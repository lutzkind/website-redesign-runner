#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from urllib.error import HTTPError, URLError
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent.parent
BUNDLED_SKILLS_DIR = BASE_DIR / "skills"
HOST = os.environ.get("WEBSITE_REDESIGN_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEBSITE_REDESIGN_PORT", "4321"))
MODEL = os.environ.get("WEBSITE_REDESIGN_MODEL", "deepseek/deepseek-v4-flash")
ROOT = Path(os.environ.get("WEBSITE_REDESIGN_ROOT", "/data"))
SKILLS_DIR = Path(os.environ.get("WEBSITE_REDESIGN_SKILLS_DIR", str(ROOT / "skills")))
DEFAULT_INDUSTRY = os.environ.get("WEBSITE_REDESIGN_DEFAULT_INDUSTRY", "general")
FIRECRAWL_URL = os.environ.get("WEBSITE_REDESIGN_FIRECRAWL_URL", "http://127.0.0.1:3092").rstrip("/")
MAX_REFERENCE_SITES = int(os.environ.get("WEBSITE_REDESIGN_MAX_REFERENCE_SITES", "3"))
FIRECRAWL_SCRAPE_TIMEOUT = int(os.environ.get("WEBSITE_REDESIGN_FIRECRAWL_TIMEOUT", "90"))
ALLOWED_GENERATOR_PROFILES = {"lean", "balanced", "quality"}
ALLOWED_IMAGE_STRATEGIES = {"source-only", "source-first", "hybrid", "stock-first"}
DEFAULT_SKILLS = [
    item.strip()
    for item in os.environ.get(
        "WEBSITE_REDESIGN_DEFAULT_SKILLS",
        "website-audit,design-direction,layout-composer,frontend-art-direction,design-critic",
    ).split(",")
    if item.strip()
]

JOBS_DIR = ROOT / "jobs"
PREVIEWS_DIR = ROOT / "previews"
STATE_LOCK = threading.Lock()


def resolve_public_base_url() -> str:
    for key in (
        "WEBSITE_REDESIGN_PUBLIC_BASE_URL",
        "SERVICE_URL_RUNNER_4321",
        "SERVICE_URL_RUNNER",
        "COOLIFY_URL",
    ):
        value = os.environ.get(key, "").strip().rstrip("/")
        if value:
            return value
    return f"http://127.0.0.1:{PORT}"


PUBLIC_BASE_URL = resolve_public_base_url()
GLOBAL_OPENCODE_CONFIG = Path(os.environ.get("OPENCODE_GLOBAL_CONFIG", "/root/.config/opencode/opencode.json"))


def ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    bootstrap_skills_dir()


def bootstrap_skills_dir() -> None:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    bundled_files = [path for path in BUNDLED_SKILLS_DIR.rglob("*.md") if path.is_file()]
    if any(SKILLS_DIR.rglob("*.md")):
        return
    for source in bundled_files:
        relative = source.relative_to(BUNDLED_SKILLS_DIR)
        destination = SKILLS_DIR / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or f"site-{uuid.uuid4().hex[:8]}"


def parse_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    return default


def parse_json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def job_state_path(job_id: str) -> Path:
    return JOBS_DIR / job_id / "state.json"


def job_dir_path(job_id: str) -> Path:
    return JOBS_DIR / job_id


def update_state(job_id: str, **fields) -> dict:
    with STATE_LOCK:
        path = job_state_path(job_id)
        state = load_json(path)
        state.update(fields)
        state["updated_at"] = now_iso()
        write_json(path, state)
        return state


def get_state(job_id: str) -> dict | None:
    path = job_state_path(job_id)
    if not path.exists():
        return None
    return load_json(path)


def run_command(
    args: list[str],
    cwd: Path | None = None,
    env: dict | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def load_global_opencode_config() -> dict:
    if not GLOBAL_OPENCODE_CONFIG.exists():
        return {}
    try:
        return json.loads(GLOBAL_OPENCODE_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_local_opencode_config(job_dir: Path) -> Path:
    global_config = load_global_opencode_config()
    mcp_config = global_config.get("mcp", {}) if isinstance(global_config, dict) else {}

    local_config: dict = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {},
        "tools": {},
    }

    for server_name, server_config in mcp_config.items():
        if not isinstance(server_config, dict):
            continue
        disabled = dict(server_config)
        disabled["enabled"] = False
        local_config["mcp"][server_name] = disabled
        local_config["tools"][f"{server_name}_*"] = False

    config_path = job_dir / "opencode.local.json"
    config_path.write_text(json.dumps(local_config, indent=2), encoding="utf-8")
    return config_path


def validate_model_policy() -> None:
    if MODEL.startswith("openrouter/"):
        raise RuntimeError(
            "OpenRouter models are disabled for this runner. "
            "Configure a non-openrouter OpenCode model before starting the service."
        )


def truncate_text(value: str, limit: int = 1800) -> str:
    value = (value or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def normalize_reference_item(item) -> dict:
    if isinstance(item, str):
        url = item.strip()
        focus = ""
    elif isinstance(item, dict):
        url = str(item.get("url", "")).strip()
        focus = str(item.get("focus", "")).strip()
    else:
        raise ValueError("design_references entries must be strings or objects")

    parsed = urlparse(url)
    if not url:
        raise ValueError("design_references entries must include a url")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid design reference URL: {url}")

    return {"url": url, "focus": focus, "hostname": parsed.netloc}


def normalize_request(payload: dict) -> dict:
    website_url = str(payload.get("website_url", "")).strip()
    if not website_url:
        raise ValueError("website_url is required")

    parsed = urlparse(website_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("website_url must be a valid http/https URL")

    refs = payload.get("design_references", [])
    if isinstance(refs, str):
        refs = [line.strip() for line in refs.splitlines() if line.strip()]
    elif not isinstance(refs, list):
        raise ValueError("design_references must be an array or newline-delimited string")

    enabled_skills = payload.get("enabled_skills")
    if enabled_skills is None:
        normalized_skills = list(DEFAULT_SKILLS)
    elif isinstance(enabled_skills, str):
        normalized_skills = [item.strip() for item in enabled_skills.split(",") if item.strip()]
    elif isinstance(enabled_skills, list):
        normalized_skills = [str(item).strip() for item in enabled_skills if str(item).strip()]
    else:
        raise ValueError("enabled_skills must be an array or comma-delimited string")

    normalized_refs = [normalize_reference_item(item) for item in refs if str(item).strip() or isinstance(item, dict)]
    client_slug = payload.get("client_slug") or parsed.netloc
    industry = slugify(str(payload.get("industry") or DEFAULT_INDUSTRY))
    generator_profile = str(payload.get("generator_profile") or "balanced").strip().lower()
    if generator_profile not in ALLOWED_GENERATOR_PROFILES:
        raise ValueError(f"generator_profile must be one of: {', '.join(sorted(ALLOWED_GENERATOR_PROFILES))}")
    image_strategy = str(payload.get("image_strategy") or "hybrid").strip().lower()
    if image_strategy not in ALLOWED_IMAGE_STRATEGIES:
        raise ValueError(f"image_strategy must be one of: {', '.join(sorted(ALLOWED_IMAGE_STRATEGIES))}")
    reference_limit = payload.get("reference_limit", MAX_REFERENCE_SITES)
    try:
        reference_limit = max(0, min(int(reference_limit), MAX_REFERENCE_SITES))
    except Exception:
        raise ValueError("reference_limit must be an integer")

    return {
        "website_url": website_url,
        "design_references": normalized_refs,
        "client_slug": slugify(str(client_slug)),
        "brand_notes": str(payload.get("brand_notes", "")).strip(),
        "dry_run": bool(payload.get("dry_run", False)),
        "hostname": parsed.netloc,
        "callback_url": str(payload.get("callback_url", "")).strip(),
        "notify_email": str(payload.get("notify_email", "")).strip(),
        "industry": industry,
        "enabled_skills": normalized_skills or list(DEFAULT_SKILLS),
        "extra_instructions": str(payload.get("extra_instructions", "")).strip(),
        "generator_profile": generator_profile,
        "image_strategy": image_strategy,
        "reuse_source_images": parse_bool(payload.get("reuse_source_images"), True),
        "allow_external_images": parse_bool(payload.get("allow_external_images"), True),
        "reference_limit": reference_limit,
        "design_goal": str(payload.get("design_goal", "")).strip(),
        "prompt_append": str(payload.get("prompt_append", "")).strip(),
    }


def list_available_skills() -> dict:
    base_skills = sorted(
        path.stem for path in SKILLS_DIR.glob("*.md") if path.is_file()
    )
    industry_skills = sorted(
        path.stem for path in (SKILLS_DIR / "industry").glob("*.md") if path.is_file()
    )
    return {
        "default_skills": list(DEFAULT_SKILLS),
        "default_industry": DEFAULT_INDUSTRY,
        "skills_dir": str(SKILLS_DIR),
        "base_skills": base_skills,
        "industry_skills": industry_skills,
    }


def resolve_skill_files(request: dict) -> list[Path]:
    skill_files: list[Path] = []
    for skill_name in request["enabled_skills"]:
        candidate = SKILLS_DIR / f"{skill_name}.md"
        if candidate.exists():
            skill_files.append(candidate)
    industry_file = SKILLS_DIR / "industry" / f"{request['industry']}.md"
    if industry_file.exists():
        skill_files.append(industry_file)
    return skill_files


def firecrawl_post(path: str, payload: dict) -> dict:
    request = Request(
        f"{FIRECRAWL_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=FIRECRAWL_SCRAPE_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Firecrawl {path} failed with HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Firecrawl {path} request failed: {exc}") from exc


def summarize_firecrawl_payload(scrape: dict, mapped_links: list[str] | None = None) -> dict:
    data = scrape.get("data", {}) if isinstance(scrape, dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
    markdown = data.get("markdown", "") if isinstance(data, dict) else ""
    html = data.get("html", "") if isinstance(data, dict) else ""
    return {
        "title": metadata.get("title", ""),
        "description": metadata.get("description", ""),
        "language": metadata.get("language", ""),
        "url": metadata.get("url") or metadata.get("sourceURL", ""),
        "markdown_excerpt": truncate_text(markdown, 2400),
        "html_excerpt": truncate_text(html, 1400),
        "top_links": mapped_links or [],
    }


def analyze_with_firecrawl(url: str, include_map: bool = False) -> dict:
    scrape = firecrawl_post("/v1/scrape", {"url": url, "formats": ["markdown", "html"]})
    mapped_links: list[str] = []
    if include_map:
        mapping = firecrawl_post("/v1/map", {"url": url, "limit": 8})
        mapped_links = mapping.get("links", [])[:8]
    return {
        "scrape": scrape,
        "summary": summarize_firecrawl_payload(scrape, mapped_links),
    }


def render_skill_bundle(skill_files: list[Path]) -> str:
    if not skill_files:
        return "No additional skill files loaded."

    sections = []
    for path in skill_files:
        body = path.read_text(encoding="utf-8").strip()
        sections.append(f"## {path.stem}\n{body}")
    return "\n\n".join(sections)


def extract_asset_candidates(html: str, base_url: str) -> list[dict]:
    if not html:
        return []

    candidates: list[dict] = []
    seen: set[str] = set()
    patterns = [
        (r"<img[^>]+src=[\"']([^\"']+)[\"'][^>]*?(?:alt=[\"']([^\"']*)[\"'])?[^>]*>", "image"),
        (r"<meta[^>]+property=[\"']og:image[\"'][^>]+content=[\"']([^\"']+)[\"'][^>]*>", "og-image"),
        (r"<meta[^>]+name=[\"']twitter:image[\"'][^>]+content=[\"']([^\"']+)[\"'][^>]*>", "social-image"),
        (r"<link[^>]+rel=[\"'][^\"']*icon[^\"']*[\"'][^>]+href=[\"']([^\"']+)[\"'][^>]*>", "icon"),
    ]
    for pattern, asset_type in patterns:
        for match in re.finditer(pattern, html, flags=re.IGNORECASE):
            src = match.group(1).strip() if match.group(1) else ""
            if not src:
                continue
            full_url = urljoin(base_url, src)
            if full_url in seen:
                continue
            seen.add(full_url)
            alt = ""
            if match.lastindex and match.lastindex > 1 and match.group(2):
                alt = match.group(2).strip()
            lower = full_url.lower()
            role = "general"
            if "logo" in lower or "brand" in lower or asset_type == "icon":
                role = "logo"
            candidates.append(
                {
                    "type": asset_type,
                    "url": full_url,
                    "alt": alt,
                    "role": role,
                }
            )
            if len(candidates) >= 12:
                return candidates
    return candidates


def fetch_source_html(job_dir: Path, request: dict) -> dict:
    source_root = job_dir / "source"
    source_root.mkdir(parents=True, exist_ok=True)
    fetch_log = source_root / "fetch.log"
    host_root = source_root / request["hostname"]
    host_root.mkdir(parents=True, exist_ok=True)
    index_file = host_root / "index.html"
    cmd = [
        "curl",
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--user-agent",
        "Mozilla/5.0 (compatible; WebsiteRedesignBot/1.0)",
        "--max-time",
        "60",
        "--output",
        str(index_file),
        request["website_url"],
    ]
    result = run_command(cmd, timeout=120)
    fetch_log.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n",
        encoding="utf-8",
    )
    if result.returncode != 0 or not index_file.exists() or index_file.stat().st_size == 0:
        raise RuntimeError("Failed to fetch source HTML")
    return {
        "exit_code": result.returncode,
        "method": "curl-fallback",
        "log": str(fetch_log),
        "source_root": str(source_root),
        "index_file": str(index_file),
    }


def analyze_site_context(job_dir: Path, request: dict) -> dict:
    source_root = job_dir / "source"
    source_root.mkdir(parents=True, exist_ok=True)
    analysis_dir = source_root / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    result: dict = {
        "source": None,
        "references": [],
    }

    try:
        source_analysis = analyze_with_firecrawl(request["website_url"], include_map=True)
        (analysis_dir / "source.json").write_text(json.dumps(source_analysis, indent=2), encoding="utf-8")
        html = source_analysis["scrape"].get("data", {}).get("html", "")
        host_root = source_root / request["hostname"]
        host_root.mkdir(parents=True, exist_ok=True)
        (host_root / "index.html").write_text(html, encoding="utf-8")
        asset_candidates = extract_asset_candidates(html, request["website_url"])
        result["source"] = {
            "method": "firecrawl",
            "analysis_file": str(analysis_dir / "source.json"),
            "source_root": str(source_root),
            "index_file": str(host_root / "index.html"),
            "summary": source_analysis["summary"],
            "asset_candidates": asset_candidates,
        }
    except Exception as exc:
        fallback = fetch_source_html(job_dir, request)
        fallback["warning"] = f"Firecrawl source analysis unavailable: {exc}"
        try:
            html = Path(fallback["index_file"]).read_text(encoding="utf-8")
            fallback["asset_candidates"] = extract_asset_candidates(html, request["website_url"])
        except Exception:
            fallback["asset_candidates"] = []
        result["source"] = fallback

    for index, reference in enumerate(request["design_references"][: request["reference_limit"]], start=1):
        slug = slugify(reference["hostname"])
        try:
            ref_analysis = analyze_with_firecrawl(reference["url"], include_map=False)
            ref_assets = extract_asset_candidates(
                ref_analysis["scrape"].get("data", {}).get("html", ""),
                reference["url"],
            )
            payload = {
                "reference": reference,
                "analysis": ref_analysis,
                "asset_candidates": ref_assets,
            }
            output_file = analysis_dir / f"reference-{index:02d}-{slug}.json"
            output_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            result["references"].append(
                {
                    "url": reference["url"],
                    "focus": reference["focus"],
                    "analysis_file": str(output_file),
                    "summary": ref_analysis["summary"],
                    "asset_candidates": ref_assets,
                }
            )
        except Exception as exc:
            result["references"].append(
                {
                    "url": reference["url"],
                    "focus": reference["focus"],
                    "error": str(exc),
                }
            )

    return result


def profile_limits(profile: str) -> dict:
    if profile == "lean":
        return {"source_chars": 700, "reference_chars": 280, "links": 4, "assets": 4}
    if profile == "quality":
        return {"source_chars": 1200, "reference_chars": 520, "links": 8, "assets": 8}
    return {"source_chars": 900, "reference_chars": 380, "links": 6, "assets": 6}


def render_asset_guidance(request: dict, source_assets: list[dict]) -> str:
    strategy = request["image_strategy"]
    if strategy == "source-only":
        mode = "Use only source-site assets and logos. Do not introduce external imagery."
    elif strategy == "source-first":
        mode = "Prefer source-site assets and logos. Only use external imagery if the source lacks a credible hero image."
    elif strategy == "stock-first":
        mode = "Prefer external editorial/stock imagery while preserving any usable source logo or icon."
    else:
        mode = "Use a hybrid approach: preserve any usable logo or brand mark, reuse good source photos when credible, and supplement weak imagery with high-quality external/editorial imagery."

    external = (
        "External imagery is allowed."
        if request["allow_external_images"]
        else "External imagery is not allowed; work only with source assets and non-photographic treatments."
    )
    reuse = (
        "Reusing source images is encouraged when quality is acceptable."
        if request["reuse_source_images"]
        else "Do not reuse source photography unless absolutely necessary."
    )
    candidates = "\n".join(
        f"- {item['url']} ({item.get('role', 'general')}{', alt=' + item['alt'] if item.get('alt') else ''})"
        for item in source_assets[:8]
    ) or "- None detected"
    return f"""{mode}
{external}
{reuse}

Detected source asset candidates:
{candidates}
"""


def build_prompt_parts(request: dict, job_dir: Path) -> tuple[dict, list[str]]:
    source_context = request.get("source_context") or {}
    source = source_context.get("source", {})
    source_summary = source.get("summary", {})
    ref_contexts = source_context.get("references", [])
    limits = profile_limits(request["generator_profile"])
    source_assets = source.get("asset_candidates", []) or []

    ref_lines = []
    for item in ref_contexts:
        if item.get("summary"):
            summary = item["summary"]
            ref_lines.append(
                "\n".join(
                    [
                        f"- URL: {item['url']}",
                        f"  Focus: {item.get('focus') or 'General visual direction'}",
                        f"  Title: {summary.get('title', '')}",
                        f"  Notes: {truncate_text(summary.get('markdown_excerpt', ''), limits['reference_chars'])}",
                    ]
                )
            )
        else:
            ref_lines.append(
                "\n".join(
                    [
                        f"- URL: {item['url']}",
                        f"  Focus: {item.get('focus') or 'General visual direction'}",
                        f"  Analysis status: {item.get('error', 'Not analyzed')}",
                    ]
                )
            )

    skill_files = resolve_skill_files(request)
    skill_names = [path.stem for path in skill_files]
    skill_bundle = render_skill_bundle(skill_files)

    stable_prefix = f"""You are redesigning a client's website into a polished static preview.

Follow these standing rules exactly:
1. Build a redesigned static website preview in ./dist.
2. Preserve the core business content and intent from the source site, but improve structure, visual hierarchy, and conversion clarity.
3. Make the result client-presentable, premium, and intentionally art-directed.
4. Ensure ./dist/index.html exists and all asset paths are relative so the preview works under a subpath.
5. Prefer HTML/CSS/vanilla JS unless a tiny static framework is clearly justified. Do not require a build step for previewing.
6. Write a concise implementation summary to ./dist/redesign-summary.md.
7. Before finishing, verify the preview files exist in ./dist.

Skill directives:
{skill_bundle}
"""

    operator_controls = f"""Operator controls:
- Industry: {request['industry']}
- Generator profile: {request['generator_profile']}
- Design goal: {request['design_goal'] or 'General premium redesign'}
- Brand notes: {request['brand_notes'] or 'None'}
- Additional instructions: {request['extra_instructions'] or 'None'}
- Prompt append: {request['prompt_append'] or 'None'}
"""

    source_context_block = f"""Source website:
- URL: {request['website_url']}
- Captured source HTML is available under ./source
- Source title: {source_summary.get('title', '')}
- Source summary:
{truncate_text(source_summary.get('markdown_excerpt', '') or 'No Firecrawl summary captured.', limits['source_chars'])}
- Important discovered links:
{chr(10).join(f"  - {link}" for link in source_summary.get('top_links', [])[:limits['links']]) or '  - None'}
"""

    reference_block = "Design references:\n" + ("\n".join(ref_lines) if ref_lines else "- None supplied")
    asset_block = "Image and asset strategy:\n" + render_asset_guidance(request, source_assets)

    implementation_block = """Implementation expectations:
- Use the design references for layout, typography, spacing, rhythm, and visual tone, but do not copy branding directly.
- Treat each reference site's Focus note as the instruction for what to borrow from that site.
- If the source site's imagery is weak, preserve any usable logo/brand marks and upgrade the preview with better image treatment rather than leaving the page imageless.
- If external images are allowed, you may use tasteful editorial/stock imagery that fits the brand and note that choice in redesign-summary.md.
- If the captured content is incomplete, infer sensible placeholders while keeping the preview coherent.
- Avoid generic AI landing-page patterns, default fonts, and flat section stacking.
"""

    parts = {
        "stable_prefix": stable_prefix,
        "operator_controls": operator_controls,
        "source_context": source_context_block,
        "reference_context": reference_block,
        "asset_strategy": asset_block,
        "implementation_expectations": implementation_block,
    }
    return parts, skill_names


def build_prompt(request: dict, job_dir: Path) -> tuple[str, list[str]]:
    parts, skill_names = build_prompt_parts(request, job_dir)
    prompt = "\n\n".join(parts.values())
    (job_dir / "prompt.parts.json").write_text(json.dumps(parts, indent=2), encoding="utf-8")
    return prompt, skill_names


def create_dry_run_preview(job_dir: Path, request: dict, applied_skills: list[str]) -> None:
    dist = job_dir / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    index_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Preview for {request["client_slug"]}</title>
    <style>
      :root {{
        --bg: #110f12;
        --panel: rgba(255,255,255,0.08);
        --text: #f5f2ea;
        --muted: #cabfb1;
        --accent: #a5242b;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: "Georgia", serif;
        color: var(--text);
        background:
          radial-gradient(circle at top, rgba(165, 36, 43, 0.35), transparent 40%),
          linear-gradient(145deg, #0b0a0c, #19151b 55%, #0f1216);
        min-height: 100vh;
      }}
      main {{
        max-width: 1100px;
        margin: 0 auto;
        padding: 72px 24px;
      }}
      .panel {{
        border: 1px solid rgba(255,255,255,0.08);
        background: var(--panel);
        backdrop-filter: blur(10px);
        border-radius: 32px;
        padding: 40px;
        box-shadow: 0 40px 120px rgba(0,0,0,0.32);
      }}
      .eyebrow {{
        text-transform: uppercase;
        letter-spacing: 0.2em;
        color: var(--muted);
        font-size: 12px;
      }}
      h1 {{
        font-size: clamp(48px, 10vw, 94px);
        line-height: 0.92;
        margin: 12px 0 16px;
        max-width: 8ch;
      }}
      p, li {{
        color: var(--muted);
        font-size: 18px;
        line-height: 1.7;
      }}
      .accent {{
        color: var(--accent);
      }}
    </style>
  </head>
  <body>
    <main>
      <section class="panel">
        <div class="eyebrow">Dry Run Preview</div>
        <h1>{request["client_slug"]} <span class="accent">concept</span></h1>
        <p>This placeholder confirms the workflow, preview publish path, and skill loading for the redesigned runner repo.</p>
        <ul>
          <li>Source URL: {request["website_url"]}</li>
          <li>Industry: {request["industry"]}</li>
          <li>Skills: {", ".join(applied_skills) or "None"}</li>
          <li>References: {", ".join(item["url"] for item in request["design_references"]) or "None"}</li>
        </ul>
      </section>
    </main>
  </body>
</html>
"""
    (dist / "index.html").write_text(index_html, encoding="utf-8")
    (dist / "redesign-summary.md").write_text(
        "Dry run mode generated a placeholder preview without calling OpenCode.\n",
        encoding="utf-8",
    )


def run_opencode_redesign(job_dir: Path, request: dict) -> dict:
    prompt, applied_skills = build_prompt(request, job_dir)
    prompt_file = job_dir / "prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    local_config_path = build_local_opencode_config(job_dir)
    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(local_config_path)
    cmd = [
        "opencode",
        "run",
        prompt,
        "--model",
        MODEL,
        "--dir",
        str(job_dir),
    ]
    result = run_command(cmd, cwd=job_dir, env=env, timeout=7200)
    log_path = job_dir / "opencode.log"
    log_path.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n",
        encoding="utf-8",
    )
    return {
        "exit_code": result.returncode,
        "log": str(log_path),
        "applied_skills": applied_skills,
        "opencode_config": str(local_config_path),
    }


def publish_preview(job_dir: Path, slug: str) -> str:
    dist = job_dir / "dist"
    if not dist.exists() or not (dist / "index.html").exists():
        raise RuntimeError("dist/index.html was not generated")
    target = PREVIEWS_DIR / slug
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(dist, target)
    return f"{PUBLIC_BASE_URL}/preview/{slug}/"


def send_callback(callback_url: str, state: dict) -> None:
    if not callback_url:
        return
    payload = json.dumps(state).encode("utf-8")
    request = Request(
        callback_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        response.read()


def safe_send_callback(job_id: str, callback_url: str, state: dict) -> None:
    try:
        send_callback(callback_url, state)
    except Exception as exc:
        update_state(job_id, callback_error=str(exc))


def send_job_email(request: dict, state: dict) -> dict | None:
    notify_email = request.get("notify_email", "").strip()
    if not notify_email:
        return None

    success = state.get("status") == "completed"
    subject = (
        f"Website redesign preview ready: {request['client_slug']}"
        if success
        else f"Website redesign job failed: {request['client_slug']}"
    )
    body_lines = [
        "Your redesign preview is ready." if success else "Your redesign job failed.",
        "",
        f"Source site: {request['website_url']}",
        f"Job ID: {state.get('job_id', '')}",
        f"Model: {state.get('model', MODEL)}",
        f"Industry: {request.get('industry', DEFAULT_INDUSTRY)}",
        f"Skills: {', '.join(state.get('applied_skills', [])) or ', '.join(request.get('enabled_skills', []))}",
        f"Status URL: {PUBLIC_BASE_URL}/jobs/{state.get('job_id', '')}",
    ]
    if success:
        body_lines.append(f"Preview URL: {state.get('preview_url', '')}")
    else:
        body_lines.append(f"Error: {state.get('error', 'Unknown error')}")
    body_lines.extend(["", "This job was processed automatically."])

    cmd = [
        "gws-email",
        "--to",
        notify_email,
        "--subject",
        subject,
        "--body",
        "\n".join(body_lines),
    ]
    result = run_command(cmd, timeout=120)
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def process_job(job_id: str, request: dict) -> None:
    job_dir = job_dir_path(job_id)
    try:
        update_state(job_id, status="running", step="capturing-source", model=MODEL)
        source_context = analyze_site_context(job_dir, request)
        request["source_context"] = source_context
        update_state(job_id, source_capture=source_context)

        if request["dry_run"]:
            _, applied_skills = build_prompt(request, job_dir)
            update_state(job_id, step="creating-dry-run-preview", applied_skills=applied_skills)
            create_dry_run_preview(job_dir, request, applied_skills)
            opencode_result = {"exit_code": 0, "log": None, "dry_run": True, "applied_skills": applied_skills}
        else:
            update_state(job_id, step="running-opencode")
            opencode_result = run_opencode_redesign(job_dir, request)
            if opencode_result["exit_code"] != 0:
                raise RuntimeError(f"OpenCode exited with code {opencode_result['exit_code']}")

        update_state(
            job_id,
            step="publishing-preview",
            opencode=opencode_result,
            applied_skills=opencode_result.get("applied_skills", []),
        )
        preview_url = publish_preview(job_dir, request["client_slug"])
        update_state(
            job_id,
            status="completed",
            step="completed",
            preview_url=preview_url,
            preview_slug=request["client_slug"],
        )
        completion_state = get_state(job_id) or {}
        email_result = send_job_email(request, completion_state)
        if email_result is not None:
            completion_state = update_state(job_id, email=email_result)
        safe_send_callback(job_id, request["callback_url"], completion_state)
    except Exception as exc:
        failed_state = update_state(
            job_id,
            status="failed",
            step="failed",
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        email_result = send_job_email(request, failed_state)
        if email_result is not None:
            failed_state = update_state(job_id, email=email_result)
        safe_send_callback(job_id, request["callback_url"], failed_state)


class Handler(BaseHTTPRequestHandler):
    server_version = "WebsiteRedesignRunner/0.2"

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path, content_type: str) -> None:
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self._send_json(
                {
                    "healthy": True,
                    "model": MODEL,
                    "public_base_url": PUBLIC_BASE_URL,
                    "firecrawl_url": FIRECRAWL_URL,
                    "model_policy": "deny-openrouter",
                    "generator_profiles": sorted(ALLOWED_GENERATOR_PROFILES),
                    "image_strategies": sorted(ALLOWED_IMAGE_STRATEGIES),
                    "skills": list_available_skills(),
                }
            )
            return

        if parsed.path == "/skills":
            self._send_json(list_available_skills())
            return

        if parsed.path.startswith("/skills/"):
            relative = unquote(parsed.path[len("/skills/"):]).lstrip("/")
            safe = Path(relative)
            if ".." in safe.parts:
                self._send_json({"error": "invalid path"}, status=400)
                return
            if safe.suffix != ".md":
                safe = safe.with_suffix(".md")
            skill_path = SKILLS_DIR / safe
            if not skill_path.exists() or not skill_path.is_file():
                self._send_json({"error": "skill not found"}, status=404)
                return
            self._send_json(
                {
                    "name": skill_path.stem,
                    "path": str(skill_path),
                    "content": skill_path.read_text(encoding="utf-8"),
                }
            )
            return

        if parsed.path.startswith("/jobs/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 3 and parts[2] == "prompt":
                job_id = parts[1]
                prompt_path = job_dir_path(job_id) / "prompt.txt"
                if not prompt_path.exists():
                    self._send_json({"error": "prompt not found"}, status=404)
                    return
                self._send_file(prompt_path, "text/plain; charset=utf-8")
                return
            if len(parts) >= 3 and parts[2] == "prompt-parts":
                job_id = parts[1]
                prompt_parts_path = job_dir_path(job_id) / "prompt.parts.json"
                if not prompt_parts_path.exists():
                    self._send_json({"error": "prompt parts not found"}, status=404)
                    return
                self._send_file(prompt_parts_path, "application/json; charset=utf-8")
                return

            job_id = parts[1]
            state = get_state(job_id)
            if not state:
                self._send_json({"error": "job not found"}, status=404)
                return
            self._send_json(state)
            return

        if parsed.path.startswith("/preview/"):
            relative = unquote(parsed.path[len("/preview/"):]).lstrip("/")
            safe = Path(relative)
            if ".." in safe.parts:
                self._send_json({"error": "invalid path"}, status=400)
                return
            file_path = PREVIEWS_DIR / safe
            if file_path.is_dir():
                file_path = file_path / "index.html"
            if not file_path.exists():
                self._send_json({"error": "preview not found"}, status=404)
                return
            content_types = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".gif": "image/gif",
                ".woff": "font/woff",
                ".woff2": "font/woff2",
                ".md": "text/markdown; charset=utf-8",
            }
            self._send_file(file_path, content_types.get(file_path.suffix.lower(), "application/octet-stream"))
            return

        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/jobs":
            self._send_json({"error": "not found"}, status=404)
            return

        try:
            payload = parse_json_body(self)
            request = normalize_request(payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        job_id = f"job_{uuid.uuid4().hex[:12]}"
        job_dir = job_dir_path(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "job_id": job_id,
            "status": "queued",
            "step": "queued",
            "request": request,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "model": MODEL,
        }
        write_json(job_state_path(job_id), state)

        thread = threading.Thread(target=process_job, args=(job_id, request), daemon=True)
        thread.start()
        self._send_json(
            {
                "job_id": job_id,
                "status": "queued",
                "status_url": f"{PUBLIC_BASE_URL}/jobs/{job_id}",
                "prompt_url": f"{PUBLIC_BASE_URL}/jobs/{job_id}/prompt",
                "prompt_parts_url": f"{PUBLIC_BASE_URL}/jobs/{job_id}/prompt-parts",
            },
            status=HTTPStatus.ACCEPTED,
        )


def main() -> None:
    validate_model_policy()
    ensure_dirs()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"website redesign runner listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

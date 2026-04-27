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
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent.parent
HOST = os.environ.get("WEBSITE_REDESIGN_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEBSITE_REDESIGN_PORT", "4321"))
PUBLIC_BASE_URL = os.environ.get(
    "WEBSITE_REDESIGN_PUBLIC_BASE_URL",
    "http://127.0.0.1:4321",
).rstrip("/")
MODEL = os.environ.get("WEBSITE_REDESIGN_MODEL", "opencode/big-pickle")
ROOT = Path(os.environ.get("WEBSITE_REDESIGN_ROOT", "/data"))
SKILLS_DIR = Path(os.environ.get("WEBSITE_REDESIGN_SKILLS_DIR", str(BASE_DIR / "skills")))
DEFAULT_INDUSTRY = os.environ.get("WEBSITE_REDESIGN_DEFAULT_INDUSTRY", "general")
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


def ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or f"site-{uuid.uuid4().hex[:8]}"


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

    normalized_refs = [str(item).strip() for item in refs if str(item).strip()]
    client_slug = payload.get("client_slug") or parsed.netloc
    industry = slugify(str(payload.get("industry") or DEFAULT_INDUSTRY))

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


def render_skill_bundle(skill_files: list[Path]) -> str:
    if not skill_files:
        return "No additional skill files loaded."

    sections = []
    for path in skill_files:
        body = path.read_text(encoding="utf-8").strip()
        sections.append(f"## {path.stem}\n{body}")
    return "\n\n".join(sections)


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
        "log": str(fetch_log),
        "source_root": str(source_root),
        "index_file": str(index_file),
    }


def build_prompt(request: dict, job_dir: Path) -> tuple[str, list[str]]:
    refs = "\n".join(f"- {item}" for item in request["design_references"]) or "- None supplied"
    notes = request["brand_notes"] or "No extra brand notes provided."
    extra = request["extra_instructions"] or "None."
    skill_files = resolve_skill_files(request)
    skill_names = [path.stem for path in skill_files]
    skill_bundle = render_skill_bundle(skill_files)

    prompt = f"""You are redesigning a client's website into a polished static preview.

Source website:
- URL: {request["website_url"]}
- Captured source HTML is available under ./source

Design references:
{refs}

Brand notes:
{notes}

Industry:
- {request["industry"]}

Additional instructions:
{extra}

Skill directives:
{skill_bundle}

Requirements:
1. Build a redesigned static website preview in ./dist.
2. Preserve the core content, sections, and intent from the source site where practical.
3. Use the design references for layout, typography, spacing, and visual direction, but do not copy branding directly.
4. Ensure ./dist/index.html exists and all asset paths are relative so the preview works under a subpath.
5. Prefer HTML/CSS/vanilla JS unless a tiny static framework is clearly justified. Do not require a build step for previewing.
6. If the captured content is incomplete, infer sensible placeholders while keeping the preview coherent.
7. Write a short implementation summary to ./dist/redesign-summary.md.
8. Favor a premium result over a safe one. Avoid default-looking landing pages.

Before finishing:
- Verify the preview files exist in ./dist.
- Keep the result client-presentable.
"""
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
          <li>References: {", ".join(request["design_references"]) or "None"}</li>
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
    cmd = [
        "opencode",
        "run",
        prompt,
        "--model",
        MODEL,
        "--dir",
        str(job_dir),
    ]
    result = run_command(cmd, cwd=job_dir, timeout=7200)
    log_path = job_dir / "opencode.log"
    log_path.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n",
        encoding="utf-8",
    )
    return {
        "exit_code": result.returncode,
        "log": str(log_path),
        "applied_skills": applied_skills,
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
        fetch_result = fetch_source_html(job_dir, request)
        update_state(job_id, source_capture=fetch_result)

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
                    "skills": list_available_skills(),
                }
            )
            return

        if parsed.path == "/skills":
            self._send_json(list_available_skills())
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
            },
            status=HTTPStatus.ACCEPTED,
        )


def main() -> None:
    ensure_dirs()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"website redesign runner listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

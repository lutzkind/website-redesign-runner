#!/usr/bin/env python3
"""
SaaS server + SPA for the redesign runner.
"""

import json
import os
import shutil
import subprocess
import threading
import traceback
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import saas_schema as db

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
HOST = os.environ.get("SAAS_HOST", "0.0.0.0")
PORT = int(os.environ.get("SAAS_PORT", "4322"))
ROOT = Path(os.environ.get("WEBSITE_REDESIGN_ROOT", "/data"))
PUBLIC_BASE_URL = os.environ.get("SAAS_PUBLIC_URL", "http://localhost:4322").rstrip("/")
RUNNER_BASE_URL = os.environ.get("RUNNER_BASE_URL", "http://localhost:4321").rstrip("/")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("SAAS_FROM_EMAIL", "noreply@webredesign.ai")
CADDY_API_URL = os.environ.get("CADDY_API_URL", "http://caddy:2019")
CREDIT_PACK_PRICE_ID = os.environ.get("STRIPE_CREDIT_PRICE_ID", "")
HOSTED_MONTHLY_PRICE_ID = os.environ.get("STRIPE_HOSTED_MONTHLY_PRICE_ID", os.environ.get("STRIPE_PRO_PRICE_ID", ""))
HOSTED_YEARLY_PRICE_ID = os.environ.get("STRIPE_HOSTED_YEARLY_PRICE_ID", "")
ONEOFF_PRICE_ID = os.environ.get("STRIPE_ONEOFF_PRICE_ID", os.environ.get("STRIPE_EXPORT_PRICE_ID", ""))
MIGRATION_CTA_URL = os.environ.get("MIGRATION_CTA_URL", f"mailto:{FROM_EMAIL}?subject=Migration%20help")
HOSTED_MONTHLY_CENTS = int(os.environ.get("HOSTED_MONTHLY_CENTS", "1900"))
HOSTED_YEARLY_CENTS = int(os.environ.get("HOSTED_YEARLY_CENTS", str(int(HOSTED_MONTHLY_CENTS * 12 * 0.8))))
CREDIT_PACK_CENTS = int(os.environ.get("CREDIT_PACK_CENTS", "900"))
CREDIT_PACK_SIZE = int(os.environ.get("CREDIT_PACK_SIZE", "5"))
ONEOFF_CENTS = int(os.environ.get("ONEOFF_CENTS", "19900"))
GWS_SEND_BIN = os.environ.get("GWS_SEND_BIN", "gws")

SITES_DIR = ROOT / "sites"
EXPORTS_DIR = ROOT / "exports"
JOBS_DIR = ROOT / "jobs"
SCREENSHOTS_DIR = ROOT / "screenshots"

for directory in (SITES_DIR, EXPORTS_DIR, JOBS_DIR, SCREENSHOTS_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def send_json(handler, payload: dict, status: int = 200):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def send_error(handler, message: str, status: int = 400, **extra):
    payload = {"error": message}
    payload.update(extra)
    send_json(handler, payload, status)


def json_body(handler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def get_client_ip(handler) -> str:
    forwarded = handler.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = handler.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return handler.client_address[0]


def resolve_public_base(handler=None) -> str:
    configured = (os.environ.get("SAAS_PUBLIC_URL") or "").rstrip("/")
    if configured and "yourdomain.com" not in configured:
        return configured
    coolify_url = (os.environ.get("COOLIFY_URL") or "").rstrip("/")
    if handler:
        proto = handler.headers.get("X-Forwarded-Proto", "")
        host = handler.headers.get("X-Forwarded-Host", "") or handler.headers.get("Host", "")
        if host:
            scheme = proto or (urlparse(coolify_url).scheme if coolify_url else "http")
            return f"{scheme}://{host}"
    if coolify_url:
        return coolify_url
    return PUBLIC_BASE_URL


def preview_url_for_public(raw_url: str, handler=None) -> str:
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    if parsed.path.startswith("/preview/"):
        base = resolve_public_base(handler)
        rebuilt = parsed._replace(scheme=urlparse(base).scheme, netloc=urlparse(base).netloc)
        return urlunparse(rebuilt)
    return raw_url


def require_auth(handler):
    auth = handler.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return db.get_user_by_session(auth[7:])


def send_email(to: str, subject: str, body_html: str) -> bool:
    if not SENDGRID_API_KEY:
        try:
            subprocess.run(
                [
                    GWS_SEND_BIN,
                    "gmail",
                    "+send",
                    "--to",
                    to,
                    "--subject",
                    subject,
                    "--body",
                    body_html,
                    "--html",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return True
        except Exception as exc:
            print(f"[email] gws fallback failed for {to}: {exc}", flush=True)
            return False
    payload = json.dumps(
        {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": FROM_EMAIL},
            "subject": subject,
            "content": [{"type": "text/html", "value": body_html}],
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=payload,
        headers={
            "Authorization": f"Bearer {SENDGRID_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20):
            return True
    except Exception as exc:
        print(f"[email] error: {exc}", flush=True)
        return False


def dig_record(domain: str, record_type: str = "A") -> str | None:
    try:
        result = subprocess.run(
            ["dig", "+short", "-t", record_type, domain],
            capture_output=True,
            text=True,
            timeout=10,
        )
        value = result.stdout.strip()
        return value or None
    except Exception:
        return None


def dig_all(domain: str) -> dict:
    return {
        "a": dig_record(domain, "A"),
        "mx": dig_record(domain, "MX"),
        "txt": dig_record(domain, "TXT"),
        "cname": dig_record(domain, "CNAME"),
        "www_a": dig_record(f"www.{domain}", "A"),
    }


def dns_check(domain: str, expected_ip: str = "") -> dict:
    records = dig_all(domain)
    a_record = records.get("a")
    return {
        "domain": domain,
        "a_record": a_record,
        "points_to_me": bool(expected_ip and a_record == expected_ip),
        "mx_present": bool(records.get("mx")),
        "warnings": ["Existing MX records will not be changed."] if records.get("mx") else [],
        "records": records,
    }


def caddy_add_domain(domain: str, site_path: str) -> bool:
    route = {
        "@id": f"domain-{domain}",
        "match": [{"host": [domain]}],
        "handle": [
            {
                "handler": "subroute",
                "routes": [
                    {
                        "handle": [
                            {
                                "handler": "file_server",
                                "root": site_path,
                            }
                        ]
                    }
                ],
            }
        ],
        "terminal": True,
    }
    req = urllib.request.Request(
        f"{CADDY_API_URL}/config/apps/http/servers/srv0/routes/",
        data=json.dumps(route).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status in (200, 201)
    except Exception:
        return False


def price_catalog() -> dict:
    return {
        "credit_pack": {
            "price_id": CREDIT_PACK_PRICE_ID,
            "price_cents": CREDIT_PACK_CENTS,
            "credits": CREDIT_PACK_SIZE,
            "label": f"{CREDIT_PACK_SIZE} redesign credits",
        },
        "hosted_monthly": {
            "price_id": HOSTED_MONTHLY_PRICE_ID,
            "price_cents": HOSTED_MONTHLY_CENTS,
            "label": "$19 hosted plan",
        },
        "hosted_yearly": {
            "price_id": HOSTED_YEARLY_PRICE_ID,
            "price_cents": HOSTED_YEARLY_CENTS,
            "discount_percent": 20,
            "label": "Yearly hosted plan",
        },
        "oneoff_unlock": {
            "price_id": ONEOFF_PRICE_ID,
            "price_cents": ONEOFF_CENTS,
            "label": "One-off purchase",
        },
        "migration": {
            "contact_url": MIGRATION_CTA_URL,
            "label": "Migration add-on",
        },
    }


def stripe_request(method: str, path: str, form: dict | None = None, query: list[tuple[str, str]] | None = None) -> dict | None:
    if not STRIPE_SECRET_KEY:
        return None
    url = f"https://api.stripe.com{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    body = urlencode(form or {}).encode() if form is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {STRIPE_SECRET_KEY}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode())
    except Exception as exc:
        print(f"[stripe] {method} {path} failed: {exc}", flush=True)
        return None


def create_site_for_user(user_id: int, source_url: str, title: str, normalized_domain: str) -> dict:
    base_slug = db.slugify(title or normalized_domain)
    candidate = base_slug
    for _ in range(6):
        site = db.create_site(
            user_id,
            slug=candidate,
            source_url=source_url,
            title=title or normalized_domain,
            normalized_domain=normalized_domain,
        )
        if site:
            return site
        candidate = f"{base_slug}-{uuid.uuid4().hex[:6]}"
    raise RuntimeError("Could not create a unique site slug")


def create_stripe_checkout(
    price_id: str,
    success_url: str,
    cancel_url: str,
    customer_email: str = "",
    metadata: dict | None = None,
    mode: str = "payment",
) -> dict | None:
    if not STRIPE_SECRET_KEY or not price_id:
        return None
    metadata = metadata or {}
    form = {
        "mode": mode,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "allow_promotion_codes": "true",
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
    }
    if mode == "payment":
        form["customer_creation"] = "always"
    if customer_email:
        form["customer_email"] = customer_email
    for key, value in metadata.items():
        if value is not None:
            form[f"metadata[{key}]"] = str(value)
    return stripe_request("POST", "/v1/checkout/sessions", form=form)


def unique_site_slug(domain: str, company_name: str = "") -> str:
    base = db.slugify(company_name or domain)
    candidate = base
    suffix = 1
    while db.get_site_by_domain(candidate):  # harmless if candidate matches an actual domain only once
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def site_payload(site: dict, user: dict | None = None) -> dict:
    active_sub = db.get_user_subscription(site["user_id"])
    hosted_active = bool(active_sub)
    offer = db.get_outreach_offer_by_site(site["id"])
    payload = dict(site)
    payload["preview_url"] = preview_url_for_public(site.get("preview_url", ""))
    payload["preview_image_url"] = site.get("preview_image_url", "")
    payload["access"] = {
        "preview_ready": bool(payload["preview_url"]),
        "hosted_active": hosted_active,
        "oneoff_unlocked": bool(site.get("oneoff_unlocked")),
        "free_preview_used": bool(site.get("free_preview_used")),
        "subscription_plan": active_sub["plan_code"] if active_sub else None,
        "offer_token": offer["token"] if offer else None,
    }
    if user:
        balance = db.get_credit_balance(user["id"])
        payload["access"]["credits"] = balance["credits"]
    return payload


def capture_preview_screenshot(site_id: int, preview_url: str):
    if not preview_url:
        return
    output_path = SCREENSHOTS_DIR / f"site-{site_id}.png"
    try:
        subprocess.run(
            ["node", str(BASE_DIR / "app" / "capture_screenshot.mjs"), preview_url, str(output_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
        )
        db.update_site(
            site_id,
            preview_image_url=f"/api/screenshots/{output_path.name}",
            preview_image_captured_at=now_iso(),
        )
    except Exception as exc:
        print(f"[preview] screenshot capture failed for site {site_id}: {exc}", flush=True)


def queue_preview_capture(site: dict):
    if not shutil.which("node"):
        return
    preview_url = site.get("preview_url", "")
    if not preview_url:
        return
    if site.get("preview_image_url") and site.get("preview_image_captured_at"):
        return
    thread = threading.Thread(target=capture_preview_screenshot, args=(site["id"], preview_url), daemon=True)
    thread.start()


def update_site_from_job_state(site: dict) -> dict:
    job_id = site.get("current_job_id")
    if not job_id:
        return site
    state_file = JOBS_DIR / job_id / "state.json"
    if not state_file.exists():
        return site
    try:
        state = json.loads(state_file.read_text())
    except Exception:
        return site
    updates = {}
    preview_url = preview_url_for_public(state.get("preview_url", ""))
    if preview_url and preview_url != site.get("preview_url"):
        updates["preview_url"] = preview_url
        updates["preview_image_url"] = None
        updates["preview_image_captured_at"] = None
    if state.get("status") == "completed":
        updates["status"] = "preview_ready"
    elif state.get("status") == "failed":
        updates["status"] = "failed"
    elif state.get("status"):
        updates["status"] = "rendering"
    if updates:
        db.update_site(site["id"], **updates)
        site = db.get_site(site["id"])
        offer = db.get_outreach_offer_by_site(site["id"])
        if offer and site.get("preview_url") and offer.get("preview_url") != site.get("preview_url"):
            conn = db.get_db()
            conn.execute(
                "UPDATE outreach_offers SET preview_url = ?, updated_at = ? WHERE id = ?",
                (site["preview_url"], now_iso(), offer["id"]),
            )
            conn.commit()
            conn.close()
        queue_preview_capture(site)
    return site


def submit_runner_job(site: dict, prompt: str = "", industry: str = "general", design_goal: str = "") -> dict:
    payload = {
        "website_url": site["source_url"],
        "client_slug": site["slug"],
        "extra_instructions": prompt,
        "industry": industry,
        "design_goal": design_goal,
        "notify_email": "",
        "generator_profile": "balanced",
        "image_strategy": "hybrid",
        "impeccable_critique": True,
        "impeccable_autofix": True,
        "reuse_source_images": True,
        "allow_external_images": True,
        "design_references": [],
    }
    request = urllib.request.Request(
        f"{RUNNER_BASE_URL}/jobs",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode())
    if result.get("job_id"):
        db.update_site(site["id"], current_job_id=result["job_id"], status="rendering")
    return result


def issue_login_link(email: str, redirect_path: str, handler=None) -> tuple[bool, str]:
    token = db.create_login_token(email, redirect_path=redirect_path)
    login_url = f"{resolve_public_base(handler)}/login?token={token}"
    body = f"""
    <h2>Your redesigned site is ready to review</h2>
    <p>Use the secure sign-in link below:</p>
    <p><a href="{login_url}">{login_url}</a></p>
    <p>This link expires in one hour.</p>
    """
    sent = send_email(email, "Your WebRedesign sign-in link", body)
    return sent, login_url


def finalize_checkout_session(session_id: str, handler=None, expected_user_id: int = 0, expected_offer_token: str = "") -> dict:
    if not session_id:
        raise ValueError("session_id required")
    existing = db.get_checkout_fulfillment(session_id)
    if existing and existing.get("status") == "fulfilled":
        user = db.get_user_by_id(existing["user_id"]) if existing.get("user_id") else None
        existing["site"] = site_payload(db.get_site(existing["site_id"]), user) if existing.get("site_id") else None
        existing["offer"] = db.get_outreach_offer_by_token(existing["offer_token"]) if existing.get("offer_token") else None
        return existing
    session = stripe_request(
        "GET",
        f"/v1/checkout/sessions/{session_id}",
        query=[
            ("expand[]", "customer"),
            ("expand[]", "subscription"),
        ],
    )
    if not session:
        raise RuntimeError("Could not retrieve checkout session from Stripe.")
    if session.get("status") != "complete":
        raise RuntimeError("Checkout session is not complete yet.")
    if session.get("mode") == "payment" and session.get("payment_status") not in {"paid", "no_payment_required"}:
        raise RuntimeError("Payment is not complete yet.")
    metadata = session.get("metadata", {}) or {}
    user_id = int(metadata.get("user_id", 0) or 0)
    site_id = int(metadata.get("site_id", 0) or 0)
    plan_code = metadata.get("plan_code", "")
    offer_token = metadata.get("offer_token", "")
    if expected_user_id and expected_user_id != user_id:
        raise RuntimeError("Checkout session does not belong to this account.")
    if expected_offer_token and expected_offer_token != offer_token:
        raise RuntimeError("Checkout session does not belong to this offer.")
    if not user_id or not plan_code:
        raise RuntimeError("Checkout session is missing fulfillment metadata.")

    fulfillment = existing or db.start_checkout_fulfillment(
        session_id=session_id,
        user_id=user_id,
        site_id=site_id or None,
        offer_token=offer_token,
        customer_email=session.get("customer_details", {}).get("email", ""),
        plan_code=plan_code,
    )
    if fulfillment.get("status") == "fulfilled":
        return fulfillment

    user = db.get_user_by_id(user_id)
    if not user:
        raise RuntimeError("Checkout user could not be found.")
    stripe_customer = session.get("customer")
    stripe_customer_id = stripe_customer.get("id") if isinstance(stripe_customer, dict) else stripe_customer or ""
    stripe_subscription = session.get("subscription")
    stripe_subscription_id = stripe_subscription.get("id") if isinstance(stripe_subscription, dict) else stripe_subscription or ""
    if stripe_customer_id and not user.get("stripe_customer_id"):
        db.update_user(user_id, stripe_customer_id=stripe_customer_id)

    if plan_code == "credit_pack":
        db.add_credits(user_id, CREDIT_PACK_SIZE, "credit_pack", session_id)
    elif plan_code in {"hosted_monthly", "hosted_yearly"}:
        db.create_subscription(user_id, stripe_subscription_id, metadata.get("price_id", ""), plan_code)
        if site_id:
            db.update_site(site_id, hosting_active=1)
    elif plan_code == "oneoff_unlock":
        if site_id:
            db.update_site(site_id, oneoff_unlocked=1)
    else:
        db.fail_checkout_fulfillment(session_id, status="unknown_plan")
        raise RuntimeError("Unknown checkout plan.")

    if offer_token:
        db.mark_outreach_offer_claimed(offer_token)

    redirect_path = f"/offer/{offer_token}" if offer_token else (f"/app?site={site_id}" if site_id else "/dashboard")
    email_sent, login_url = issue_login_link(user["email"], redirect_path, handler=handler)
    db.complete_checkout_fulfillment(
        session_id,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
        login_url=login_url,
        email_sent=email_sent,
        status="fulfilled",
    )
    result = db.get_checkout_fulfillment(session_id) or {}
    result["redirect_path"] = redirect_path
    result["login_url"] = login_url
    result["email_sent"] = bool(email_sent)
    result["site"] = site_payload(db.get_site(site_id), user) if site_id else None
    result["offer"] = db.get_outreach_offer_by_token(offer_token) if offer_token else None
    return result


def parse_event_payload(handler) -> dict:
    try:
        return json_body(handler)
    except Exception:
        return {}


class SaasHandler(BaseHTTPRequestHandler):
    server_version = "WebRedesignSaaS/0.2"

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _send_file(self, path: Path, content_type: str = ""):
        if not path.exists() or not path.is_file():
            send_error(self, "File not found", 404)
            return
        mime = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".zip": "application/zip",
        }
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or mime.get(path.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_spa(self, request_path: str):
        cleaned = request_path.lstrip("/")
        static_file = FRONTEND_DIR / cleaned
        if cleaned and static_file.exists() and static_file.is_file():
            self._send_file(static_file)
            return
        self._send_file(FRONTEND_DIR / "index.html")

    def _proxy_preview(self):
        target = f"{RUNNER_BASE_URL}{self.path}"
        try:
            req = urllib.request.Request(target, headers=dict(self.headers))
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read()
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in {"transfer-encoding", "content-encoding", "content-length"}:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except Exception:
            send_error(self, "Preview unavailable", 502)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        if not path.startswith("/api/"):
            if path.startswith("/preview/"):
                self._proxy_preview()
                return
            self._serve_spa(path)
            return

        try:
            user = require_auth(self)

            if path == "/api/health":
                send_json(self, {"status": "ok", "version": "0.2"})
                return

            if path == "/api/pricing":
                send_json(self, price_catalog())
                return

            if path == "/api/auth/verify":
                token = params.get("token", [""])[0]
                verified_user, redirect_path = db.verify_login_token(token)
                if not verified_user:
                    send_error(self, "Invalid or expired token", 401)
                    return
                session_token = db.create_session(verified_user["id"])
                send_json(
                    self,
                    {
                        "token": session_token,
                        "user": verified_user,
                        "redirect_path": redirect_path or "/dashboard",
                    },
                )
                return

            if path == "/api/me":
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                send_json(
                    self,
                    {
                        "user": user,
                        "credits": db.get_credit_balance(user["id"]),
                        "subscription": db.get_user_subscription(user["id"]),
                    },
                )
                return

            if path == "/api/sites":
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                sites = [site_payload(update_site_from_job_state(site), user) for site in db.get_user_sites(user["id"])]
                send_json(self, {"sites": sites})
                return

            if path.startswith("/api/sites/"):
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                parts = path.split("/")
                site_id = int(parts[3])
                site = db.get_site(site_id)
                if not site or site["user_id"] != user["id"]:
                    send_error(self, "Site not found", 404)
                    return
                site = update_site_from_job_state(site)
                if len(parts) == 4:
                    send_json(self, {"site": site_payload(site, user)})
                    return
                if len(parts) >= 5 and parts[4] == "export":
                    if not site.get("oneoff_unlocked"):
                        send_error(self, "Export requires the one-off purchase.", 402, code="oneoff_required")
                        return
                    job_dir = JOBS_DIR / (site.get("current_job_id") or "")
                    dist = job_dir / "dist"
                    if not dist.exists():
                        send_error(self, "No generated files found for this site.", 404)
                        return
                    export_path = EXPORTS_DIR / f"site-{site_id}.zip"
                    shutil.make_archive(str(export_path.with_suffix("")), "zip", dist)
                    send_json(self, {"download_url": f"/api/exports/{export_path.name}"})
                    return
                if len(parts) >= 5 and parts[4] == "domains":
                    send_json(self, {"domains": db.get_site_domains(site_id)})
                    return

            if path.startswith("/api/exports/"):
                filename = path.split("/")[-1]
                self._send_file(EXPORTS_DIR / filename)
                return

            if path.startswith("/api/screenshots/"):
                filename = path.split("/")[-1]
                self._send_file(SCREENSHOTS_DIR / filename)
                return

            if path.startswith("/api/jobs/"):
                job_id = path.split("/")[3]
                state_path = JOBS_DIR / job_id / "state.json"
                if not state_path.exists():
                    send_error(self, "Job not found", 404)
                    return
                state = json.loads(state_path.read_text())
                site = None
                if user:
                    for candidate in db.get_user_sites(user["id"]):
                        if candidate.get("current_job_id") == job_id:
                            site = update_site_from_job_state(candidate)
                            break
                if site:
                    state["site"] = site_payload(site, user)
                send_json(self, state)
                return

            if path == "/api/dns/check":
                domain = params.get("domain", [""])[0]
                if not domain:
                    send_error(self, "domain required")
                    return
                current_host = urlparse(PUBLIC_BASE_URL).hostname or ""
                expected_ip = dig_record(current_host, "A") or ""
                send_json(self, dns_check(domain, expected_ip=expected_ip))
                return

            if path.startswith("/api/offers/"):
                token = path.split("/")[3]
                offer = db.get_outreach_offer_by_token(token)
                if not offer:
                    send_error(self, "Offer not found", 404)
                    return
                db.mark_outreach_offer_opened(token)
                site = db.get_site(offer["site_id"])
                site = update_site_from_job_state(site) if site else None
                if site:
                    queue_preview_capture(site)
                offer_payload = dict(offer)
                offer_payload["preview_url"] = site.get("preview_url") if site else preview_url_for_public(offer.get("preview_url", ""), self)
                send_json(
                    self,
                    {
                        "offer": offer_payload,
                        "site": site_payload(site) if site else None,
                        "pricing": price_catalog(),
                    },
                )
                return

            send_error(self, "Not found", 404)
        except Exception as exc:
            traceback.print_exc()
            send_error(self, str(exc), 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        try:
            body = json_body(self)
            user = require_auth(self)

            if path == "/api/auth/login":
                email = params.get("email", [""])[0] or body.get("email", "")
                redirect_path = body.get("redirect_path", "/dashboard")
                if "@" not in email:
                    send_error(self, "Valid email required")
                    return
                sent, login_url = issue_login_link(email, redirect_path)
                send_json(
                    self,
                    {
                        "sent": sent,
                        "message": "Check your email for the sign-in link." if sent else "Email sending disabled; use the dev link.",
                        "login_url": None if sent else login_url,
                    },
                )
                return

            if path == "/api/auth/logout":
                auth = self.headers.get("Authorization", "")
                if auth.startswith("Bearer "):
                    db.delete_session(auth[7:])
                send_json(self, {"ok": True})
                return

            if path == "/api/free-claims":
                website_url = body.get("website_url", "").strip()
                email = body.get("email", "").strip().lower()
                company_name = body.get("company_name", "").strip()
                if not website_url or "@" not in email:
                    send_error(self, "website_url and email are required")
                    return
                normalized_domain = db.normalize_domain(website_url)
                client_ip = get_client_ip(self)
                if db.has_free_claim_for_domain(normalized_domain):
                    send_error(
                        self,
                        "A free redesign has already been created for this website.",
                        409,
                        code="domain_already_claimed",
                    )
                    return
                if db.has_free_claim_for_ip(client_ip):
                    send_error(
                        self,
                        "This free redesign offer has already been used from your connection.",
                        409,
                        code="ip_already_claimed",
                    )
                    return
                owner = db.get_or_create_user(email, company_name)
                site = db.get_user_site_by_domain(owner["id"], normalized_domain)
                if not site:
                    site = create_site_for_user(owner["id"], website_url, company_name or normalized_domain, normalized_domain)
                claim = db.create_free_claim(owner["id"], site["id"], normalized_domain, client_ip, "homepage")
                db.update_site(site["id"], free_preview_used=1, status="rendering")
                result = submit_runner_job(site, prompt="", industry="small-business", design_goal="Make this business look more trustworthy and easier to buy from.")
                sent, login_url = issue_login_link(owner["email"], f"/app?site={site['id']}", handler=self)
                send_json(
                    self,
                    {
                        "claim": claim,
                        "site": site_payload(db.get_site(site["id"]), owner),
                        "job_id": result.get("job_id"),
                        "login_url": None if sent else login_url,
                        "message": "Your free redesign is in progress. Check your email for your private review link.",
                    },
                    202,
                )
                return

            if path == "/api/sites":
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                source_url = body.get("source_url", "").strip()
                if not source_url:
                    send_error(self, "source_url required")
                    return
                normalized_domain = db.normalize_domain(source_url)
                existing = db.get_user_site_by_domain(user["id"], normalized_domain)
                if existing:
                    send_json(self, {"site": site_payload(existing, user)})
                    return
                site = create_site_for_user(
                    user["id"],
                    source_url,
                    body.get("title", "").strip() or normalized_domain,
                    normalized_domain,
                )
                send_json(self, {"site": site_payload(site, user)}, 201)
                return

            if path == "/api/jobs":
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                site_id = int(body.get("site_id", 0) or 0)
                site = db.get_site(site_id)
                if not site or site["user_id"] != user["id"]:
                    send_error(self, "Site not found", 404)
                    return
                balance = db.get_credit_balance(user["id"])
                if balance["credits"] <= 0:
                    send_error(self, "Buy credits to keep redesigning this site.", 402, code="credits_required")
                    return
                if not db.deduct_credit(user["id"]):
                    send_error(self, "No credits available.", 402, code="credits_required")
                    return
                try:
                    result = submit_runner_job(
                        site,
                        prompt=body.get("prompt", "").strip(),
                        industry=body.get("industry", "small-business"),
                        design_goal=body.get("design_goal", "Make this business easier to trust and easier to contact."),
                    )
                except Exception as exc:
                    db.refund_credit(user["id"])
                    send_error(self, f"Runner error: {exc}", 500)
                    return
                send_json(self, result, 202)
                return

            if path == "/api/offers":
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                website_url = body.get("website_url", "").strip()
                contact_email = body.get("email", "").strip().lower()
                company_name = body.get("company_name", "").strip()
                headline = body.get("headline", "").strip()
                notes = body.get("notes", "").strip()
                if not website_url or "@" not in contact_email or not company_name:
                    send_error(self, "website_url, email, and company_name are required")
                    return
                normalized_domain = db.normalize_domain(website_url)
                lead_user = db.get_or_create_user(contact_email, company_name)
                site = db.get_user_site_by_domain(lead_user["id"], normalized_domain)
                if not site:
                    site = create_site_for_user(lead_user["id"], website_url, company_name, normalized_domain)
                if not db.has_free_claim_for_domain(normalized_domain):
                    db.create_free_claim(lead_user["id"], site["id"], normalized_domain, f"outreach:{normalized_domain}", "outreach")
                    db.update_site(site["id"], free_preview_used=1, status="rendering")
                    submit_runner_job(
                        site,
                        prompt=notes,
                        industry="small-business",
                        design_goal=f"Create a persuasive, more modern homepage for {company_name}.",
                    )
                existing_offer = db.get_outreach_offer_by_site(site["id"])
                if existing_offer:
                    offer = existing_offer
                else:
                    offer = db.create_outreach_offer(
                        lead_user["id"],
                        site["id"],
                        company_name,
                        contact_email,
                        normalized_domain,
                        headline=headline or f"{company_name}, here is your redesigned website.",
                        notes=notes,
                        preview_url=preview_url_for_public(site.get("preview_url") or "", self),
                    )
                send_json(
                    self,
                    {
                        "offer": offer,
                        "offer_url": f"{resolve_public_base(self)}/offer/{offer['token']}",
                        "site": site_payload(site),
                    },
                    201,
                )
                return

            if path == "/api/checkout":
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                plan_code = body.get("plan_code", "")
                site_id = int(body.get("site_id", 0) or 0)
                pricing = price_catalog()
                price = pricing.get(plan_code)
                if not price or not price.get("price_id"):
                    send_error(self, "Unknown plan", 400)
                    return
                mode = "subscription" if plan_code in {"hosted_monthly", "hosted_yearly"} else "payment"
                metadata = {"user_id": user["id"], "plan_code": plan_code, "price_id": price["price_id"]}
                if site_id:
                    metadata["site_id"] = site_id
                public_base = resolve_public_base(self)
                session = create_stripe_checkout(
                    price_id=price["price_id"],
                    success_url=f"{public_base}/billing?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
                    cancel_url=f"{public_base}/billing?checkout=cancel",
                    customer_email=user["email"],
                    metadata=metadata,
                    mode=mode,
                )
                if not session or not session.get("url"):
                    send_error(self, "Failed to create checkout session", 500)
                    return
                send_json(self, {"checkout_url": session["url"]})
                return

            if path.startswith("/api/offers/") and path.endswith("/checkout"):
                token = path.split("/")[3]
                offer = db.get_outreach_offer_by_token(token)
                if not offer:
                    send_error(self, "Offer not found", 404)
                    return
                plan_code = body.get("plan_code", "")
                pricing = price_catalog()
                price = pricing.get(plan_code)
                if not price or not price.get("price_id"):
                    send_error(self, "Unknown plan", 400)
                    return
                mode = "subscription" if plan_code in {"hosted_monthly", "hosted_yearly"} else "payment"
                email = body.get("email", "").strip().lower() or offer["contact_email"]
                metadata = {
                    "user_id": offer["user_id"],
                    "site_id": offer["site_id"],
                    "offer_token": offer["token"],
                    "plan_code": plan_code,
                    "price_id": price["price_id"],
                }
                public_base = resolve_public_base(self)
                session = create_stripe_checkout(
                    price_id=price["price_id"],
                    success_url=f"{public_base}/offer/{offer['token']}?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
                    cancel_url=f"{public_base}/offer/{offer['token']}?checkout=cancel",
                    customer_email=email,
                    metadata=metadata,
                    mode=mode,
                )
                if not session or not session.get("url"):
                    send_error(self, "Failed to create checkout session", 500)
                    return
                send_json(self, {"checkout_url": session["url"]})
                return

            if path == "/api/checkout/confirm":
                session_id = body.get("session_id", "").strip()
                offer_token = body.get("offer_token", "").strip()
                if not session_id:
                    send_error(self, "session_id required")
                    return
                result = finalize_checkout_session(
                    session_id,
                    handler=self,
                    expected_user_id=user["id"] if user else 0,
                    expected_offer_token=offer_token,
                )
                send_json(self, result)
                return

            if path == "/api/domains":
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                site_id = int(body.get("site_id", 0) or 0)
                site = db.get_site(site_id)
                if not site or site["user_id"] != user["id"]:
                    send_error(self, "Site not found", 404)
                    return
                if not db.get_user_subscription(user["id"]):
                    send_error(self, "Custom domains require the hosted subscription.", 402, code="hosting_required")
                    return
                domain = body.get("domain", "").strip().lower()
                if not domain:
                    send_error(self, "domain required")
                    return
                created = db.create_domain(site_id, domain)
                if not created:
                    send_error(self, "Domain already registered")
                    return
                send_json(self, {"domain": created}, 201)
                return

            if path == "/api/domains/verify":
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                domain_id = int(body.get("domain_id", 0) or 0)
                site_id = int(body.get("site_id", 0) or 0)
                domain = body.get("domain", "").strip().lower()
                site = db.get_site(site_id)
                if not site or site["user_id"] != user["id"]:
                    send_error(self, "Site not found", 404)
                    return
                current_host = urlparse(PUBLIC_BASE_URL).hostname or ""
                expected_ip = dig_record(current_host, "A") or ""
                check = dns_check(domain, expected_ip=expected_ip)
                if check["points_to_me"]:
                    db.update_domain(domain_id, dns_status="verified", verified_at=now_iso())
                    job_dir = JOBS_DIR / (site.get("current_job_id") or "")
                    dist = job_dir / "dist"
                    if dist.exists():
                        target_dir = SITES_DIR / domain
                        shutil.copytree(dist, target_dir, dirs_exist_ok=True)
                        if caddy_add_domain(domain, str(target_dir)):
                            db.update_domain(domain_id, ssl_status="provisioning", caddy_route_added=1)
                send_json(self, check)
                return

            if path == "/api/stripe/webhook":
                event = parse_event_payload(self)
                event_type = event.get("type", "")
                obj = event.get("data", {}).get("object", {})
                metadata = obj.get("metadata", {}) or {}
                if event_type == "checkout.session.completed" and obj.get("id"):
                    try:
                        finalize_checkout_session(obj.get("id"), expected_user_id=int(metadata.get("user_id", 0) or 0))
                    except Exception as exc:
                        print(f"[stripe] webhook fulfillment failed: {exc}", flush=True)
                send_json(self, {"received": True})
                return

            send_error(self, "Not found", 404)
        except Exception as exc:
            traceback.print_exc()
            send_error(self, str(exc), 500)


def main():
    db.init_db()
    server = ThreadingHTTPServer((HOST, PORT), SaasHandler)
    print(f"[saas] listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

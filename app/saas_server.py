#!/usr/bin/env python3
"""
WebRedesign SaaS — API server + frontend.

Serves:
  - Frontend SPA at /
  - SaaS API at /api/*
  - User auth, credit mgmt, billing, export, domains

Designed to sit behind Caddy alongside the runner.
Caddy routes:
  /preview/*  → runner (port 4321)
  /api/*      → saas   (port 4322)
  /*          → saas   (port 4322)  — SPA frontend
"""
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote

# Local schema module
import saas_schema as db

# ── Config ──────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
HOST = os.environ.get("SAAS_HOST", "0.0.0.0")
PORT = int(os.environ.get("SAAS_PORT", "4322"))
ROOT = Path(os.environ.get("WEBSITE_REDESIGN_ROOT", "/data"))
PUBLIC_BASE_URL = os.environ.get("SAAS_PUBLIC_URL", "http://localhost:4322")
RUNNER_BASE_URL = os.environ.get("RUNNER_BASE_URL", "http://localhost:4321")
STRIPE_PUBLIC_KEY = os.environ.get("STRIPE_PUBLIC_KEY", "")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
CREDIT_PRICE_ID = os.environ.get("STRIPE_CREDIT_PRICE_ID", "")
PRO_PRICE_ID = os.environ.get("STRIPE_PRO_PRICE_ID", "")
EXPORT_PRICE_ID = os.environ.get("STRIPE_EXPORT_PRICE_ID", "")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("SAAS_FROM_EMAIL", "noreply@webredesign.ai")
CADDY_API_URL = os.environ.get("CADDY_API_URL", "http://caddy:2019")
SITES_DIR = ROOT / "sites"
EXPORTS_DIR = ROOT / "exports"
JOBS_DIR = ROOT / "jobs"
PREVIEWS_DIR = ROOT / "previews"

for d in [SITES_DIR, EXPORTS_DIR, JOBS_DIR, PREVIEWS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ── Auth helpers ────────────────────────────────────────────────────

def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


SESSIONS: dict[str, dict] = {}  # token → user dict (in-memory, simple)


def require_auth(handler) -> dict | None:
    """Check Authorization header. Returns user dict or None."""
    auth = handler.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    user = SESSIONS.get(token)
    if not user:
        return None
    return user


def json_body(handler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def send_json(handler, payload: dict, status: int = 200):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def send_error(handler, message: str, status: int = 400):
    send_json(handler, {"error": message}, status)


def parse_bool(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    return lowered in {"1", "true", "yes", "y", "on"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── DNS helpers ─────────────────────────────────────────────────────

def dig_record(domain: str, rtype: str = "A") -> str | None:
    """Run dig and return the first result value, or None."""
    try:
        result = subprocess.run(
            ["dig", "+short", "-t", rtype, domain],
            capture_output=True, text=True, timeout=15,
        )
        val = result.stdout.strip()
        return val if val else None
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
    """Check DNS status."""
    records = dig_all(domain)
    a_record = records.get("a")
    return {
        "domain": domain,
        "a_record": a_record,
        "points_to_me": a_record == expected_ip if expected_ip else bool(a_record),
        "mx_present": bool(records.get("mx")),
        "warnings": (
            ["Email (MX) records detected — they won't be affected"]
            if records.get("mx") else []
        ),
        "records": records,
    }


# ── Caddy API helpers ───────────────────────────────────────────────

def caddy_add_domain(domain: str, site_path: str) -> bool:
    """Add a domain route to Caddy via admin API."""
    try:
        import urllib.request
        route = {
            "@id": f"domain-{domain}",
            "match": [{"host": [domain]}],
            "handle": [{
                "handler": "subroute",
                "routes": [{
                    "group": "websites",
                    "handle": [{
                        "handler": "file_server",
                        "root": site_path
                    }]
                }]
            }],
            "terminal": True,
        }
        req = urllib.request.Request(
            f"{CADDY_API_URL}/config/apps/http/servers/srv0/routes/",
            data=json.dumps(route).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201)
    except Exception:
        return False


def caddy_remove_domain(domain: str) -> bool:
    """Remove a domain route from Caddy."""
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{CADDY_API_URL}/id/domain-{domain}",
            method="DELETE",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except Exception:
        return False


# ── Stripe helpers ──────────────────────────────────────────────────

def create_stripe_checkout(price_id: str, success_url: str, cancel_url: str,
                           customer_email: str = "", metadata: dict = None) -> dict | None:
    """Create a Stripe Checkout session via the Stripe MCP or direct API."""
    metadata = metadata or {}
    try:
        import urllib.request
        payload = json.dumps({
            "mode": "subscription" if "pro" in price_id else "payment",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "customer_email": customer_email or None,
            "metadata": metadata,
            "allow_promotion_codes": True,
        }).encode()
        req = urllib.request.Request(
            "https://api.stripe.com/v1/checkout/sessions",
            data=payload,
            headers={
                "Authorization": f"Bearer {STRIPE_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        print(f"[stripe] Checkout error: {exc}")
        return None


# ── Email helpers ───────────────────────────────────────────────────

def send_email(to: str, subject: str, body_html: str) -> bool:
    """Send an email via SendGrid API."""
    if not SENDGRID_API_KEY:
        print(f"[email] Would send to {to}: {subject}")
        return True
    try:
        import urllib.request
        payload = json.dumps({
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": FROM_EMAIL},
            "subject": subject,
            "content": [{"type": "text/html", "value": body_html}],
        }).encode()
        req = urllib.request.Request(
            "https://api.sendgrid.com/v3/mail/send",
            data=payload,
            headers={
                "Authorization": f"Bearer {SENDGRID_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30):
            return True
    except Exception as exc:
        print(f"[email] Error: {exc}")
        return False


# ── Request handler ────────────────────────────────────────────────

class SaasHandler(BaseHTTPRequestHandler):
    server_version = "WebRedesignSaaS/0.1"

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _send_file(self, file_path: Path, content_type: str = ""):
        if not file_path.exists() or not file_path.is_file():
            send_error(self, "File not found", 404)
            return
        mime_map = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".ico": "image/x-icon",
            ".woff2": "font/woff2",
            ".woff": "font/woff",
            ".ttf": "font/ttf",
            ".zip": "application/zip",
            ".md": "text/markdown",
        }
        ct = content_type or mime_map.get(file_path.suffix.lower(), "application/octet-stream")
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_spa(self, subpath: str = ""):
        """Serve the SPA — index.html for all routes, static files for assets."""
        if not subpath or subpath == "/":
            index = FRONTEND_DIR / "index.html"
            if index.exists():
                self._send_file(index)
                return
        # Try static file
        safe = subpath.lstrip("/")
        file_path = FRONTEND_DIR / safe
        if file_path.exists() and file_path.is_file():
            self._send_file(file_path)
            return
        # Fallback to index.html (SPA routing)
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            self._send_file(index)
        else:
            send_error(self, "Frontend not built", 404)

    # ── Route dispatcher ────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        # ── Frontend SPA ─────────────────────────────────────────────
        if path.startswith("/api/"):
            pass  # handled below
        elif path.startswith("/static/"):
            self._serve_spa(path)
            return
        elif path.startswith("/preview/"):
            # Proxy to runner
            self._proxy_to_runner()
            return
        else:
            self._serve_spa(path)
            return

        # ── API routes ───────────────────────────────────────────────
        try:
            if path == "/api/health":
                send_json(self, {
                    "status": "ok",
                    "version": "0.1",
                    "stripe_configured": bool(STRIPE_SECRET_KEY),
                })

            elif path == "/api/auth/login":
                email = params.get("email", [""])[0]
                if not email or "@" not in email:
                    send_error(self, "Valid email required")
                    return
                token = db.create_login_token(email)
                login_url = f"{PUBLIC_BASE_URL}/login?token={token}"
                body = f"""
                <h2>Login to WebRedesign</h2>
                <p>Click the link below to sign in:</p>
                <p><a href="{login_url}">{login_url}</a></p>
                <p>This link expires in 1 hour.</p>
                """
                sent = send_email(email, "Your WebRedesign login link", body)
                send_json(self, {
                    "sent": sent,
                    "message": "Check your email for the login link" if sent else "Email sending disabled (dev mode)",
                    "login_url": login_url if not SENDGRID_API_KEY else None,
                })

            elif path == "/api/auth/verify":
                token = params.get("token", [""])[0]
                if not token:
                    send_error(self, "Token required")
                    return
                user = db.verify_login_token(token)
                if not user:
                    send_error(self, "Invalid or expired token", 401)
                    return
                session_token = generate_session_token()
                SESSIONS[session_token] = user
                send_json(self, {
                    "token": session_token,
                    "user": {k: v for k, v in user.items() if k != "stripe_customer_id"},
                })

            elif path == "/api/me":
                user = require_auth(self)
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                balance = db.get_credit_balance(user["id"])
                sub = db.get_user_subscription(user["id"])
                send_json(self, {
                    "user": {k: v for k, v in user.items() if k != "stripe_customer_id"},
                    "credits": balance,
                    "subscription": sub,
                })

            elif path == "/api/sites":
                user = require_auth(self)
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                sites = db.get_user_sites(user["id"])
                send_json(self, {"sites": sites})

            elif path.startswith("/api/sites/"):
                user = require_auth(self)
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                parts = path.split("/")
                if len(parts) >= 4 and parts[3] == "export":
                    site_id = int(parts[2])
                    site = db.get_site(site_id)
                    if not site or site["user_id"] != user["id"]:
                        send_error(self, "Site not found", 404)
                        return
                    if user["tier"] != "pro" and user["credits"] < 1:
                        send_error(self, "Export requires a credit ($199 purchase)", 402)
                        return
                    job_id = site.get("current_job_id")
                    if not job_id:
                        send_error(self, "No redesign job for this site", 400)
                        return
                    job_dir = JOBS_DIR / job_id
                    dist = job_dir / "dist"
                    if not dist.exists():
                        send_error(self, "No generated files found", 404)
                        return
                    export_path = EXPORTS_DIR / f"site-{site_id}.zip"
                    shutil.make_archive(str(export_path.with_suffix("")), "zip", dist)
                    download_url = f"/api/exports/site-{site_id}.zip"
                    send_json(self, {"download_url": download_url, "path": str(export_path)})

                elif len(parts) >= 4 and parts[3] == "domain":
                    site_id = int(parts[2])
                    site = db.get_site(site_id)
                    if not site or site["user_id"] != user["id"]:
                        send_error(self, "Site not found", 404)
                        return
                    domains = db.get_site_domains(site_id)
                    send_json(self, {"domains": domains})

                else:
                    site_id = int(parts[2])
                    site = db.get_site(site_id)
                    if not site or site["user_id"] != user["id"]:
                        send_error(self, "Site not found", 404)
                        return
                    send_json(self, {"site": site})

            elif path == "/api/credits":
                user = require_auth(self)
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                balance = db.get_credit_balance(user["id"])
                history = db.get_credit_history(user["id"])
                send_json(self, {"balance": balance, "history": history})

            elif path == "/api/checkout":
                user = require_auth(self)
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                price_id = params.get("price_id", [""])[0]
                if not price_id:
                    send_error(self, "price_id required")
                    return
                success_url = f"{PUBLIC_BASE_URL}/app?checkout=success"
                cancel_url = f"{PUBLIC_BASE_URL}/app?checkout=cancel"
                session = create_stripe_checkout(
                    price_id=price_id,
                    success_url=success_url,
                    cancel_url=cancel_url,
                    customer_email=user.get("email"),
                    metadata={"user_id": str(user["id"]), "price_id": price_id},
                )
                if session and session.get("url"):
                    send_json(self, {"checkout_url": session["url"]})
                else:
                    send_error(self, "Failed to create checkout session", 500)

            elif path == "/api/dns/check":
                domain = params.get("domain", [""])[0]
                if not domain:
                    send_error(self, "domain required")
                    return
                result = dns_check(domain)
                send_json(self, result)

            elif path.startswith("/api/exports/"):
                filename = path.split("/")[-1]
                export_file = EXPORTS_DIR / filename
                if not export_file.exists():
                    send_error(self, "Export not found", 404)
                    return
                self._send_file(export_file)

            elif path == "/api/pricing":
                send_json(self, {
                    "credit_pack": {
                        "price_id": CREDIT_PRICE_ID,
                        "credits": 5,
                        "price_cents": 900,
                        "label": "5 Credits — $9",
                    },
                    "pro_monthly": {
                        "price_id": PRO_PRICE_ID,
                        "price_cents": 1900,
                        "label": "Pro — $19/mo, unlimited credits + hosting",
                    },
                    "export": {
                        "price_id": EXPORT_PRICE_ID,
                        "price_cents": 19900,
                        "label": "Export — $199, full site ZIP",
                    },
                })

            elif path.startswith("/api/jobs/"):
                parts = path.split("/")
                job_id = parts[3]
                job_dir = JOBS_DIR / job_id
                state_file = job_dir / "state.json"
                if not state_file.exists():
                    send_error(self, "Job not found", 404)
                    return
                state = json.loads(state_file.read_text())
                send_json(self, state)

            else:
                send_error(self, "Not found", 404)

        except Exception as exc:
            send_error(self, str(exc), 500)
            traceback.print_exc()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        try:
            # ── Auth: create site (triggered from frontend) ────────
            if path == "/api/sites":
                user = require_auth(self)
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                data = json_body(self)
                slug = data.get("slug", uuid.uuid4().hex[:10])
                source_url = data.get("source_url", "")
                title = data.get("title", "")
                if not source_url:
                    send_error(self, "source_url required")
                    return
                site = db.create_site(user["id"], slug, source_url, title)
                if not site:
                    send_error(self, "Site slug already exists")
                    return
                send_json(self, {"site": site}, 201)

            # ── Auth: submit redesign job ───────────────────────────
            elif path == "/api/jobs":
                user = require_auth(self)
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                data = json_body(self)
                site_id = data.get("site_id")
                if not site_id:
                    send_error(self, "site_id required")
                    return
                site = db.get_site(site_id)
                if not site or site["user_id"] != user["id"]:
                    send_error(self, "Site not found", 404)
                    return

                # Check credits
                balance = db.get_credit_balance(user["id"])
                if not balance["unlimited"] and balance["credits"] <= 0:
                    send_error(self, "Insufficient credits. Purchase more credits or subscribe to Pro.", 402)
                    return

                # Deduct credit (skip for Pro)
                if not balance["unlimited"]:
                    db.deduct_credit(user["id"])

                # Forward to runner
                payload = {
                    "website_url": site["source_url"],
                    "client_slug": site["slug"],
                    "extra_instructions": data.get("prompt", ""),
                    "design_references": data.get("references", []),
                    "generator_profile": data.get("profile", "balanced"),
                    "image_strategy": data.get("image_strategy", "hybrid"),
                    "design_goal": data.get("design_goal", ""),
                    "notify_email": "",
                    "industry": data.get("industry", "general"),
                    "impeccable_critique": True,
                    "impeccable_autofix": True,
                    "reuse_source_images": True,
                    "allow_external_images": True,
                }

                # Call runner
                import urllib.request
                runner_payload = json.dumps(payload).encode()
                req = urllib.request.Request(
                    f"{RUNNER_BASE_URL}/jobs",
                    data=runner_payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        result = json.loads(resp.read().decode())
                except Exception as exc:
                    send_error(self, f"Runner error: {exc}", 500)
                    return

                # Update site with job ID
                if result.get("job_id"):
                    db.update_site(site_id, current_job_id=result["job_id"])

                send_json(self, result, 202)

            # ── Auth: activate domain ───────────────────────────────
            elif path == "/api/domains":
                user = require_auth(self)
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                data = json_body(self)
                site_id = data.get("site_id")
                domain = data.get("domain", "").strip().lower()
                if not site_id or not domain:
                    send_error(self, "site_id and domain required")
                    return
                site = db.get_site(site_id)
                if not site or site["user_id"] != user["id"]:
                    send_error(self, "Site not found", 404)
                    return
                dom = db.create_domain(site_id, domain)
                if not dom:
                    send_error(self, "Domain already registered")
                    return
                send_json(self, {"domain": dom}, 201)

            # ── Auth: verify DNS ────────────────────────────────────
            elif path == "/api/domains/verify":
                user = require_auth(self)
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                data = json_body(self)
                domain_id = data.get("domain_id")
                if not domain_id:
                    send_error(self, "domain_id required")
                    return
                # Get our server IP from dig
                our_ip = dig_record(PUBLIC_BASE_URL.split("//")[1].split(":")[0] if "//" in PUBLIC_BASE_URL else PUBLIC_BASE_URL, "A")
                check = dns_check(data.get("domain", ""), our_ip)
                if check.get("points_to_me"):
                    db.update_domain(domain_id, dns_status="verified", verified_at=now_iso())
                    # Deploy the site
                    site_id = data.get("site_id")
                    if site_id:
                        site = db.get_site(site_id)
                        if site and site.get("current_job_id"):
                            job_dir = JOBS_DIR / site["current_job_id"]
                            dist = job_dir / "dist"
                            if dist.exists():
                                domain_path = SITES_DIR / data.get("domain", "")
                                shutil.copytree(dist, domain_path, dirs_exist_ok=True)
                                caddy_add_domain(data.get("domain", ""), str(domain_path))
                                db.update_domain(domain_id, ssl_status="provisioning", caddy_route_added=1)
                    check["deployed"] = True
                send_json(self, check)

            # ── Create checkout session ─────────────────────────────
            elif path == "/api/checkout":
                user = require_auth(self)
                if not user:
                    send_error(self, "Unauthorized", 401)
                    return
                data = json_body(self)
                price_id = data.get("price_id", "")
                if not price_id:
                    send_error(self, "price_id required")
                    return
                success_url = f"{PUBLIC_BASE_URL}/app?checkout=success"
                cancel_url = f"{PUBLIC_BASE_URL}/app?checkout=cancel"
                session = create_stripe_checkout(
                    price_id=price_id,
                    success_url=success_url,
                    cancel_url=cancel_url,
                    customer_email=user.get("email"),
                    metadata={"user_id": str(user["id"]), "price_id": price_id},
                )
                if session and session.get("url"):
                    send_json(self, {"checkout_url": session["url"]})
                else:
                    send_error(self, "Failed to create checkout session", 500)

            # ── Stripe webhook ──────────────────────────────────────
            elif path == "/api/stripe/webhook":
                data = json_body(self)
                event_type = data.get("type", "")
                sess = data.get("data", {}).get("object", {})
                metadata = sess.get("metadata", {})
                user_id = int(metadata.get("user_id", 0))
                price_id = sess.get("metadata", {}).get("price_id", "")

                if event_type == "checkout.session.completed" and user_id:
                    if CREDIT_PRICE_ID and price_id == CREDIT_PRICE_ID:
                        db.add_credits(user_id, 5, "purchase", sess.get("id", ""))
                    elif PRO_PRICE_ID and price_id == PRO_PRICE_ID:
                        db.create_subscription(user_id, sess.get("subscription", ""), price_id)
                        db.set_tier(user_id, "pro")
                    elif EXPORT_PRICE_ID and price_id == EXPORT_PRICE_ID:
                        db.add_credits(user_id, 1, "export_purchase", sess.get("id", ""))
                        db.set_tier(user_id, "pro")
                send_json(self, {"received": True})

            else:
                send_error(self, "Not found", 404)

        except Exception as exc:
            send_error(self, str(exc), 500)
            traceback.print_exc()

    def _proxy_to_runner(self):
        """Proxy preview requests to the runner."""
        import urllib.request
        target = f"{RUNNER_BASE_URL}{self.path}"
        try:
            req = urllib.request.Request(target, headers=dict(self.headers))
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                self.send_response(resp.status)
                for key, val in resp.headers.items():
                    if key.lower() not in ("transfer-encoding", "content-encoding", "content-length"):
                        self.send_header(key, val)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except Exception:
            send_error(self, "Preview unavailable", 502)


# ── Server startup ──────────────────────────────────────────────────

def main():
    db.init_db()
    server = ThreadingHTTPServer((HOST, PORT), SaasHandler)
    print(f"[saas] WebRedesign SaaS on http://{HOST}:{PORT}", flush=True)
    print(f"[saas] Frontend: {FRONTEND_DIR}", flush=True)
    print(f"[saas] Runner: {RUNNER_BASE_URL}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

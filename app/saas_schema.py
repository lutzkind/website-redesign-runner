#!/usr/bin/env python3
"""
Persistent storage for the SaaS shell around the redesign runner.
"""

import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

DB_DIR = Path(os.environ.get("WEBSITE_REDESIGN_ROOT", "/data"))
DB_PATH = DB_DIR / "saas.db"

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    tier TEXT NOT NULL DEFAULT 'free',
    credits INTEGER NOT NULL DEFAULT 0,
    total_credits_purchased INTEGER NOT NULL DEFAULT 0,
    stripe_customer_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    token TEXT UNIQUE NOT NULL,
    redirect_path TEXT,
    used INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL,
    normalized_domain TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    current_job_id TEXT,
    preview_url TEXT,
    preview_image_url TEXT,
    preview_image_captured_at TEXT,
    subdomain TEXT,
    custom_domain TEXT,
    dns_verified INTEGER NOT NULL DEFAULT 0,
    hosting_active INTEGER NOT NULL DEFAULT 0,
    oneoff_unlocked INTEGER NOT NULL DEFAULT 0,
    free_preview_used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS credit_txns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    stripe_session_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stripe_subscription_id TEXT UNIQUE,
    stripe_price_id TEXT,
    plan_code TEXT NOT NULL DEFAULT 'hosted_monthly',
    status TEXT NOT NULL DEFAULT 'incomplete',
    current_period_end TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    domain TEXT UNIQUE NOT NULL,
    dns_status TEXT NOT NULL DEFAULT 'pending',
    ssl_status TEXT NOT NULL DEFAULT 'pending',
    verified_at TEXT,
    caddy_route_added INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS free_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    site_id INTEGER REFERENCES sites(id) ON DELETE SET NULL,
    normalized_domain TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'homepage',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    contact_email TEXT NOT NULL,
    normalized_domain TEXT NOT NULL,
    headline TEXT,
    notes TEXT,
    preview_url TEXT,
    status TEXT NOT NULL DEFAULT 'ready',
    opened_at TEXT,
    claimed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkout_fulfillments (
    session_id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    site_id INTEGER REFERENCES sites(id) ON DELETE SET NULL,
    offer_token TEXT,
    customer_email TEXT,
    plan_code TEXT NOT NULL,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    status TEXT NOT NULL DEFAULT 'processing',
    login_url TEXT,
    email_sent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

"""


def get_db() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_domain(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)
    host = (parsed.netloc or parsed.path).strip().lower()
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return text[:48] or secrets.token_hex(6)


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str):
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA_SQL)

    # Backfill older databases created before the rebuild.
    _add_column_if_missing(conn, "login_tokens", "redirect_path", "TEXT")
    _add_column_if_missing(conn, "sites", "normalized_domain", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "sites", "preview_url", "TEXT")
    _add_column_if_missing(conn, "sites", "preview_image_url", "TEXT")
    _add_column_if_missing(conn, "sites", "preview_image_captured_at", "TEXT")
    _add_column_if_missing(conn, "sites", "hosting_active", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "sites", "oneoff_unlocked", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "sites", "free_preview_used", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "subscriptions", "plan_code", "TEXT NOT NULL DEFAULT 'hosted_monthly'")
    rows = conn.execute("SELECT id, source_url, slug FROM sites").fetchall()
    for row in rows:
        domain = normalize_domain(row["source_url"])
        conn.execute(
            "UPDATE sites SET normalized_domain = COALESCE(NULLIF(normalized_domain, ''), ?) WHERE id = ?",
            (domain or row["slug"], row["id"]),
        )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_free_claims_domain ON free_claims(normalized_domain)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_free_claims_ip ON free_claims(ip_address)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sites_user ON sites(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sites_domain ON sites(normalized_domain)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_outreach_offer_site ON outreach_offers(site_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_checkout_fulfillments_user ON checkout_fulfillments(user_id)")
    conn.commit()
    conn.close()


def _row_or_none(row):
    return dict(row) if row else None


def create_user(email: str, name: str = "") -> dict | None:
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, name, tier, credits, created_at, updated_at) VALUES (?, ?, 'free', 0, ?, ?)",
            (email.strip().lower(), name.strip(), now_iso(), now_iso()),
        )
        conn.commit()
        return get_user_by_id(cur.lastrowid)
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_or_create_user(email: str, name: str = "") -> dict:
    existing = get_user_by_email(email)
    if existing:
        if name and not existing.get("name"):
            update_user(existing["id"], name=name)
            existing = get_user_by_id(existing["id"])
        return existing
    created = create_user(email, name)
    return created if created else get_user_by_email(email)


def update_user(user_id: int, **fields):
    if not fields:
        return
    sets = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values())
    conn = get_db()
    conn.execute(f"UPDATE users SET {sets}, updated_at = ? WHERE id = ?", (*values, now_iso(), user_id))
    conn.commit()
    conn.close()


def get_user_by_id(user_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return _row_or_none(row)


def get_user_by_email(email: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    conn.close()
    return _row_or_none(row)


def create_login_token(email: str, redirect_path: str | None = None) -> str:
    token = secrets.token_urlsafe(48)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_db()
    conn.execute(
        "INSERT INTO login_tokens (email, token, redirect_path, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
        (email.strip().lower(), token, redirect_path, expires_at, now_iso()),
    )
    conn.commit()
    conn.close()
    return token


def verify_login_token(token: str) -> tuple[dict | None, str | None]:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM login_tokens WHERE token = ? AND used = 0 AND expires_at > ?",
        (token, now_iso()),
    ).fetchone()
    if not row:
        conn.close()
        return None, None
    conn.execute("UPDATE login_tokens SET used = 1 WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    user = get_or_create_user(row["email"])
    return user, row["redirect_path"]


def create_session(user_id: int, days: int = 30) -> str:
    token = secrets.token_urlsafe(48)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_db()
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
        (token, user_id, expires_at, now_iso()),
    )
    conn.commit()
    conn.close()
    return token


def get_user_by_session(token: str) -> dict | None:
    if not token:
        return None
    conn = get_db()
    row = conn.execute(
        """
        SELECT users.* FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ? AND sessions.expires_at > ?
        """,
        (token, now_iso()),
    ).fetchone()
    conn.close()
    return _row_or_none(row)


def delete_session(token: str):
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def create_site(user_id: int, slug: str, source_url: str, title: str = "", normalized_domain: str | None = None) -> dict | None:
    conn = get_db()
    try:
        domain = normalized_domain or normalize_domain(source_url) or slug
        subdomain = f"{slug}.webredesign.ai"
        cur = conn.execute(
            """
            INSERT INTO sites (
                user_id, slug, title, source_url, normalized_domain, subdomain,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, slug, title, source_url, domain, subdomain, now_iso(), now_iso()),
        )
        conn.commit()
        return get_site(cur.lastrowid)
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_site(site_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
    conn.close()
    return _row_or_none(row)


def get_user_sites(user_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM sites WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_user_site_by_domain(user_id: int, normalized_domain: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM sites WHERE user_id = ? AND normalized_domain = ? ORDER BY updated_at DESC LIMIT 1",
        (user_id, normalized_domain),
    ).fetchone()
    conn.close()
    return _row_or_none(row)


def get_site_by_domain(normalized_domain: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM sites WHERE normalized_domain = ? ORDER BY updated_at DESC LIMIT 1",
        (normalized_domain,),
    ).fetchone()
    conn.close()
    return _row_or_none(row)


def update_site(site_id: int, **fields):
    if not fields:
        return
    sets = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values())
    conn = get_db()
    conn.execute(f"UPDATE sites SET {sets}, updated_at = ? WHERE id = ?", (*values, now_iso(), site_id))
    conn.commit()
    conn.close()


def create_domain(site_id: int, domain: str) -> dict | None:
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO domains (site_id, domain, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (site_id, domain, now_iso(), now_iso()),
        )
        conn.commit()
        return get_domain(cur.lastrowid)
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_domain(domain_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM domains WHERE id = ?", (domain_id,)).fetchone()
    conn.close()
    return _row_or_none(row)


def get_site_domains(site_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM domains WHERE site_id = ? ORDER BY created_at DESC", (site_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_domain(domain_id: int, **fields):
    if not fields:
        return
    sets = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values())
    conn = get_db()
    conn.execute(f"UPDATE domains SET {sets}, updated_at = ? WHERE id = ?", (*values, now_iso(), domain_id))
    conn.commit()
    conn.close()


def add_credits(user_id: int, amount: int, reason: str = "purchase", session_id: str = ""):
    conn = get_db()
    conn.execute(
        "UPDATE users SET credits = credits + ?, total_credits_purchased = total_credits_purchased + ?, updated_at = ? WHERE id = ?",
        (amount, max(amount, 0), now_iso(), user_id),
    )
    conn.execute(
        "INSERT INTO credit_txns (user_id, amount, reason, stripe_session_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, reason, session_id, now_iso()),
    )
    conn.commit()
    conn.close()


def deduct_credit(user_id: int) -> bool:
    conn = get_db()
    row = conn.execute("SELECT credits FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or row["credits"] <= 0:
        conn.close()
        return False
    conn.execute("UPDATE users SET credits = credits - 1, updated_at = ? WHERE id = ?", (now_iso(), user_id))
    conn.execute(
        "INSERT INTO credit_txns (user_id, amount, reason, created_at) VALUES (?, -1, 'redesign_run', ?)",
        (user_id, now_iso()),
    )
    conn.commit()
    conn.close()
    return True


def refund_credit(user_id: int, reason: str = "runner_failure"):
    add_credits(user_id, 1, reason)


def get_credit_balance(user_id: int) -> dict:
    conn = get_db()
    user = conn.execute("SELECT credits, tier FROM users WHERE id = ?", (user_id,)).fetchone()
    sub = conn.execute(
        "SELECT plan_code, status FROM subscriptions WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    conn.close()
    return {
        "credits": user["credits"] if user else 0,
        "tier": user["tier"] if user else "free",
        "hosted_active": bool(sub),
        "plan_code": sub["plan_code"] if sub else None,
    }


def get_credit_history(user_id: int, limit: int = 50) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM credit_txns WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def create_subscription(user_id: int, stripe_sub_id: str, stripe_price_id: str, plan_code: str) -> dict | None:
    conn = get_db()
    try:
        cur = conn.execute(
            """
            INSERT INTO subscriptions (
                user_id, stripe_subscription_id, stripe_price_id, plan_code,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            (user_id, stripe_sub_id, stripe_price_id, plan_code, now_iso(), now_iso()),
        )
        conn.execute("UPDATE users SET tier = 'subscriber', updated_at = ? WHERE id = ?", (now_iso(), user_id))
        conn.commit()
        return get_subscription(cur.lastrowid)
    except sqlite3.IntegrityError:
        row = conn.execute(
            """
            SELECT * FROM subscriptions
            WHERE user_id = ? AND stripe_subscription_id = ?
            LIMIT 1
            """,
            (user_id, stripe_sub_id),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE subscriptions SET stripe_price_id = ?, plan_code = ?, status = 'active', updated_at = ? WHERE id = ?",
                (stripe_price_id, plan_code, now_iso(), row["id"]),
            )
            conn.execute("UPDATE users SET tier = 'subscriber', updated_at = ? WHERE id = ?", (now_iso(), user_id))
            conn.commit()
            result = dict(row)
            result.update({"stripe_price_id": stripe_price_id, "plan_code": plan_code, "status": "active"})
            return result
        return None
    finally:
        conn.close()


def get_subscription(subscription_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
    conn.close()
    return _row_or_none(row)


def get_user_subscription(user_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    conn.close()
    return _row_or_none(row)


def cancel_subscription(user_id: int):
    conn = get_db()
    conn.execute(
        "UPDATE subscriptions SET status = 'canceled', updated_at = ? WHERE user_id = ? AND status = 'active'",
        (now_iso(), user_id),
    )
    conn.execute("UPDATE users SET tier = 'free', updated_at = ? WHERE id = ?", (now_iso(), user_id))
    conn.commit()
    conn.close()


def has_free_claim_for_domain(normalized_domain: str) -> bool:
    conn = get_db()
    row = conn.execute("SELECT 1 FROM free_claims WHERE normalized_domain = ? LIMIT 1", (normalized_domain,)).fetchone()
    conn.close()
    return bool(row)


def has_free_claim_for_ip(ip_address: str) -> bool:
    if not ip_address:
        return False
    conn = get_db()
    row = conn.execute("SELECT 1 FROM free_claims WHERE ip_address = ? LIMIT 1", (ip_address,)).fetchone()
    conn.close()
    return bool(row)


def create_free_claim(user_id: int, site_id: int, normalized_domain: str, ip_address: str, source_type: str) -> dict:
    conn = get_db()
    cur = conn.execute(
        """
        INSERT INTO free_claims (user_id, site_id, normalized_domain, ip_address, source_type, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, site_id, normalized_domain, ip_address, source_type, now_iso()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM free_claims WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def get_free_claim_for_domain(normalized_domain: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM free_claims WHERE normalized_domain = ? ORDER BY created_at DESC LIMIT 1",
        (normalized_domain,),
    ).fetchone()
    conn.close()
    return _row_or_none(row)


def create_outreach_offer(
    user_id: int,
    site_id: int,
    company_name: str,
    contact_email: str,
    normalized_domain: str,
    headline: str = "",
    notes: str = "",
    preview_url: str = "",
) -> dict:
    token = secrets.token_urlsafe(24)
    conn = get_db()
    cur = conn.execute(
        """
        INSERT INTO outreach_offers (
            token, user_id, site_id, company_name, contact_email, normalized_domain,
            headline, notes, preview_url, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            token,
            user_id,
            site_id,
            company_name.strip(),
            contact_email.strip().lower(),
            normalized_domain,
            headline.strip(),
            notes.strip(),
            preview_url,
            now_iso(),
            now_iso(),
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM outreach_offers WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def get_outreach_offer_by_token(token: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM outreach_offers WHERE token = ?", (token,)).fetchone()
    conn.close()
    return _row_or_none(row)


def get_outreach_offer_by_site(site_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM outreach_offers WHERE site_id = ?", (site_id,)).fetchone()
    conn.close()
    return _row_or_none(row)


def get_outreach_offer_by_contact(contact_email: str, normalized_domain: str = "") -> dict | None:
    conn = get_db()
    if normalized_domain:
        row = conn.execute(
            """
            SELECT * FROM outreach_offers
            WHERE contact_email = ? AND normalized_domain = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (contact_email.strip().lower(), normalized_domain),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT * FROM outreach_offers
            WHERE contact_email = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (contact_email.strip().lower(),),
        ).fetchone()
    conn.close()
    return _row_or_none(row)


def mark_outreach_offer_opened(token: str):
    conn = get_db()
    conn.execute(
        "UPDATE outreach_offers SET opened_at = COALESCE(opened_at, ?), updated_at = ? WHERE token = ?",
        (now_iso(), now_iso(), token),
    )
    conn.commit()
    conn.close()


def mark_outreach_offer_claimed(token: str):
    conn = get_db()
    conn.execute(
        "UPDATE outreach_offers SET claimed_at = COALESCE(claimed_at, ?), updated_at = ? WHERE token = ?",
        (now_iso(), now_iso(), token),
    )
    conn.commit()
    conn.close()


def get_checkout_fulfillment(session_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM checkout_fulfillments WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    return _row_or_none(row)


def start_checkout_fulfillment(
    session_id: str,
    user_id: int | None,
    site_id: int | None,
    offer_token: str,
    customer_email: str,
    plan_code: str,
) -> dict:
    existing = get_checkout_fulfillment(session_id)
    if existing:
        return existing
    conn = get_db()
    conn.execute(
        """
        INSERT INTO checkout_fulfillments (
            session_id, user_id, site_id, offer_token, customer_email, plan_code,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'processing', ?, ?)
        """,
        (session_id, user_id, site_id, offer_token, customer_email, plan_code, now_iso(), now_iso()),
    )
    conn.commit()
    conn.close()
    return get_checkout_fulfillment(session_id)


def complete_checkout_fulfillment(
    session_id: str,
    stripe_customer_id: str = "",
    stripe_subscription_id: str = "",
    login_url: str = "",
    email_sent: bool = False,
    status: str = "fulfilled",
):
    conn = get_db()
    conn.execute(
        """
        UPDATE checkout_fulfillments
        SET stripe_customer_id = ?, stripe_subscription_id = ?, login_url = ?,
            email_sent = ?, status = ?, updated_at = ?
        WHERE session_id = ?
        """,
        (
            stripe_customer_id or None,
            stripe_subscription_id or None,
            login_url or None,
            1 if email_sent else 0,
            status,
            now_iso(),
            session_id,
        ),
    )
    conn.commit()
    conn.close()


def fail_checkout_fulfillment(session_id: str, status: str = "failed"):
    conn = get_db()
    conn.execute(
        "UPDATE checkout_fulfillments SET status = ?, updated_at = ? WHERE session_id = ?",
        (status, now_iso(), session_id),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")

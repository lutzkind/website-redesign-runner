#!/usr/bin/env python3
"""
WebRedesign SaaS — SQLite schema initialization.

Creates and manages all SaaS tables:
  - users         (auth, tier, credits, stripe customer id)
  - sites         (website projects linked to users)
  - credit_txns   (ledger: earned, spent, purchased credits)
  - subscriptions (stripe subscription records)
  - domains       (custom domain mappings / caddy state)
  - login_tokens  (magic-link auth tokens)
"""
import sqlite3
import os
from pathlib import Path
from datetime import datetime, timezone

DB_DIR = Path(os.environ.get("WEBSITE_REDESIGN_ROOT", "/data"))
DB_PATH = DB_DIR / "saas.db"

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Users
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    tier            TEXT NOT NULL DEFAULT 'free',
    credits         INTEGER NOT NULL DEFAULT 0,
    total_credits_purchased INTEGER NOT NULL DEFAULT 0,
    stripe_customer_id TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Login tokens (magic-link auth)
CREATE TABLE IF NOT EXISTS login_tokens (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL,
    token           TEXT UNIQUE NOT NULL,
    used            INTEGER NOT NULL DEFAULT 0,
    expires_at      TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

-- Sites (website projects)
CREATE TABLE IF NOT EXISTS sites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    slug            TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    source_url      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft',
    current_job_id  TEXT,
    subdomain       TEXT,
    custom_domain   TEXT,
    dns_verified    INTEGER NOT NULL DEFAULT 0,
    stripe_product_id TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Credit transactions (audit ledger)
CREATE TABLE IF NOT EXISTS credit_txns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    amount          INTEGER NOT NULL,
    reason          TEXT NOT NULL,
    stripe_session_id TEXT,
    created_at      TEXT NOT NULL
);

-- Subscriptions
CREATE TABLE IF NOT EXISTS subscriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    stripe_subscription_id TEXT UNIQUE,
    stripe_price_id TEXT,
    status          TEXT NOT NULL DEFAULT 'incomplete',
    current_period_end TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Domains (DNS state tracking)
CREATE TABLE IF NOT EXISTS domains (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         INTEGER NOT NULL REFERENCES sites(id),
    domain          TEXT UNIQUE NOT NULL,
    dns_status      TEXT NOT NULL DEFAULT 'pending',
    ssl_status      TEXT NOT NULL DEFAULT 'pending',
    verified_at     TEXT,
    caddy_route_added INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""


def get_db() -> sqlite3.Connection:
    """Get a database connection with row_factory set."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize the database schema."""
    conn = get_db()
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- User helpers ----

def create_user(email: str, name: str = "") -> dict | None:
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, name, tier, credits, created_at, updated_at) VALUES (?, ?, 'free', 3, ?, ?)",
            (email, name, now_iso(), now_iso()),
        )
        uid = cur.lastrowid
        conn.commit()
        # Add initial free credits as a transaction
        conn.execute(
            "INSERT INTO credit_txns (user_id, amount, reason, created_at) VALUES (?, 3, 'signup_bonus', ?)",
            (uid, now_iso()),
        )
        conn.commit()
        return get_user_by_id(uid)
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_user_by_id(uid: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def deduct_credit(uid: int) -> bool:
    """Deduct 1 credit. Returns False if insufficient balance."""
    conn = get_db()
    row = conn.execute("SELECT credits FROM users WHERE id = ?", (uid,)).fetchone()
    if not row or row["credits"] <= 0:
        conn.close()
        return False
    conn.execute("UPDATE users SET credits = credits - 1, updated_at = ? WHERE id = ?", (now_iso(), uid))
    conn.execute("INSERT INTO credit_txns (user_id, amount, reason, created_at) VALUES (?, -1, 'redesign_run', ?)", (uid, now_iso()))
    conn.commit()
    conn.close()
    return True


def add_credits(uid: int, amount: int, reason: str = "purchase", session_id: str = ""):
    conn = get_db()
    conn.execute("UPDATE users SET credits = credits + ?, total_credits_purchased = total_credits_purchased + ?, updated_at = ? WHERE id = ?",
                 (amount, amount, now_iso(), uid))
    conn.execute(
        "INSERT INTO credit_txns (user_id, amount, reason, stripe_session_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (uid, amount, reason, session_id, now_iso()),
    )
    conn.commit()
    conn.close()


def set_tier(uid: int, tier: str):
    conn = get_db()
    conn.execute("UPDATE users SET tier = ?, updated_at = ? WHERE id = ?", (tier, now_iso(), uid))
    conn.commit()
    conn.close()


# ---- Auth token helpers ----

def create_login_token(email: str) -> str:
    import secrets
    token = secrets.token_urlsafe(48)
    expires = now_iso()  # 1 hour from now
    # Calculate 1 hour from now
    from datetime import timedelta
    expires_dt = datetime.now(timezone.utc) + timedelta(hours=1)
    conn = get_db()
    conn.execute(
        "INSERT INTO login_tokens (email, token, expires_at, created_at) VALUES (?, ?, ?, ?)",
        (email, token, expires_dt.strftime("%Y-%m-%dT%H:%M:%SZ"), now_iso()),
    )
    conn.commit()
    conn.close()
    return token


def verify_login_token(token: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM login_tokens WHERE token = ? AND used = 0 AND expires_at > ?",
        (token, now_iso()),
    ).fetchone()
    if not row:
        conn.close()
        return None
    conn.execute("UPDATE login_tokens SET used = 1 WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    user = get_user_by_email(row["email"])
    if not user:
        user = create_user(row["email"])
    return user


# ---- Site helpers ----

def create_site(user_id: int, slug: str, source_url: str, title: str = "") -> dict | None:
    conn = get_db()
    try:
        from datetime import datetime, timezone
        now = now_iso()
        sub = f"{slug}.webredesign.ai"
        cur = conn.execute(
            "INSERT INTO sites (user_id, slug, title, source_url, subdomain, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, slug, title, source_url, sub, now, now),
        )
        sid = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM sites WHERE id = ?", (sid,)).fetchone()
        return dict(row)
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_user_sites(user_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM sites WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_site(site_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_site(site_id: int, **fields):
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values())
    conn = get_db()
    conn.execute(f"UPDATE sites SET {sets}, updated_at = ? WHERE id = ?", (*vals, now_iso(), site_id))
    conn.commit()
    conn.close()


# ---- Domain helpers ----

def create_domain(site_id: int, domain: str) -> dict | None:
    conn = get_db()
    try:
        now = now_iso()
        cur = conn.execute(
            "INSERT INTO domains (site_id, domain, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (site_id, domain, now, now),
        )
        did = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM domains WHERE id = ?", (did,)).fetchone()
        return dict(row)
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_site_domains(site_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM domains WHERE site_id = ?", (site_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_domain(domain_id: int, **fields):
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values())
    conn = get_db()
    conn.execute(f"UPDATE domains SET {sets}, updated_at = ? WHERE id = ?", (*vals, now_iso(), domain_id))
    conn.commit()
    conn.close()


# ---- Subscription helpers ----

def create_subscription(user_id: int, stripe_sub_id: str, stripe_price_id: str) -> dict | None:
    conn = get_db()
    try:
        now = now_iso()
        cur = conn.execute(
            "INSERT INTO subscriptions (user_id, stripe_subscription_id, stripe_price_id, status, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?)",
            (user_id, stripe_sub_id, stripe_price_id, now, now),
        )
        sid = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (sid,)).fetchone()
        set_tier(user_id, "pro")
        return dict(row)
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_user_subscription(user_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def cancel_subscription(user_id: int):
    conn = get_db()
    conn.execute(
        "UPDATE subscriptions SET status = 'canceled', updated_at = ? WHERE user_id = ? AND status = 'active'",
        (now_iso(), user_id),
    )
    conn.execute("UPDATE users SET tier = 'free', updated_at = ? WHERE id = ?", (now_iso(), user_id))
    conn.commit()
    conn.close()


# ---- Credit balance check ----

def get_credit_balance(user_id: int) -> dict:
    conn = get_db()
    user = conn.execute("SELECT credits, tier FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not user:
        return {"credits": 0, "tier": "free", "unlimited": False}
    return {
        "credits": user["credits"],
        "tier": user["tier"],
        "unlimited": user["tier"] == "pro",
    }


def get_credit_history(user_id: int, limit: int = 50) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM credit_txns WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")

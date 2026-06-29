"""User accounts — email + bcrypt password hashing, role checks, OAuth-ready.

Schema (added to core/memory.py):
    users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',  -- admin | user | readonly
        password_hash TEXT,                 -- bcrypt; NULL for OAuth-only users
        oauth_provider TEXT,                -- 'google' | 'github' | NULL
        oauth_id TEXT,
        created_at TEXT NOT NULL,
        last_seen TEXT
    )

Roles:
    admin   — full read/write
    user    — full read/write to own data
    readonly — read-only

The legacy single-user deployment (no auth) is supported by a special
'legacy' user (id='user_legacy') that owns all rows created before this
schema landed. See core/memory.py:_backfill_user_id() for the migration.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
import uuid

import bcrypt

logger = logging.getLogger(__name__)

VALID_ROLES = frozenset({"admin", "user", "readonly"})
LEGACY_USER_ID = "user_legacy"
LEGACY_USER_EMAIL = "legacy+noreply@nexus01.local"
LEGACY_USER_NAME = "Legacy User"

# Email is permissive: local + domain, TLD 2+ chars. Reject obvious garbage.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# bcrypt cost factor: 12 ≈ 250ms on modern hardware, OWASP minimum for 2024+
_BCRYPT_ROUNDS = 12


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _new_id() -> str:
    return "user_" + uuid.uuid4().hex[:12]


def hash_password(plaintext: str) -> str:
    """Hash a password with bcrypt. Returns the encoded hash (includes salt + cost)."""
    if not plaintext:
        raise ValueError("password must not be empty")
    if len(plaintext) > 1024:
        # bcrypt truncates at 72 bytes anyway, but reject obvious DoS / overflow early
        raise ValueError("password too long (max 1024 chars)")
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plaintext: str, password_hash: str) -> bool:
    """Constant-time check. Returns False on any failure (bad hash, mismatch, etc)."""
    if not plaintext or not password_hash:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash (e.g., not a bcrypt hash at all)
        return False


def validate_email(email: str) -> str:
    """Normalize (strip, lowercase) and validate. Raises ValueError on bad input."""
    if not email:
        raise ValueError("email is required")
    e = email.strip().lower()
    if not _EMAIL_RE.match(e):
        raise ValueError(f"invalid email: {email!r}")
    if len(e) > 254:  # RFC 5321 max
        raise ValueError("email too long")
    return e


def validate_name(name: str) -> str:
    if not name or not name.strip():
        raise ValueError("name is required")
    n = name.strip()
    if len(n) > 120:
        raise ValueError("name too long (max 120 chars)")
    return n


def validate_role(role: str) -> str:
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role: {role!r}; must be one of {sorted(VALID_ROLES)}")
    return role


class UserStore:
    """CRUD + auth for users. Backed by the `users` table in the main memory DB."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._ensure_legacy_user()

    # ── Read ────────────────────────────────────────────────────────────

    def get(self, user_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return self._row(row) if row else None

    def get_by_email(self, email: str) -> dict | None:
        try:
            email = validate_email(email)
        except ValueError:
            return None
        row = self._conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        return self._row(row) if row else None

    def get_by_oauth(self, provider: str, oauth_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE oauth_provider = ? AND oauth_id = ?",
            (provider, oauth_id),
        ).fetchone()
        return self._row(row) if row else None

    def list(self, limit: int = 100) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [r for r in (self._row(row) for row in rows) if r is not None]

    # ── Write ───────────────────────────────────────────────────────────

    def create(
        self, email: str, name: str, password: str | None = None, *,
        role: str = "user", oauth_provider: str | None = None, oauth_id: str | None = None,
    ) -> dict:
        """Create a new user. Password is required unless creating an OAuth-only user.

        Raises ValueError on validation failure or duplicate email.
        Returns the created user dict (without password_hash).
        """
        email = validate_email(email)
        name = validate_name(name)
        role = validate_role(role)

        if password is None and not (oauth_provider and oauth_id):
            raise ValueError("password is required for non-OAuth users")
        if password is not None:
            password_hash = hash_password(password)
        else:
            password_hash = None

        if self.get_by_email(email) is not None:
            raise ValueError(f"email already registered: {email}")

        uid = _new_id()
        now = _now_iso()
        self._conn.execute(
            """INSERT INTO users
               (id, email, name, role, password_hash, oauth_provider, oauth_id, created_at, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uid, email, name, role, password_hash, oauth_provider, oauth_id, now, None),
        )
        self._conn.commit()
        logger.info("[users] created uid=%s email=%s role=%s", uid, email, role)
        return self.get(uid)  # type: ignore[return-value]

    def update(
        self, user_id: str, *, name: str | None = None, role: str | None = None,
        password: str | None = None,
    ) -> dict | None:
        """Update mutable fields. Returns the updated user, or None if not found."""
        user = self.get(user_id)
        if user is None:
            return None
        new_name = validate_name(name) if name is not None else user["name"]
        new_role = validate_role(role) if role is not None else user["role"]
        new_hash = hash_password(password) if password is not None else user.get("password_hash")
        self._conn.execute(
            "UPDATE users SET name = ?, role = ?, password_hash = ? WHERE id = ?",
            (new_name, new_role, new_hash, user_id),
        )
        self._conn.commit()
        return self.get(user_id)

    def delete(self, user_id: str) -> bool:
        if user_id == LEGACY_USER_ID:
            raise ValueError("cannot delete the legacy user")
        cur = self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def touch(self, user_id: str) -> None:
        """Update last_seen timestamp. Silent no-op if user doesn't exist."""
        self._conn.execute(
            "UPDATE users SET last_seen = ? WHERE id = ?", (_now_iso(), user_id)
        )
        self._conn.commit()

    # ── Auth ────────────────────────────────────────────────────────────

    def authenticate(self, email: str, password: str) -> dict | None:
        """Verify email + password. Returns the user dict on success, None on failure.

        On success, bumps last_seen. Always runs a bcrypt comparison so the
        timing for "user not found" is similar to "wrong password" — but
        we accept that those are still slightly distinguishable to a
        determined attacker.
        """
        # Internal fetch that keeps password_hash
        row = self._conn.execute(
            "SELECT * FROM users WHERE email = ?", (validate_email(email),)
        ).fetchone()
        if row is None:
            verify_password(password, "$2b$12$" + "x" * 53)  # constant-time
            return None
        password_hash = row["password_hash"]
        if not password_hash:
            # OAuth-only user — never authenticate by password
            verify_password(password, "$2b$12$" + "x" * 53)
            return None
        if not verify_password(password, password_hash):
            return None
        self.touch(row["id"])
        return self._row(row)

    # ── Helpers ─────────────────────────────────────────────────────────

    def _ensure_legacy_user(self) -> None:
        """Create the legacy user if it doesn't exist. Idempotent."""
        existing = self.get(LEGACY_USER_ID)
        if existing is not None:
            return
        # Use raw SQL — create() requires password and validates role
        self._conn.execute(
            """INSERT OR IGNORE INTO users
               (id, email, name, role, password_hash, oauth_provider, oauth_id, created_at, last_seen)
               VALUES (?, ?, ?, 'admin', NULL, NULL, NULL, ?, NULL)""",
            (LEGACY_USER_ID, LEGACY_USER_EMAIL, LEGACY_USER_NAME, _now_iso()),
        )
        self._conn.commit()
        logger.info("[users] ensured legacy user uid=%s", LEGACY_USER_ID)

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        # Never return the password hash to callers
        d.pop("password_hash", None)
        return d

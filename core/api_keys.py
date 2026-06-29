"""API keys — scoped per-user tokens, hashed at rest, JWT-friendly.

Schema (added to core/memory.py):
    api_keys (
        key_hash TEXT PRIMARY KEY,         -- sha256(raw_key)
        user_id TEXT NOT NULL,
        scope TEXT NOT NULL DEFAULT 'user', -- admin | user | readonly
        name TEXT,                          -- human label
        created_at TEXT NOT NULL,
        last_used TEXT,
        expires_at TEXT
    )

Key format: 'nxk_<user_id_short>_<random>' — about 60 chars total.
The raw key is returned ONCE on creation; we store only the sha256 hash.
This is the same pattern GitHub, Stripe, etc. use.

The buildplan's `X-API-Key` header continues to work for legacy
environment-configured keys (NEXUS_API_KEY / NEXUS_READONLY_KEY) — those
are checked alongside db-backed keys in api.auth.resolve_key.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
import time

logger = logging.getLogger(__name__)

VALID_SCOPES = frozenset({"admin", "user", "readonly"})

# Format prefix helps us recognize our own keys vs random garbage
KEY_PREFIX = "nxk_"
KEY_RANDOM_BYTES = 32  # 256 bits of entropy


def generate_key() -> tuple[str, str]:
    """Generate a new API key. Returns (raw_key, sha256_hash)."""
    random_part = secrets.token_urlsafe(KEY_RANDOM_BYTES)
    raw = f"{KEY_PREFIX}{random_part}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, h


def hash_key(raw: str) -> str:
    """sha256 of a raw key, lowercase hex. Stable for lookup."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def mask_key(raw: str) -> str:
    """Return a short, safe representation for UI display.
    e.g. 'nxk_abc...xyz' (first 7 + last 4 chars)."""
    if not raw or len(raw) < 12:
        return "***"
    return f"{raw[:7]}...{raw[-4:]}"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def validate_scope(scope: str) -> str:
    if scope not in VALID_SCOPES:
        raise ValueError(f"invalid scope: {scope!r}; must be one of {sorted(VALID_SCOPES)}")
    return scope


class ApiKeyStore:
    """CRUD for API keys. Backed by the `api_keys` table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(
        self, user_id: str, *, scope: str = "user", name: str | None = None,
        expires_at: str | None = None,
    ) -> dict:
        """Create a new key. Returns {raw_key, id, ...} — raw_key is shown ONCE.

        Raises ValueError on invalid scope.
        """
        scope = validate_scope(scope)
        raw, key_hash = generate_key()
        now = _now_iso()
        self._conn.execute(
            """INSERT INTO api_keys
               (key_hash, user_id, scope, name, created_at, last_used, expires_at)
               VALUES (?, ?, ?, ?, ?, NULL, ?)""",
            (key_hash, user_id, scope, name, now, expires_at),
        )
        self._conn.commit()
        logger.info("[api_keys] created user_id=%s scope=%s name=%s", user_id, scope, name)
        return {
            "raw_key": raw,
            "key_hash": key_hash,
            "user_id": user_id,
            "scope": scope,
            "name": name,
            "created_at": now,
            "last_used": None,
            "expires_at": expires_at,
        }

    def lookup(self, raw_key: str) -> dict | None:
        """Look up by raw key. Returns the key record (with user_id, scope) or None.

        Updates last_used on hit. Skips expired keys.
        """
        if not raw_key or not raw_key.startswith(KEY_PREFIX):
            return None
        key_hash = hash_key(raw_key)
        row = self._conn.execute(
            "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
        ).fetchone()
        if row is None:
            return None
        rec = dict(row)
        if rec.get("expires_at") and rec["expires_at"] < _now_iso():
            return None
        # Best-effort last_used bump — failure here must not break auth
        now = _now_iso()
        try:
            self._conn.execute(
                "UPDATE api_keys SET last_used = ? WHERE key_hash = ?",
                (now, key_hash),
            )
            self._conn.commit()
            rec["last_used"] = now
        except sqlite3.OperationalError:
            logger.warning("[api_keys] failed to bump last_used (concurrent write?)")
        return rec

    def list_for_user(self, user_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT key_hash, user_id, scope, name, created_at, last_used, expires_at "
            "FROM api_keys WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [self._public_view(dict(r)) for r in rows]

    def revoke(self, key_hash: str, user_id: str | None = None) -> bool:
        """Revoke a key. If user_id is given, only revoke if it belongs to that user."""
        if user_id is not None:
            cur = self._conn.execute(
                "DELETE FROM api_keys WHERE key_hash = ? AND user_id = ?",
                (key_hash, user_id),
            )
        else:
            cur = self._conn.execute(
                "DELETE FROM api_keys WHERE key_hash = ?", (key_hash,)
            )
        self._conn.commit()
        return cur.rowcount > 0

    def revoke_all_for_user(self, user_id: str) -> int:
        cur = self._conn.execute("DELETE FROM api_keys WHERE user_id = ?", (user_id,))
        self._conn.commit()
        return cur.rowcount

    @staticmethod
    def _public_view(rec: dict) -> dict:
        """Return the key record in a UI-safe form (no raw_key, no hash)."""
        return {
            "id": rec["key_hash"][:12],   # short ID for the UI
            "scope": rec["scope"],
            "name": rec.get("name"),
            "created_at": rec["created_at"],
            "last_used": rec.get("last_used"),
            "expires_at": rec.get("expires_at"),
        }

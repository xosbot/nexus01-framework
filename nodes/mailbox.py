"""Durable per-node mailboxes — one message per JSON file, atomic writes, .done retention."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

MAX_HOPS = 8

ALLOWED_ACTS = frozenset(
    {"request", "inform", "propose", "query", "agree", "refuse", "done", "error"}
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_message_id(prefix: str = "msg") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def mailbox_dirs(base_dir: str | Path, node_id: str) -> dict[str, Path]:
    root = Path(base_dir) / node_id
    return {
        "root": root,
        "inbox": root / "inbox",
        "inbox_done": root / "inbox" / ".done",
        "outbox": root / "outbox",
        "outbox_done": root / "outbox" / ".done",
    }


def ensure_mailbox(base_dir: str | Path, node_id: str) -> dict[str, Path]:
    dirs = mailbox_dirs(base_dir, node_id)
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def validate_message(msg: dict) -> dict:
    if not isinstance(msg, dict):
        raise ValueError("Message must be a dict")
    for key in ("id", "correlation_id", "from", "to", "act", "body"):
        if not msg.get(key):
            raise ValueError(f"Message missing {key}")
    if msg["act"] not in ALLOWED_ACTS:
        raise ValueError(f"Unknown act {msg['act']!r}")
    hops = int(msg.get("hops", 0))
    if hops < 0:
        raise ValueError("hops must be >= 0")
    if hops > MAX_HOPS:
        raise ValueError(f"hops {hops} exceeds MAX_HOPS {MAX_HOPS}")
    # prevent path traversal via id
    mid = msg["id"]
    if "/" in mid or "\\" in mid or ".." in mid:
        raise ValueError("Invalid message id")
    return msg


def write_message_atomic(box_dir: Path, msg: dict) -> Path:
    """Write temp file + flush + fsync + atomic rename. Never expose partial writes."""
    validate_message(msg)
    box_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(msg, sort_keys=True, ensure_ascii=False)
    if len(payload) > 1_000_000:
        raise ValueError("Message too large")
    fd, tmp = tempfile.mkstemp(dir=str(box_dir), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        dest = box_dir / f"{msg['id']}.json"
        os.rename(tmp, dest)
        return dest
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def list_pending(box_dir: Path) -> list[dict]:
    """List live (non-.done) messages sorted by name."""
    if not box_dir.exists():
        return []
    out = []
    for p in sorted(box_dir.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def mark_done(box_dir: Path, message_id: str) -> bool:
    """Move processed message to .done/. Never delete immediately."""
    src = box_dir / f"{message_id}.json"
    if not src.exists():
        return False
    done = box_dir / ".done"
    done.mkdir(parents=True, exist_ok=True)
    dest = done / f"{message_id}.json"
    try:
        os.rename(src, dest)
        return True
    except OSError:
        return False


def list_done(box_dir: Path) -> list[dict]:
    done = box_dir / ".done"
    if not done.exists():
        return []
    out = []
    for p in sorted(done.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def build_message(
    *,
    to: str,
    body: str,
    sender: str = "nexus",
    act: str = "request",
    subject: str = "task",
    correlation_id: str | None = None,
    hops: int = 0,
    requires_reply: bool = True,
) -> dict:
    if act not in ALLOWED_ACTS:
        raise ValueError(f"Unknown act {act!r}")
    if hops > MAX_HOPS:
        raise ValueError("hops exceeds MAX_HOPS")
    return {
        "id": new_message_id(),
        "correlation_id": correlation_id or f"corr_{uuid.uuid4().hex[:12]}",
        "from": sender,
        "to": to,
        "act": act,
        "subject": subject,
        "body": body,
        "hops": hops,
        "requires_reply": requires_reply,
        "created_at": _now_iso(),
    }

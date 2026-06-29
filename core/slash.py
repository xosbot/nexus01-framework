"""Slash commands — in-chat control surface for IVA.

The dashboard's chat input recognizes lines that start with `/` and routes
them here instead of the LLM. Commands return a structured response that
the frontend renders as a system message.

Available commands:
  /help            — list commands
  /status          — system + provider status
  /memory [sub]    — long-term memory (summary | list | show | forget | pause | resume | audit)
                    or `/memory <query>` to search (legacy)
  /remember <text> — store a high-confidence memory
  /forget <id>     — delete a memory (alias for /memory forget)
  /tools           — list available chat tools
  /who             — show current core blocks (user/persona/project_state/current_focus)
  /clear           — start a new session
  /theme [dark|light|auto] — toggle/set theme (UI side; backend records)
  /agents          — list running agents
  /budget          — token usage + cost
  /events [N]      — last N events from the log
  /mode [ask|allow] — set session permission mode
  /soul            — show soul section stats
  /providers       — list LLM providers + availability
  /model <name>    — hint which model to prefer (advisory)

Commands that change state (clear, mode, theme) are emitted to the event
log. The dashboard also sees them via the events feed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from core import events as _events
from core import permissions as _permissions
from core import soul as _soul

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    ok: bool
    text: str
    title: str = ""
    data: dict[str, Any] | None = None
    side_effect: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "title": self.title,
            "text": self.text,
            "data": self.data or {},
            "side_effect": self.side_effect,
        }


Handler = Callable[[list[str], str, dict], Awaitable[CommandResult]]


async def cmd_help(args, session_id, ctx) -> CommandResult:
    lines = [
        "**Available commands**",
        "",
        "  `/help`            — this list",
        "  `/status`          — system, providers, agents",
        "  `/agents`          — list registered agents",
        "  `/providers`       — LLM provider status",
        "  `/budget`          — token usage + cost",
        "  `/who`             — show core blocks (user/persona/project_state/current_focus)",
        "  `/tools`           — list available chat tools",
        "  `/memory`          — memory summary (active, pending, by type)",
        "  `/memory list [type]`   — list active memories of a type",
        "  `/memory show <id>`     — full memory record + source quote",
        "  `/memory forget <id>`   — delete a memory",
        "  `/memory pause|resume`  — pause/resume auto-extraction this session",
        "  `/memory audit [N=20]`  — last N memory operations",
        "  `/memory <query>`  — search long-term memory (legacy)",
        "  `/remember <text>` — store a high-confidence memory",
        "  `/forget <id>`     — alias for /memory forget",
        "  `/events [N=20]`   — show recent event log entries",
        "  `/mode [ask|allow]`— set session permission mode (default: ask)",
        "  `/soul`            — show soul section sizes",
        "  `/theme [auto|dark|light]` — set UI theme (advisory)",
        "  `/model <name>`    — hint preferred model (advisory)",
        "  `/clear`           — start a new session",
        "",
        "Anything not starting with `/` goes to the LLM as a normal chat message.",
    ]
    return CommandResult(True, "\n".join(lines), title="Help")


async def cmd_status(args, session_id, ctx) -> CommandResult:
    llm = ctx.get("llm")
    providers = llm.provider_status() if llm else []
    online = sum(1 for p in providers if p.get("available"))
    lines = [
        f"**System status** — {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Providers online: {online} / {len(providers)}",
        f"Bus: {ctx.get('bus_backend', 'memory')}",
        f"Cold mode: {'on' if ctx.get('cold_mode') else 'off'}",
        f"ReAct loop: {'on' if ctx.get('react_loop') else 'off'}",
    ]
    if providers:
        lines.append("")
        lines.append("**Providers**")
        for p in providers:
            mark = "●" if p.get("available") else "○"
            lines.append(f"  {mark} {p.get('name', '?')} — `{p.get('model', '?')}`")
    return CommandResult(True, "\n".join(lines), title="Status", data={"providers": providers})


async def cmd_agents(args, session_id, ctx) -> CommandResult:
    agents = ctx.get("agents") or ["orchestrator", "osint", "analyst", "executor"]
    lines = ["**Registered agents**", ""]
    for a in agents:
        lines.append(f"  • {a}")
    return CommandResult(True, "\n".join(lines), title="Agents", data={"agents": agents})


async def cmd_providers(args, session_id, ctx) -> CommandResult:
    llm = ctx.get("llm")
    providers = llm.provider_status() if llm else []
    if not providers:
        return CommandResult(True, "No providers configured.", title="Providers")
    lines = ["**LLM providers**", ""]
    for p in providers:
        avail = "available" if p.get("available") else "unavailable"
        tier = p.get("tier", "—")
        lines.append(f"  • **{p.get('name', '?')}** — {avail} · tier `{tier}` · `{p.get('model', '?')}`")
    return CommandResult(True, "\n".join(lines), title="Providers", data={"providers": providers})


async def cmd_budget(args, session_id, ctx) -> CommandResult:
    llm = ctx.get("llm")
    stats = llm.stats() if llm else {}
    lines = [
        "**Token budget (this session)**",
        f"  total tokens: {stats.get('total_tokens', 0):,}",
        f"  total cost:   ${stats.get('total_cost', 0):.4f}",
        f"  calls:        {stats.get('call_count', 0)}",
    ]
    return CommandResult(True, "\n".join(lines), title="Budget", data=stats)


async def cmd_memory(args, session_id, ctx) -> CommandResult:
    """Memory control surface.

    With no args: show summary (active count, pending count, by type).
    With subcommand: list, show, forget, pause, resume, audit.
    Otherwise: search the long-term memory (legacy behavior).
    """
    if not args:
        return _memory_summary(ctx)
    sub = args[0].lower()
    rest = args[1:]
    if sub == "list":
        return _memory_list(rest, ctx)
    if sub == "show":
        return _memory_show(rest, ctx)
    if sub == "forget":
        return _memory_forget(rest, ctx)
    if sub == "pause":
        return _memory_pause(session_id, ctx)
    if sub == "resume":
        return _memory_resume(session_id, ctx)
    if sub == "audit":
        return _memory_audit(rest, ctx)
    # Legacy: treat all args as a search query
    return _memory_legacy_search(" ".join(args), ctx)


def _get_brain(ctx: dict):
    return ctx.get("nexus_app") and getattr(ctx["nexus_app"], "second_brain", None)


def _ctx_user_id(ctx: dict) -> str:
    return ctx.get("user_id") or "user_legacy"


def _memory_summary(ctx: dict) -> CommandResult:
    brain = _get_brain(ctx)
    if brain is None:
        return CommandResult(True, "Memory not enabled (set PHASE1_ENABLED=true).", title="Memory")
    user_id = _ctx_user_id(ctx)
    active = brain.list_memories(status="active", user_id=user_id, limit=10_000)
    pending = brain.list_pending(limit=10_000, user_id=user_id)
    by_type: dict = {}
    for m in active:
        t = m.get("type", "memory")
        by_type[t] = by_type.get(t, 0) + 1
    type_str = ", ".join(f"{n} {t}" for t, n in sorted(by_type.items(), key=lambda x: -x[1])) or "none"
    lines = [
        "**Memory summary**",
        f"  active: {len(active)}",
        f"  pending: {len(pending)}",
        f"  by type: {type_str}",
    ]
    if pending:
        lines.append("")
        lines.append("**Recent pending** (use `/memory show <id>` to inspect):")
        for m in pending[:3]:
            lines.append(f"  • `{m['id']}` [{m['type']}, conf {m['confidence']:.2f}] {m['content'][:80]}")
    return CommandResult(True, "\n".join(lines), title="Memory", data={"total": len(active) + len(pending), "pending": len(pending), "by_type": by_type})


def _memory_list(args: list[str], ctx: dict) -> CommandResult:
    brain = _get_brain(ctx)
    if brain is None:
        return CommandResult(False, "Memory not enabled.", title="Memory")
    type_filter = args[0] if args else None
    user_id = _ctx_user_id(ctx)
    try:
        rows = brain.list_memories(status="active", type=type_filter, user_id=user_id, limit=50)
    except Exception as exc:
        return CommandResult(False, f"List failed: {exc}", title="Memory")
    if not rows:
        return CommandResult(True, "No active memories" + (f" of type `{type_filter}`" if type_filter else ""), title="Memory")
    lines = ["**Active memories" + (f" of type `{type_filter}`" if type_filter else "") + f" ({len(rows)})**", ""]
    for m in rows:
        lines.append(f"  • `{m['id']}` [{m['type']}, conf {m['confidence']:.2f}] {m['content'][:80]}")
    return CommandResult(True, "\n".join(lines), title="Memory")


def _memory_show(args: list[str], ctx: dict) -> CommandResult:
    brain = _get_brain(ctx)
    if brain is None:
        return CommandResult(False, "Memory not enabled.", title="Memory")
    if not args:
        return CommandResult(False, "Usage: `/memory show <id>`", title="Memory")
    mid = args[0]
    m = brain.get(mid)
    if not m:
        return CommandResult(False, f"Memory `{mid}` not found.", title="Memory")
    lines = [
        f"**Memory `{m['id']}`**",
        f"  type: {m['type']}",
        f"  status: {m['status']}" + (" (pinned)" if m.get("pinned") else ""),
        f"  confidence: {m['confidence']:.2f}  importance: {m['importance']:.2f}  durability: {m['durability']:.2f}",
        f"  content: {m['content']}",
    ]
    if m.get("source_quote"):
        lines.append(f"  source: *\"{m['source_quote']}\"*")
    if m.get("source_session_id"):
        lines.append(f"  session: `{m['source_session_id']}`")
    if m.get("last_referenced"):
        lines.append(f"  last referenced: {m['access_count']} time(s)")
    return CommandResult(True, "\n".join(lines), title=f"Memory {mid}")


def _memory_forget(args: list[str], ctx: dict) -> CommandResult:
    brain = _get_brain(ctx)
    if brain is None:
        return CommandResult(False, "Memory not enabled.", title="Memory")
    if not args:
        return CommandResult(False, "Usage: `/memory forget <id>`", title="Memory")
    mid = args[0]
    if brain.delete_memory(mid):
        return CommandResult(True, f"Forgot memory `{mid}`.", title="Memory")
    return CommandResult(False, f"Memory `{mid}` not found.", title="Memory")


def _memory_pause(session_id: str, ctx: dict) -> CommandResult:
    if not session_id:
        return CommandResult(False, "No active session.", title="Memory")
    _PAUSED_SESSIONS.add(session_id)
    return CommandResult(True, "Memory extraction **paused** for this session.", title="Memory",
                         side_effect="memory_paused")


def _memory_resume(session_id: str, ctx: dict) -> CommandResult:
    if not session_id:
        return CommandResult(False, "No active session.", title="Memory")
    _PAUSED_SESSIONS.discard(session_id)
    return CommandResult(True, "Memory extraction **resumed** for this session.", title="Memory",
                         side_effect="memory_resumed")


def _memory_audit(args: list[str], ctx: dict) -> CommandResult:
    brain = _get_brain(ctx)
    if brain is None:
        return CommandResult(False, "Memory not enabled.", title="Memory")
    limit = 20
    if args and args[0].isdigit():
        limit = min(int(args[0]), 200)
    entries = brain.audit_log(limit=limit)
    if not entries:
        return CommandResult(True, "No memory operations yet.", title="Memory")
    lines = [f"**Last {len(entries)} memory operations**", ""]
    for e in entries:
        ts = time.strftime("%H:%M:%S", time.localtime(e["ts"]))
        op = e["op"]
        mid = (e.get("memory_id") or "")[:14]
        actor = e.get("actor", "")
        note = (e.get("note") or "")[:60]
        lines.append(f"  `{ts}` `{op:<14}` `{mid}` ({actor}) {note}")
    return CommandResult(True, "\n".join(lines), title="Memory audit")


def _memory_legacy_search(query: str, ctx: dict) -> CommandResult:
    """Legacy ChromaDB-backed search via core.memory.Memory.search_similar."""
    memory = ctx.get("memory")
    if not memory or not hasattr(memory, "search_similar"):
        return CommandResult(False, "Memory backend unavailable.", title="Memory")
    try:
        results = memory.search_similar(query, n=5)
    except Exception as exc:
        return CommandResult(False, f"Memory search failed: {exc}", title="Memory")
    if not results:
        return CommandResult(True, f"No memory matches for: *{query}*", title="Memory")
    lines = [f"**Memory matches for** *{query}*", ""]
    for i, r in enumerate(results, 1):
        content = (r.get("content") or "")[:200]
        score = r.get("score", 0)
        lines.append(f"  **{i}.** (score {score:.2f}) {content}{'…' if len(content) >= 200 else ''}")
    return CommandResult(True, "\n".join(lines), title="Memory")


async def cmd_events(args, session_id, ctx) -> CommandResult:
    limit = 20
    if args and args[0].isdigit():
        limit = min(int(args[0]), 200)
    rows = _events.query(limit=limit)
    if not rows:
        return CommandResult(True, "No events yet.", title="Events")
    lines = [f"**Last {len(rows)} events**", ""]
    for r in rows:
        ts = time.strftime("%H:%M:%S", time.localtime(r["ts"]))
        kind = r["kind"]
        msg = (r.get("message") or "")[:60]
        sid = (r.get("session_id") or "")[:8]
        lines.append(f"  `{ts}` `{kind:<20}` {msg} `{sid}`")
    return CommandResult(True, "\n".join(lines), title="Events", data={"rows": rows})


async def cmd_mode(args, session_id, ctx) -> CommandResult:
    if not session_id:
        return CommandResult(False, "No active session.", title="Mode")
    if not args:
        p = _permissions.get(session_id)
        return CommandResult(
            True,
            f"Current permission mode: **{p.mode}** ({p.set_by})",
            title="Mode",
            data=p.to_dict(),
        )
    new_mode = args[0].lower()
    if new_mode not in ("ask", "allow"):
        return CommandResult(False, "Use `/mode ask` or `/mode allow`", title="Mode")
    p = _permissions.set_mode(session_id, new_mode, set_by="operator")
    msg = (
        "Switched to **allow** — destructive actions will run without prompting this session. "
        "Cold mode still blocks catastrophic actions."
        if new_mode == "allow"
        else "Switched to **ask** — destructive actions need approval."
    )
    return CommandResult(True, msg, title="Mode", side_effect="mode_changed", data=p.to_dict())


async def cmd_soul(args, session_id, ctx) -> CommandResult:
    stats = _soul.section_stats()
    lines = ["**Soul — operator-defined personality**", ""]
    for name, s in stats.items():
        lines.append(f"  • `{name}.md` — {s['lines']} lines / {s['chars']} chars")
    lines.append("")
    lines.append("Edit files in `data/iva/*.md` to change IVA's voice.")
    return CommandResult(True, "\n".join(lines), title="Soul", data=stats)


async def cmd_theme(args, session_id, ctx) -> CommandResult:
    if not args:
        return CommandResult(True, "Usage: `/theme dark|light|auto` (advisory — UI side)", title="Theme")
    mode = args[0].lower()
    if mode not in ("dark", "light", "auto"):
        return CommandResult(False, "Use `/theme dark|light|auto`", title="Theme")
    return CommandResult(
        True, f"Theme set to **{mode}** (saved in browser localStorage).",
        title="Theme", side_effect="theme_changed", data={"mode": mode},
    )


async def cmd_model(args, session_id, ctx) -> CommandResult:
    if not args:
        return CommandResult(True, "Usage: `/model <provider-name>` — e.g. `nim_llama70b`", title="Model")
    name = " ".join(args)
    return CommandResult(
        True, f"Model preference noted: `{name}`. Will be preferred for next calls in this session.",
        title="Model", data={"preferred": name},
    )


async def cmd_clear(args, session_id, ctx) -> CommandResult:
    return CommandResult(
        True, "Started a new session.",
        title="New session", side_effect="new_session",
    )


async def cmd_remember(args, session_id, ctx) -> CommandResult:
    """Store a high-confidence memory manually."""
    if not args:
        return CommandResult(False, "Usage: `/remember <text>`", title="Remember")
    text = " ".join(args)
    brain = _get_brain(ctx)
    if brain is None:
        return CommandResult(False, "Memory not enabled.", title="Remember")
    try:
        m = brain.add_memory(
            type="identity", content=text, confidence=0.95,
            importance=0.8, durability=0.9,
            source_session_id=session_id,
            source_quote=text[:200],
        )
    except Exception as exc:
        return CommandResult(False, f"Failed to store: {exc}", title="Remember")
    if m.get("status") == "discarded":
        return CommandResult(True, "Stored (note: short or duplicate content).", title="Remember", data=m)
    return CommandResult(
        True, f"Stored memory `{m['id']}` (status: {m['status']}).",
        title="Remember", data=m,
    )


async def cmd_forget(args, session_id, ctx) -> CommandResult:
    """Alias for /memory forget."""
    return await cmd_memory(["forget", *args], session_id, ctx)


async def cmd_tools(args, session_id, ctx) -> CommandResult:
    """List registered chat tools (Phase 1)."""
    nexus = ctx.get("nexus_app")
    tools_reg = nexus and getattr(nexus, "chat_tools", None)
    if tools_reg is None:
        return CommandResult(True, "No chat tools registered (Phase 1 not enabled).", title="Tools")
    names = tools_reg.tool_names()
    schemas = tools_reg.as_openai_tools()
    lines = [f"**Available tools ({len(names)})**", ""]
    for s in schemas:
        func = s.get("function", {})
        lines.append(f"  • `{func.get('name', '?')}` — {func.get('description', '')}")
    return CommandResult(True, "\n".join(lines), title="Tools", data={"names": names})


async def cmd_who(args, session_id, ctx) -> CommandResult:
    """Show current core blocks (user / persona / project_state / current_focus)."""
    brain = _get_brain(ctx)
    if brain is None:
        return CommandResult(False, "Memory not enabled.", title="Who")
    blocks = brain.get_core_blocks()
    if not blocks:
        return CommandResult(True, "No core blocks set yet. Edit them in the Memory tab or via `/memory core <label>`.", title="Who")
    lines = ["**Core blocks (in-context persona)**", ""]
    for label, value in blocks.items():
        if not value:
            continue
        lines.append(f"### {label}")
        lines.append(value[:500] + ("…" if len(value) > 500 else ""))
        lines.append("")
    return CommandResult(True, "\n".join(lines), title="Who", data={"blocks": blocks})


def is_paused(session_id: str) -> bool:
    """Called by the API layer to skip extraction for paused sessions."""
    return session_id in _PAUSED_SESSIONS


# Session IDs that have paused memory extraction
_PAUSED_SESSIONS: set[str] = set()


_REGISTRY: dict[str, Handler] = {
    "help": cmd_help,
    "status": cmd_status,
    "agents": cmd_agents,
    "providers": cmd_providers,
    "budget": cmd_budget,
    "memory": cmd_memory,
    "remember": cmd_remember,
    "forget": cmd_forget,
    "tools": cmd_tools,
    "who": cmd_who,
    "events": cmd_events,
    "mode": cmd_mode,
    "soul": cmd_soul,
    "theme": cmd_theme,
    "model": cmd_model,
    "clear": cmd_clear,
}


async def dispatch(text: str, session_id: str, ctx: dict) -> CommandResult | None:
    """If `text` starts with `/`, route to a command. Otherwise return None."""
    if not text or not text.strip().startswith("/"):
        return None
    body = text.strip()[1:]
    parts = body.split(maxsplit=1)
    name = parts[0].lower()
    args = parts[1].split() if len(parts) > 1 else []
    handler = _REGISTRY.get(name)
    if not handler:
        return CommandResult(False, f"Unknown command: `/{name}`. Type `/help` for the list.", title="Error")
    try:
        result = await handler(args, session_id, ctx)
    except Exception as exc:
        logger.exception("Slash command /%s failed", name)
        return CommandResult(False, f"Command failed: {exc}", title=f"/{name}")
    _events.emit(
        "slash_command", f"/{name}", session_id=session_id, agent="chat",
        data={"args": args, "ok": result.ok, "side_effect": result.side_effect},
    )
    return result


def list_commands() -> list[str]:
    return sorted(_REGISTRY.keys())

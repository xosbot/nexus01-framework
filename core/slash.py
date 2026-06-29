"""Slash commands — in-chat control surface for IVA.

The dashboard's chat input recognizes lines that start with `/` and routes
them here instead of the LLM. Commands return a structured response that
the frontend renders as a system message.

Available commands:
  /help            — list commands
  /status          — system + provider status
  /memory <query>  — search long-term memory
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
        "  `/memory <query>`  — search long-term memory",
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
    if not args:
        return CommandResult(True, "Usage: `/memory <query>`", title="Memory")
    query = " ".join(args)
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


_REGISTRY: dict[str, Handler] = {
    "help": cmd_help,
    "status": cmd_status,
    "agents": cmd_agents,
    "providers": cmd_providers,
    "budget": cmd_budget,
    "memory": cmd_memory,
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

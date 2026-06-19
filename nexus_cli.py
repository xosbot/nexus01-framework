#!/usr/bin/env python3
"""
NEXUS-01 terminal client — local REPL or remote API client.

  python nexus_cli.py              # interactive (uses API if running, else prompts to start main.py)
  python nexus_cli.py chat "query" # one-shot
  python nexus_cli.py status       # system status
"""

import argparse
import json
import sys
import urllib.request
import urllib.error

from rich.console import Console
from rich.prompt import Prompt

console = Console()
DEFAULT_API = "http://127.0.0.1:8765"


def api_get(path: str, base: str = DEFAULT_API) -> dict:
    with urllib.request.urlopen(f"{base}{path}", timeout=10) as resp:
        return json.loads(resp.read())


def api_post(path: str, data: dict, base: str = DEFAULT_API) -> dict:
    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())


def cmd_status(base: str):
    try:
        data = api_get("/api/system/status", base)
        m = data["memory"]
        console.print("[bold cyan]NEXUS-01 Status[/bold cyan]")
        console.print(f"  Agents: {', '.join(data['agents'])}")
        console.print(f"  Channels: {', '.join(c['name'] for c in data['channels']) or 'none'}")
        console.print(f"  Memory: {m['conversations']} convs, {m['sessions']} sessions, {m['projects']} projects")
        for p in data.get("llm_providers", []):
            status = "online" if p["available"] else "offline"
            console.print(f"  LLM {p['name']}: {status}")
    except urllib.error.URLError:
        console.print("[red]NEXUS-01 not running. Start with: python main.py[/red]")
        sys.exit(1)


def cmd_chat(text: str, base: str, session_id: str | None = None):
    try:
        result = api_post("/api/chat", {"text": text, "session_id": session_id}, base)
        if result.get("route"):
            console.print(f"[dim]Route: {' → '.join(result['route'])}[/dim]")
        console.print(result["text"])
        if result.get("requires_approval"):
            answer = Prompt.ask("[yellow]Approve? (yes/no)[/yellow]")
            approved = answer.lower() in {"yes", "y"}
            result = api_post("/api/chat/approve", {
                "approval_id": result["approval_id"],
                "approved": approved,
                "session_id": result.get("session_id", "web"),
            }, base)
            console.print(result["text"])
    except urllib.error.URLError:
        console.print("[red]API unreachable. Run: python main.py[/red]")
        sys.exit(1)


def cmd_repl(base: str):
    session_id = None
    console.print(f"[cyan]NEXUS-01 CLI[/cyan] (API: {base}) — type exit to quit\n")
    while True:
        try:
            text = Prompt.ask("[green]nexus[/green]")
        except (EOFError, KeyboardInterrupt):
            break
        if text.strip().lower() in ("exit", "quit"):
            break
        if not text.strip():
            continue
        try:
            result = api_post("/api/chat", {"text": text, "session_id": session_id}, base)
            session_id = result.get("session_id")
            if result.get("route"):
                console.print(f"[dim]{' → '.join(result['route'])}[/dim]")
            console.print(result["text"])
            if result.get("requires_approval"):
                answer = Prompt.ask("[yellow]Approve?[/yellow]")
                result = api_post("/api/chat/approve", {
                    "approval_id": result["approval_id"],
                    "approved": answer.lower() in {"yes", "y"},
                    "session_id": session_id,
                }, base)
                console.print(result["text"])
        except urllib.error.URLError:
            console.print("[red]Lost connection to NEXUS-01[/red]")
            break
        console.print()


def main():
    parser = argparse.ArgumentParser(prog="nexus", description="NEXUS-01 terminal client")
    parser.add_argument("--api", default=DEFAULT_API, help="API base URL")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="System status")
    chat_p = sub.add_parser("chat", help="Send one message")
    chat_p.add_argument("text", help="Message text")

    args = parser.parse_args()
    if args.command == "status":
        cmd_status(args.api)
    elif args.command == "chat":
        cmd_chat(args.text, args.api)
    else:
        cmd_repl(args.api)


if __name__ == "__main__":
    main()

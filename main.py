#!/usr/bin/env python3
"""NEXUS-01 — Agentic AI OS entry point."""

import argparse
import asyncio
import logging
import signal

from rich.console import Console
from rich.prompt import Prompt

from config import config
from core.app import create_app, start_services
from core.structured_logging import setup_logging
from gateway.types import ChannelKind, InboundMessage

console = Console()
running = True


def _shutdown(sig, frame):
    global running
    running = False


async def _run_cli(app):
    global running
    while running:
        try:
            user_input = await asyncio.get_event_loop().run_in_executor(
                None, lambda: Prompt.ask("[bold green]nexus[/bold green]")
            )
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input.strip():
            continue
        if user_input.strip().lower() in ("exit", "quit"):
            running = False
            break
        if user_input.strip().lower() == "help":
            console.print("[bold]Commands:[/bold] osint, exec, analyst, natural language, help, exit")
            continue

        response = await app.gateway.handle(InboundMessage(
            channel=ChannelKind.CLI, session_id="terminal", text=user_input, user_id="local",
        ))
        if response.requires_approval:
            answer = await asyncio.get_event_loop().run_in_executor(
                None, lambda: Prompt.ask("[yellow]Approve exec? (yes/no)[/yellow]")
            )
            approved = answer.strip().lower() in {"yes", "y"}
            response = await app.gateway.handle(InboundMessage(
                channel=ChannelKind.CLI, session_id="terminal", text=answer, user_id="local",
                metadata={"approval_decision": approved, "approval_id": response.approval_id},
            ))
        route = " → ".join(response.route) if response.route else ""
        if route:
            console.print(f"[dim]Route: {route}[/dim]")
        console.print(f"[cyan]{response.text}[/cyan]\n")


async def main():
    parser = argparse.ArgumentParser(description="NEXUS-01 Agentic AI OS")
    parser.add_argument("--no-cli", action="store_true", help="Run without terminal (API + channels only)")
    parser.add_argument("--no-web", action="store_true", help="Disable web dashboard")
    parser.add_argument("--port", type=int, default=None, help="API port (default 8765)")
    parser.add_argument("--json-logs", action="store_true", help="Output structured JSON logs")
    args = parser.parse_args()

    json_logs = args.json_logs or config.structured_log_json
    setup_logging(level="INFO", json_output=json_logs)

    if args.no_web:
        config.enable_web_ui = False
    if args.port:
        config.api_port = args.port
    if args.no_cli:
        config.enable_cli = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    console.print("[bold cyan]NEXUS-01 Agentic OS[/bold cyan]")
    app = await create_app(config)
    await start_services(app, config)

    channels = ", ".join(c.name for c in app.channels) or "none"
    console.print(f"[green]Channels:[/green] {channels}")
    if config.enable_web_ui:
        console.print(f"[green]Dashboard:[/green] http://127.0.0.1:{config.api_port}")
    console.print(f"[green]LLM:[/green] {config.ollama_model} (router: Ollama → cloud fallback)")
    if json_logs:
        console.print(f"[green]Logging:[/green] structured JSON")

    try:
        if config.enable_cli and not args.no_cli:
            console.print("Terminal ready. Type 'help' or 'exit'.\n")
            await _run_cli(app)
        else:
            console.print("Running headless. Ctrl+C to stop.")
            while running:
                await asyncio.sleep(1)
    finally:
        await app.shutdown()
        console.print("[green]NEXUS-01 shutdown complete.[/green]")


if __name__ == "__main__":
    asyncio.run(main())

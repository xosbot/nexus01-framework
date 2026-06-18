import asyncio
import signal
import sys
from rich.console import Console
from rich.prompt import Prompt
from config import config
from core.bus import Message, MessageBus, bus
from core.llm import OllamaClient
from core.memory import Memory
from core.cold_mode import ColdMode
from agents.osint import OSINTAgent
from agents.executor import ExecutorAgent
from agents.analyst import AnalystAgent

console = Console()
running = True

def shutdown(sig, frame):
    global running
    console.print("\n[yellow]Shutting down...[/yellow]")
    running = False

async def main():
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    console.print("[bold cyan]NEXUS-01 Framework[/bold cyan]")
    console.print("Initializing components...")

    llm = OllamaClient(config.ollama_url, config.ollama_model)
    memory = Memory(config.database_path, config.chroma_path)
    cold_mode = ColdMode(config.cold_mode_enabled)

    osint = OSINTAgent(llm, memory)
    executor = ExecutorAgent(llm, memory, cold_mode)
    analyst = AnalystAgent(llm, memory)

    for agent in [osint, executor, analyst]:
        agent.set_bus(bus)

    console.print(f"[green]Agents ready: osint, executor, analyst[/green]")
    console.print(f"LLM: {config.ollama_model} @ {config.ollama_url}")
    console.print("Type 'help' for commands, 'exit' to quit.\n")

    if config.telegram_token:
        console.print("[cyan]Telegram bot enabled[/cyan]")

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
            break

        if user_input.strip().lower() == "help":
            console.print("[bold]Commands:[/bold]")
            console.print("  osint <query>    - Run OSINT search")
            console.print("  exec <cmd>       - Execute a command")
            console.print("  analyst <data>   - Analyze data")
            console.print("  help             - Show this help")
            console.print("  exit             - Quit")
            continue

        parts = user_input.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        msg = Message(sender="cli", recipient="", type="task", payload={"task": args, "query": args})

        if cmd == "osint":
            msg.recipient = "osint"
            result = await osint.on_message(msg)
            console.print(f"\n[bold cyan]OSINT Report:[/bold cyan]\n{result.get('analysis', 'No analysis')}\n")
        elif cmd == "exec":
            msg.recipient = "executor"
            msg.payload["action"] = "run_command"
            msg.payload["params"] = {"cmd": args}
            result = await executor.on_message(msg)
            console.print(f"\n[bold cyan]Command Result:[/bold cyan]\n{result.get('stdout', result.get('error', 'No output'))}\n")
        elif cmd == "analyst":
            msg.recipient = "analyst"
            msg.payload["data"] = {"input": args}
            result = await analyst.on_message(msg)
            console.print(f"\n[bold cyan]Analysis:[/bold cyan]\n{result.get('analysis', 'No analysis')}\n")
        else:
            console.print(f"[red]Unknown command: {cmd}. Type 'help' for available commands.[/red]")

    await llm.close()
    console.print("[green]Goodbye.[/green]")

if __name__ == "__main__":
    asyncio.run(main())

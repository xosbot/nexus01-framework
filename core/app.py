import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from config import Config, config
from core.bus_factory import create_bus, set_global_bus
from core.cold_mode import ColdMode
from core.cost_tracker import CostTracker
from core.llm_client import NexusLLM
from core.memory import Memory
from core.rag import RAGStore
from core.tool_registry import ToolRegistry
from core.agent_loop import AgentLoop
from agents.osint import OSINTAgent
from agents.executor import ExecutorAgent
from agents.analyst import AnalystAgent
from agents.orchestrator import OrchestratorAgent
from gateway.gateway import NexusGateway
from gateway.channels.telegram import TelegramChannel
from gateway.channels.whatsapp import WhatsAppChannel
from gateway.channels.discord_channel import DiscordChannel
from gateway.channels.slack import SlackChannel
from gateway.channels.signal import SignalChannel
from gateway.channels.teams import TeamsChannel

logger = logging.getLogger(__name__)


@dataclass
class NexusApp:
    llm: NexusLLM
    memory: Memory
    rag: RAGStore
    gateway: NexusGateway
    channels: list
    bus: object
    cost_tracker: CostTracker
    api_app: object | None
    _channel_tasks: list
    _api_server: object | None

    async def shutdown(self) -> None:
        for channel in self.channels:
            try:
                await channel.stop()
            except Exception as exc:
                logger.warning("Channel stop error: %s", exc)
        if self._api_server:
            self._api_server.should_exit = True
        if hasattr(self.bus, "disconnect"):
            await self.bus.disconnect()
        await self.llm.close()


def _parse_allowlist(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [v.strip() for v in str(value).split(",") if v.strip()]


def _build_orchestrator_tools(rag: RAGStore, app_bus) -> ToolRegistry:
    from core.bus import Message

    registry = ToolRegistry()

    async def search_knowledge(query: str) -> str:
        hits = rag.search(query, n=5)
        if not hits:
            return "No relevant knowledge found."
        return "\n\n".join(f"[{h['metadata'].get('source', '?')}]\n{h['content']}" for h in hits)

    async def ask_osint(query: str) -> str:
        reply = await app_bus.request(Message(
            sender="react_loop", recipient="osint", type="task",
            payload={"task": query, "query": query},
        ))
        if reply.type == "error":
            return f"OSINT error: {reply.payload.get('error')}"
        data = reply.payload.get("data", {})
        return data.get("analysis", str(data))

    async def ask_analyst(data: str) -> str:
        reply = await app_bus.request(Message(
            sender="react_loop", recipient="analyst", type="task",
            payload={"data": {"input": data}, "query": "analysis"},
        ))
        if reply.type == "error":
            return f"Analyst error: {reply.payload.get('error')}"
        result = reply.payload.get("data", {})
        return result.get("analysis", str(result))

    from tools.browser import browser_navigate, browser_scrape, browser_interact, browser_screenshot

    registry.register(search_knowledge, description="Search tradecraft knowledge base for relevant context")
    registry.register(ask_osint, description="Delegate OSINT web research to the OSINT agent")
    registry.register(ask_analyst, description="Delegate data analysis to the Analyst agent")
    registry.register(browser_navigate, description="Navigate to a URL with full JS rendering and extract text content")
    registry.register(browser_scrape, description="Extract text from a URL using a CSS selector")
    registry.register(browser_interact, description="Navigate a URL, perform actions (click, fill, scroll), and extract content")
    registry.register(browser_screenshot, description="Capture a screenshot of a webpage")
    return registry


async def create_app(cfg: Config | None = None) -> NexusApp:
    cfg = cfg or config

    msg_bus = await create_bus(cfg.bus_backend, cfg.redis_url)
    set_global_bus(msg_bus)

    cost_tracker = CostTracker(cfg.database_path)
    llm = NexusLLM(cfg.ollama_url, cfg.ollama_model, cost_tracker=cost_tracker)
    memory = Memory(cfg.database_path, cfg.chroma_path)
    cold_mode = ColdMode(cfg.cold_mode_enabled)

    rag = RAGStore(
        chroma_path=cfg.chroma_path,
        supabase_url=cfg.supabase_url,
        supabase_key=cfg.supabase_key,
    )

    if cfg.auto_ingest_docs and cfg.rag_enabled:
        docs_dir = Path(cfg.docs_path)
        if docs_dir.exists():
            stats = rag.ingest_directory(docs_dir, "**/*.md")
            if stats["chunks"]:
                logger.info("RAG: ingested %d chunks from %d docs", stats["chunks"], stats["files"])

    tools = _build_orchestrator_tools(rag, msg_bus)
    agent_loop = AgentLoop(llm.router, tools, memory) if cfg.use_react_loop else None

    sandbox = None
    if cfg.executor_sandbox_enabled:
        from core.sandbox import DockerSandbox
        sandbox = DockerSandbox()
        if not sandbox.is_available():
            logger.warning("Docker sandbox requested but Docker not available — falling back to host exec")
            sandbox = None
        else:
            logger.info("Docker sandbox enabled for executor agent")

    osint = OSINTAgent(llm, memory, rag)
    executor = ExecutorAgent(llm, memory, cold_mode, rag, sandbox=sandbox)
    analyst = AnalystAgent(llm, memory, rag)
    orchestrator = OrchestratorAgent(llm, memory, rag, agent_loop)

    for agent in [osint, executor, analyst, orchestrator]:
        agent.set_bus(msg_bus)

    allowed_users = {
        "telegram": _parse_allowlist(cfg.telegram_allowed_users),
        "whatsapp": _parse_allowlist(cfg.whatsapp_allowed_numbers),
        "discord": _parse_allowlist(cfg.discord_allowed_users),
        "slack": _parse_allowlist(cfg.slack_allowed_users),
        "signal": _parse_allowlist(cfg.signal_allowed_numbers),
        "teams": _parse_allowlist(cfg.teams_allowed_users),
    }

    gateway = NexusGateway(
        bus=msg_bus,
        allowed_users=allowed_users,
        require_approval_for_exec=cfg.require_approval_for_exec,
    )

    channels = []
    enabled = {c.lower() for c in cfg.enabled_channels}

    if "telegram" in enabled and cfg.telegram_token:
        tg = TelegramChannel(gateway, cfg.telegram_token)
        gateway.register_channel(tg)
        channels.append(tg)

    if "whatsapp" in enabled and cfg.whatsapp_token and cfg.whatsapp_phone_number_id:
        wa = WhatsAppChannel(gateway, cfg.whatsapp_token, cfg.whatsapp_phone_number_id, cfg.whatsapp_verify_token)
        gateway.register_channel(wa)
        channels.append(wa)

    if "discord" in enabled and cfg.discord_token:
        dc = DiscordChannel(gateway, cfg.discord_token)
        gateway.register_channel(dc)
        channels.append(dc)

    if "slack" in enabled and cfg.slack_bot_token and cfg.slack_signing_secret:
        sl = SlackChannel(gateway, cfg.slack_bot_token, cfg.slack_signing_secret)
        gateway.register_channel(sl)
        channels.append(sl)

    if "signal" in enabled and cfg.signal_account:
        sig = SignalChannel(gateway, cfg.signal_api_url, cfg.signal_account)
        gateway.register_channel(sig)
        channels.append(sig)

    if "teams" in enabled and cfg.teams_app_id and cfg.teams_app_password:
        tm = TeamsChannel(gateway, cfg.teams_app_id, cfg.teams_app_password)
        gateway.register_channel(tm)
        channels.append(tm)

    nexus = NexusApp(
        llm=llm,
        memory=memory,
        rag=rag,
        gateway=gateway,
        channels=channels,
        bus=msg_bus,
        cost_tracker=cost_tracker,
        api_app=None,
        _channel_tasks=[],
        _api_server=None,
    )

    from core.brain import IVABrain
    from core.copilot import ExecutionCopilot
    from core.integrations import IntegrationHub
    from core.proactive import ProactiveIntelligence

    nexus.brain = IVABrain(nexus.memory, nexus.rag)
    nexus.copilot = ExecutionCopilot(nexus.memory, nexus.rag, {})
    nexus.integrations = IntegrationHub(nexus.memory, nexus.brain)
    nexus.proactive = ProactiveIntelligence(nexus.memory, nexus.brain)

    if cfg.enable_web_ui:
        from api.server import create_api_app
        nexus.api_app = create_api_app(nexus)

    return nexus


async def start_services(app: NexusApp, cfg: Config | None = None) -> None:
    cfg = cfg or config
    for channel in app.channels:
        if channel.name == "discord":
            app._channel_tasks.append(asyncio.create_task(channel.start()))
        else:
            await channel.start()

    if app.api_app and cfg.enable_web_ui:
        import uvicorn
        uvi_config = uvicorn.Config(app.api_app, host=cfg.api_host, port=cfg.api_port, log_level="info")
        app._api_server = uvicorn.Server(uvi_config)
        app._channel_tasks.append(asyncio.create_task(app._api_server.serve()))
        logger.info("NEXUS-01 OS dashboard: http://%s:%s", cfg.api_host, cfg.api_port)

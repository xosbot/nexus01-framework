import re
from agents.base import BaseAgent
from core.bus import Message
from config import config

CHAIN_PATTERNS = [
    (re.compile(r"\b(research|investigate|osint|intel)\b.*\b(analyz|analyse|assess|risk)\b", re.I), ["osint", "analyst"]),
    (re.compile(r"\b(research|investigate|osint|intel)\b.*\b(run|exec|deploy|install)\b", re.I), ["osint", "analyst", "executor"]),
]


class OrchestratorAgent(BaseAgent):
    """Routes requests to specialist agents or runs ReAct loop for complex queries."""

    DIRECT_COMMANDS = {
        "osint": "osint",
        "exec": "executor",
        "analyst": "analyst",
        "analyze": "analyst",
    }

    def __init__(self, llm, memory, rag=None, agent_loop=None):
        super().__init__("orchestrator", llm, memory, rag)
        self._agent_loop = agent_loop

    async def on_message(self, message: Message) -> dict:
        text = message.payload.get("text", message.payload.get("task", "")).strip()
        if not text:
            return {"status": "error", "error": "Empty request"}

        session_id = message.payload.get("session_id", "")

        if self._agent_loop and config.use_react_loop and self._is_complex_query(text):
            result = await self._agent_loop.run(text, session_id=session_id, agent=self.name)
            return {"status": "complete", "route": ["react_loop"], "output": result, "steps": []}

        route = self._resolve_route(text, message.payload)
        agents = route["agents"]
        args = route["args"]
        results: list[dict] = []
        prior_context = ""

        for agent_name in agents:
            payload = dict(message.payload)
            payload["task"] = args
            payload["query"] = args
            payload["_prior_context"] = prior_context
            payload["session_id"] = session_id

            if agent_name == "executor":
                payload["action"] = "run_command"
                payload["params"] = {"cmd": args}
                payload["permission"] = message.payload.get("permission", "EXECUTE")
            elif agent_name == "analyst":
                payload["data"] = {"input": args, "prior": prior_context or None}

            agent_msg = Message(sender="orchestrator", recipient=agent_name, type="task", payload=payload)
            reply = await self._bus.request(agent_msg)

            if reply.type == "error":
                return {"status": "error", "agent": agent_name, "error": reply.payload.get("error")}

            step_result = reply.payload.get("data", {})
            results.append({"agent": agent_name, "result": step_result})
            prior_context = self._summarize_step(step_result)

        return {"status": "complete", "route": agents, "steps": results, "output": prior_context}

    def _is_complex_query(self, text: str) -> bool:
        parts = text.split(maxsplit=1)
        if parts[0].lower() in self.DIRECT_COMMANDS:
            return False
        return len(text.split()) > 8 or any(p.search(text) for p, _ in CHAIN_PATTERNS)

    def _resolve_route(self, text: str, payload: dict) -> dict:
        explicit = payload.get("target_agent")
        if explicit:
            return {"agents": [explicit], "args": text}

        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else text

        if cmd in self.DIRECT_COMMANDS:
            return {"agents": [self.DIRECT_COMMANDS[cmd]], "args": args}

        for pattern, chain in CHAIN_PATTERNS:
            if pattern.search(text):
                return {"agents": chain, "args": text}

        if re.search(r"\b(osint|research|investigate|scrape|search)\b", text, re.I):
            return {"agents": ["osint"], "args": text}
        if re.search(r"\b(analyz|analyse|pattern|anomaly|report)\b", text, re.I):
            return {"agents": ["analyst"], "args": text}
        if re.search(r"\b(exec|run|command|shell|deploy)\b", text, re.I):
            return {"agents": ["executor"], "args": text}

        return {"agents": ["osint"], "args": text}

    @staticmethod
    def _summarize_step(result: dict) -> str:
        if isinstance(result, dict):
            for key in ("analysis", "stdout", "output"):
                if result.get(key):
                    return str(result[key])[:2000]
            return str(result)[:2000]
        return str(result)[:2000]

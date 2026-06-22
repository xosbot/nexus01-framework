"""Orchestrator agent — intelligent routing with decision frameworks."""

from __future__ import annotations

import re
from agents.base import BaseAgent
from core.bus import Message
from config import config

# ── Intent Classification Patterns ──────────────────────────────────────────

INTENT_PATTERNS = {
    "osint_investigate": [
        r"\b(research|investigate|osint|intel|recon|spy|surveillance)\b",
        r"\b(who is|find|look up|check|scan|enumerate)\b.*\b(user|person|account|profile)\b",
        r"\b(username|email|domain|ip|phone)\b.*\b(check|scan|search|find)\b",
        r"\b(breach|exposed|leak|compromised)\b",
        r"\b(dark.?web|onion|tor)\b",
    ],
    "osint_username": [
        r"\bcheck\s+username\b",
        r"\busername\s+enumerat\b",
        r"\bscan\s+username\b",
        r"\bfind\s+user(?:name)?\b",
        r"\blook\s+up\s+user(?:name)?\b",
    ],
    "osint_domain": [
        r"\b(recon|reconnaissance)\b.*\b(domain|site|website)\b",
        r"\b(domain|subdomain|dns)\b.*\b(scan|check|search|enum)\b",
        r"\bwhois\b",
        r"\bcertificate\b.*\b(transparency|log)\b",
    ],
    "osint_email": [
        r"\bcheck\s+email\b",
        r"\bemail\s+(?:enum|verif|check|search)\b",
        r"\bis\s+email\b.*\b(valid|real|exist)\b",
        r"\bbreach\s+check\b",
        r"\bhaveibeenpwned\b",
    ],
    "analysis": [
        r"\b(analyz|analyse|pattern|anomaly|insight|trend)\b",
        r"\b(summariz|summarise|explain|describe|overview)\b",
        r"\b(compare|contrast|evaluate|assess|review)\b",
        r"\b(report|summary|brief|digest)\b",
    ],
    "execution": [
        r"\b(exec|run|command|shell|deploy|install|build)\b",
        r"\b(create|write|generate|produce)\b.*\b(file|script|code)\b",
        r"\b(install|setup|configure|provision)\b",
        r"\b(docker|container|sandbox)\b",
    ],
    "general": [
        r"\b(what|who|where|when|why|how)\b",
        r"\b(help|assist|guide|explain)\b",
        r"\b(question|query|ask)\b",
    ],
}

# ── Chain Patterns (multi-agent workflows) ─────────────────────────────────

CHAIN_PATTERNS = [
    (re.compile(r"\b(research|investigate|osint|intel)\b.*\b(analyz|analyse|assess|risk)\b", re.I), ["osint", "analyst"]),
    (re.compile(r"\b(research|investigate|osint|intel)\b.*\b(run|exec|deploy|install)\b", re.I), ["osint", "analyst", "executor"]),
    (re.compile(r"\b(scan|check|enumerate)\b.*\b(report|summary|document)\b", re.I), ["osint", "analyst"]),
    (re.compile(r"\b(data|dataset|csv|json)\b.*\b(analyz|visualiz|chart|graph)\b", re.I), ["analyst"]),
]


class OrchestratorAgent(BaseAgent):
    """Routes requests to specialist agents with intelligent classification."""

    DIRECT_COMMANDS = {
        "osint": "osint",
        "exec": "executor",
        "analyze": "analyst",
        "analyst": "analyst",
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

        intent = self._classify_intent(text)
        intent_to_agent = {
            "osint_investigate": "osint",
            "osint_username": "osint",
            "osint_domain": "osint",
            "osint_email": "osint",
            "analysis": "analyst",
            "execution": "executor",
            "general": "analyst",
        }

        agent = intent_to_agent.get(intent, "analyst")
        return {"agents": [agent], "args": text}

    def _classify_intent(self, text: str) -> str:
        text_lower = text.lower()
        scores: dict[str, int] = {}

        for intent, patterns in INTENT_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, text_lower, re.I):
                    score += 1
            if score > 0:
                scores[intent] = score

        if not scores:
            return "general"

        return max(scores, key=scores.get)

    @staticmethod
    def _summarize_step(result: dict) -> str:
        if isinstance(result, dict):
            for key in ("analysis", "stdout", "output", "summary"):
                if result.get(key):
                    return str(result[key])[:2000]
            return str(result)[:2000]
        return str(result)[:2000]

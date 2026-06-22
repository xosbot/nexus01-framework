"""IVA Execution Copilot — Multi-step workflow engine.

Inspired by OpenClaw but more powerful. IVA can:
- Execute complex, multi-step workflows
- Chain commands and tools
- Learn from patterns
- Handle failures gracefully
"""

from __future__ import annotations

import asyncio
import json
import time
import logging
from datetime import datetime, timezone
from typing import Any, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_APPROVAL = "waiting_approval"


@dataclass
class WorkflowStep:
    id: str
    name: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str | None = None
    requires_approval: bool = False
    timeout: int = 300
    retries: int = 0
    max_retries: int = 3

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "action": self.action,
            "params": self.params,
            "status": self.status.value,
            "result": str(self.result)[:500] if self.result else None,
            "error": self.error,
            "requires_approval": self.requires_approval,
        }


@dataclass
class Workflow:
    id: str
    name: str
    description: str
    steps: list[WorkflowStep] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    result: Any = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "result": str(self.result)[:1000] if self.result else None,
        }


class ExecutionCopilot:
    """IVA's execution engine — handles multi-step workflows."""

    def __init__(self, memory, rag, agents):
        self.memory = memory
        self.rag = rag
        self.agents = agents
        self.workflows: dict[str, Workflow] = {}
        self.patterns: list[dict] = []
        self._handlers: dict[str, Callable] = {}
        self._register_handlers()
        self._load_patterns()

    def _register_handlers(self) -> None:
        self._handlers = {
            "osint": self._handle_osint,
            "analyze": self._handle_analyze,
            "execute": self._handle_execute,
            "search": self._handle_search,
            "web_recon": self._handle_web_recon,
            "domain_recon": self._handle_domain_recon,
            "port_scan": self._handle_port_scan,
            "report": self._handle_report,
            "chain": self._handle_chain,
        }

    def _load_patterns(self) -> None:
        try:
            knowledge = self.memory.list_knowledge(limit=1000)
            for item in knowledge:
                if "workflow_pattern" in item.get("key", ""):
                    value = item.get("value", "")
                    if isinstance(value, str):
                        parsed = json.loads(value)
                        if isinstance(parsed, list):
                            self.patterns.extend(parsed)
        except Exception as e:
            logger.warning("Pattern load failed: %s", e)

    async def execute_workflow(self, workflow: Workflow,
                                callback: Callable = None) -> Workflow:
        workflow.status = "running"
        logger.info(f"Starting workflow: {workflow.name}")

        step_index = 0
        while step_index < len(workflow.steps):
            step = workflow.steps[step_index]

            if workflow.status == "cancelled":
                break

            if step.status == StepStatus.COMPLETED or step.status == StepStatus.SKIPPED:
                step_index += 1
                continue

            step.status = StepStatus.RUNNING
            logger.info(f"  Step [{step_index+1}/{len(workflow.steps)}]: {step.name}")

            if step.requires_approval:
                step.status = StepStatus.WAITING_APPROVAL
                if callback:
                    await callback("approval_required", step)
                step_index += 1
                continue

            try:
                resolved_params = self._substitute_templates(step.params, workflow.context)
                step.params = resolved_params
                result = await self._execute_step(step, workflow.context)
                step.result = result
                step.status = StepStatus.COMPLETED
                workflow.context[f"step_{step.id}_result"] = result
                workflow.context["data"] = workflow.context.get("data", {})
                if isinstance(result, dict):
                    workflow.context["data"].update(result)
                if callback:
                    await callback("step_completed", step)
                step_index += 1
            except Exception as e:
                step.error = str(e)
                logger.error(f"  Step failed: {step.name} — {e}")
                if step.retries < step.max_retries:
                    step.retries += 1
                    step.status = StepStatus.PENDING
                    await asyncio.sleep(1)
                    continue
                step.status = StepStatus.FAILED
                if callback:
                    await callback("step_failed", step)
                step_index += 1

        all_completed = all(s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in workflow.steps)
        any_failed = any(s.status == StepStatus.FAILED for s in workflow.steps)
        workflow.status = "completed" if all_completed else ("failed" if any_failed else "partial")
        workflow.completed_at = datetime.now(timezone.utc).isoformat()
        workflow.result = self._aggregate_results(workflow)

        if workflow.status == "completed":
            self._learn_pattern(workflow)

        return workflow

    def _substitute_templates(self, params: dict, context: dict) -> dict:
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
                ref = value[1:-1]
                if ref in context:
                    resolved[key] = context[ref]
                elif ref.startswith("step_"):
                    resolved[key] = context.get(ref, value)
                else:
                    resolved[key] = value
            elif isinstance(value, dict):
                resolved[key] = self._substitute_templates(value, context)
            else:
                resolved[key] = value
        return resolved

    async def _execute_step(self, step: WorkflowStep,
                             context: dict) -> Any:
        handler = self._handlers.get(step.action)
        if not handler:
            raise ValueError(f"Unknown action: {step.action}")

        try:
            return await asyncio.wait_for(
                handler(step.params, context),
                timeout=step.timeout,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"Step timed out after {step.timeout}s")

    async def _handle_osint(self, params: dict, context: dict) -> dict:
        agent = self.agents.get("osint")
        if not agent:
            return {"error": "OSINT agent not available"}
        target = params.get("target", "")
        task = params.get("task", "recon")
        from core.bus import Message
        msg = Message(
            sender="copilot",
            recipient="osint",
            type="task",
            payload={"task": task, "target": target},
        )
        response = await agent.on_message(msg)
        return response if isinstance(response, dict) else {"result": str(response)}

    async def _handle_analyze(self, params: dict, context: dict) -> dict:
        agent = self.agents.get("analyst")
        if not agent:
            return {"error": "Analyst agent not available"}
        from core.bus import Message
        msg = Message(
            sender="copilot",
            recipient="analyst",
            type="task",
            payload=params,
        )
        response = await agent.on_message(msg)
        return response if isinstance(response, dict) else {"result": str(response)}

    async def _handle_execute(self, params: dict, context: dict) -> dict:
        agent = self.agents.get("executor")
        if not agent:
            return {"error": "Executor agent not available"}
        from core.bus import Message
        msg = Message(
            sender="copilot",
            recipient="executor",
            type="task",
            payload=params,
        )
        response = await agent.on_message(msg)
        return response if isinstance(response, dict) else {"result": str(response)}

    async def _handle_search(self, params: dict, context: dict) -> list:
        query = params.get("query", "")
        results = self.rag.search(query, n=params.get("limit", 5))
        return results

    async def _handle_web_recon(self, params: dict, context: dict) -> dict:
        target = params.get("target", "")
        results = {}
        whois = self.rag.search(f"whois {target}", n=1)
        if whois:
            results["whois"] = whois[0].get("content", "")
        subdomains = self.rag.search(f"subdomains {target}", n=5)
        if subdomains:
            results["subdomains"] = [s.get("content", "") for s in subdomains]
        return results

    async def _handle_domain_recon(self, params: dict, context: dict) -> dict:
        domain = params.get("domain", "")
        return await self._handle_web_recon({"target": domain}, context)

    async def _handle_port_scan(self, params: dict, context: dict) -> dict:
        target = params.get("target", "")
        agent = self.agents.get("executor")
        if agent:
            from core.bus import Message
            msg = Message(
                sender="copilot",
                recipient="executor",
                type="task",
                payload={"command": f"nmap -sV {target}", "timeout": 120},
            )
            return await agent.on_message(msg)
        return {"error": "Executor not available"}

    async def _handle_report(self, params: dict, context: dict) -> dict:
        template = params.get("template", "intel_report")
        data = context.get("data", {})
        return {
            "template": template,
            "data": data,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _handle_chain(self, params: dict, context: dict) -> dict:
        steps = params.get("steps", [])
        results = []
        for step_def in steps:
            action = step_def.get("action", "")
            handler = self._handlers.get(action)
            if handler:
                try:
                    result = await handler(step_def.get("params", {}), context)
                    results.append({"action": action, "result": result})
                except Exception as e:
                    results.append({"action": action, "error": str(e)})
        return {"chain_results": results}

    def _aggregate_results(self, workflow: Workflow) -> dict:
        results = {}
        for step in workflow.steps:
            if step.status == StepStatus.COMPLETED and step.result:
                results[step.id] = step.result
        return results

    def _learn_pattern(self, workflow: Workflow) -> None:
        if workflow.status != "completed":
            return
        pattern = {
            "name": workflow.name,
            "actions": [s.action for s in workflow.steps],
            "params": [s.params for s in workflow.steps],
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.patterns.append(pattern)
        if len(self.patterns) > 100:
            self.patterns = self.patterns[-100:]
        try:
            self.memory.save_knowledge(
                f"workflow_pattern_{int(time.time())}",
                json.dumps(pattern),
                {"type": "pattern", "name": workflow.name}
            )
        except Exception as e:
            logger.warning("Pattern save failed: %s", e)

    def create_workflow(self, name: str, steps: list[dict],
                        description: str = "") -> Workflow:
        wf = Workflow(
            id=f"wf_{int(time.time())}",
            name=name,
            description=description,
            steps=[
                WorkflowStep(
                    id=f"step_{i}",
                    name=s.get("name", f"Step {i+1}"),
                    action=s.get("action", ""),
                    params=s.get("params", {}),
                    requires_approval=s.get("requires_approval", False),
                    timeout=s.get("timeout", 300),
                )
                for i, s in enumerate(steps)
            ],
        )
        self.workflows[wf.id] = wf
        return wf

    def get_workflow(self, workflow_id: str) -> Workflow | None:
        return self.workflows.get(workflow_id)

    def list_workflows(self) -> list[dict]:
        return [w.to_dict() for w in self.workflows.values()]

    def suggest_workflow(self, intent: str) -> list[dict]:
        suggestions = []
        intent_lower = intent.lower()

        if any(w in intent_lower for w in ["domain", "website", "site"]):
            suggestions.append({
                "name": "Domain Reconnaissance",
                "description": "Full domain analysis including WHOIS, subdomains, and DNS",
                "steps": [
                    {"name": "WHOIS Lookup", "action": "domain_recon", "params": {"domain": "{target}"}},
                    {"name": "Analyze Results", "action": "analyze", "params": {"data": "{step_0_result}"}},
                ],
            })

        if any(w in intent_lower for w in ["scan", "port", "vulnerability"]):
            suggestions.append({
                "name": "Port Scan & Analysis",
                "description": "Scan target for open ports and analyze services",
                "steps": [
                    {"name": "Port Scan", "action": "port_scan", "params": {"target": "{target}"}},
                    {"name": "Analyze Findings", "action": "analyze", "params": {"data": "{step_0_result}"}},
                ],
            })

        if any(w in intent_lower for w in ["intel", "intelligence", "report"]):
            suggestions.append({
                "name": "Intelligence Report",
                "description": "Gather and analyze intelligence on target",
                "steps": [
                    {"name": "Gather Intel", "action": "osint", "params": {"target": "{target}", "task": "intel"}},
                    {"name": "Search Knowledge", "action": "search", "params": {"query": "{target}"}},
                    {"name": "Generate Report", "action": "report", "params": {"template": "intel_report"}},
                ],
            })

        return suggestions

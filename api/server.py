"""FastAPI server — IVA by NEXUS-01 OS. REST API, WebSocket chat, webhooks, static OS dashboard."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api.auth import AuthMiddleware, ws_auth
from gateway.types import ChannelKind, InboundMessage

logger = logging.getLogger(__name__)
WEB_ROOT = Path(__file__).parent.parent / "web" / "os"
ALLOWED_ORIGINS = os.getenv(
    "NEXUS_ALLOWED_ORIGINS",
    "https://navos.space,https://navos.online,http://localhost:8765",
).split(",")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    project_id: str | None = None


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class SessionCreate(BaseModel):
    title: str = "New Session"
    project_id: str | None = None
    channel: str = "web"


class ApprovalRequest(BaseModel):
    approval_id: str
    approved: bool
    session_id: str = "web"


class IngestRequest(BaseModel):
    path: str | None = None
    text: str | None = None
    url: str | None = None
    source: str = "manual"
    project_id: str | None = None


def create_api_app(nexus_app) -> FastAPI:
    app = FastAPI(title="IVA — NEXUS-01 OS", version="2.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "X-API-Key", "Content-Type"],
    )
    app.add_middleware(AuthMiddleware)
    gateway = nexus_app.gateway
    memory = nexus_app.memory
    llm = nexus_app.llm

    brain = getattr(nexus_app, 'brain', None)
    copilot = getattr(nexus_app, 'copilot', None)
    integrations = getattr(nexus_app, 'integrations', None)
    proactive = getattr(nexus_app, 'proactive', None)

    if WEB_ROOT.exists():
        app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="assets")

    @app.get("/")
    async def root():
        index = WEB_ROOT / "index.html"
        if index.exists():
            return FileResponse(index)
        return HTMLResponse("<h1>NEXUS-01</h1><p>Dashboard not found. Run from nexus01-framework.</p>")

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "nexus-os"}

    # ── System ──────────────────────────────────────────────────────────

    _start_time = __import__('time').time()

    @app.get("/api/overview")
    async def overview():
        import time as _t
        uptime_secs = int(_t.time() - _start_time)
        hours, remainder = divmod(uptime_secs, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 24:
            days, hours = divmod(hours, 24)
            uptime_str = f"{days}d {hours}h"
        elif hours > 0:
            uptime_str = f"{hours}h {minutes}m"
        else:
            uptime_str = f"{minutes}m {seconds}s"
        stats = memory.stats()
        rag_stats = nexus_app.rag.stats() if hasattr(nexus_app, "rag") else {}
        providers = llm.provider_status() if hasattr(llm, "provider_status") else []
        agent_activity = {}
        for agent_name, count in stats.get("by_agent", {}).items():
            agent_activity[agent_name] = count
        return {
            "total_sessions": stats.get("sessions", 0),
            "total_messages": stats.get("conversations", 0),
            "knowledge_count": stats.get("knowledge", 0),
            "rag_docs": rag_stats.get("documents", 0),
            "uptime": uptime_str,
            "providers": [{"name": p.get("name", ""), "available": p.get("available", False)} for p in providers],
            "agent_activity": agent_activity,
        }

    @app.get("/api/system/status")
    async def system_status():
        from config import config
        channels = [{"name": c.name, "active": True} for c in nexus_app.channels]
        return {
            "agents": ["orchestrator", "osint", "analyst", "executor"],
            "channels": channels,
            "bus_backend": config.bus_backend,
            "llm_providers": llm.provider_status() if hasattr(llm, "provider_status") else [],
            "llm_stats": llm.stats() if hasattr(llm, "stats") else {},
            "memory": memory.stats(),
            "rag": nexus_app.rag.stats() if hasattr(nexus_app, "rag") else {},
            "cold_mode": True,
            "react_loop": config.use_react_loop,
        }

    @app.get("/api/costs")
    async def costs(days: int = 30):
        return nexus_app.cost_tracker.summary(days)

    @app.get("/api/tools/status")
    async def tools_status():
        from tools.availability import get_tool_availability
        availability = get_tool_availability()
        return availability.to_dict()

    # ── Social Media ─────────────────────────────────────────────────

    social_mgr = getattr(nexus_app, 'social_media', None)

    @app.get("/api/social/adapters")
    async def list_social_adapters():
        if not social_mgr:
            return {"adapters": [], "error": "Social media manager not initialized"}
        return {"adapters": social_mgr.list_adapters()}

    @app.post("/api/social/draft")
    async def draft_social_post(request: Request):
        if not social_mgr:
            return {"error": "Social media manager not initialized"}
        data = await request.json()
        platform = data.get("platform", "")
        prompt = data.get("prompt", "")
        if not platform or not prompt:
            raise HTTPException(400, "platform and prompt are required")
        try:
            entry = await social_mgr.draft_post(platform, prompt, data.get("context"))
            return entry.to_dict()
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/social/schedule")
    async def schedule_social_post(request: Request):
        if not social_mgr:
            return {"error": "Social media manager not initialized"}
        data = await request.json()
        entry_id = data.get("entry_id", "")
        scheduled_at = data.get("scheduled_at", "")
        if not entry_id or not scheduled_at:
            raise HTTPException(400, "entry_id and scheduled_at are required")
        try:
            dt = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            entry = await social_mgr.schedule_post(entry_id, dt)
            return entry.to_dict()
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/social/publish")
    async def publish_social_post(request: Request):
        if not social_mgr:
            return {"error": "Social media manager not initialized"}
        data = await request.json()
        entry_id = data.get("entry_id", "")
        if not entry_id:
            raise HTTPException(400, "entry_id is required")
        try:
            entry = await social_mgr.publish_now(entry_id)
            return entry.to_dict()
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/social/calendar")
    async def list_social_calendar(platform: str | None = None, status: str | None = None, limit: int = 50):
        if not social_mgr:
            return {"entries": [], "error": "Social media manager not initialized"}
        entries = social_mgr.get_calendar().list_entries(platform=platform, status=status, limit=limit)
        return {"entries": [e.to_dict() for e in entries]}

    @app.get("/api/social/calendar/{entry_id}")
    async def get_social_calendar_entry(entry_id: str):
        if not social_mgr:
            raise HTTPException(404, "Social media manager not initialized")
        entry = social_mgr.get_calendar().get(entry_id)
        if not entry:
            raise HTTPException(404, "Entry not found")
        return entry.to_dict()

    @app.delete("/api/social/calendar/{entry_id}")
    async def delete_social_calendar_entry(entry_id: str):
        if not social_mgr:
            raise HTTPException(404, "Social media manager not initialized")
        if social_mgr.get_calendar().delete(entry_id):
            return {"deleted": True}
        raise HTTPException(404, "Entry not found")

    @app.get("/api/social/stats")
    async def social_stats():
        if not social_mgr:
            return {"error": "Social media manager not initialized"}
        return social_mgr.stats()

    @app.get("/api/rag/stats")
    async def rag_stats():
        return nexus_app.rag.stats()

    @app.get("/api/rag/search")
    async def rag_search(q: str, n: int = 5, project_id: str | None = None):
        return nexus_app.rag.search(q, n, project_id=project_id)

    @app.post("/api/rag/ingest")
    async def rag_ingest(req: IngestRequest):
        RESTRICTED = ["/etc", "/proc", "/sys", "/dev", "/root/.ssh"]
        if req.path:
            from pathlib import Path
            p = Path(req.path).resolve()
            for restricted in RESTRICTED:
                if str(p).startswith(restricted):
                    raise HTTPException(403, f"Access to {restricted} is restricted")
        meta = {"project_id": req.project_id} if req.project_id else {}
        if req.text:
            chunks = nexus_app.rag.ingest_text(req.text, source=req.source, metadata=meta)
        elif req.url:
            try:
                from tools.web_scraper import scrape_url
                result = await scrape_url(req.url)
                if result.get("status") == "failed":
                    raise HTTPException(400, f"Failed to fetch URL: {result.get('error', 'unknown')}")
                text = result.get("text", "")
                if not text:
                    raise HTTPException(400, "No content extracted from URL")
                chunks = nexus_app.rag.ingest_text(text, source=req.url, metadata={**meta, "url": req.url, "title": result.get("title", "")})
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(400, f"URL ingest failed: {str(e)}")
        elif req.path:
            p = Path(req.path)
            if p.is_dir():
                stats = nexus_app.rag.ingest_directory(p)
                return stats
            chunks = nexus_app.rag.ingest_file(p, source=req.source)
        else:
            raise HTTPException(400, "Provide text, url, or path")
        return {"chunks": chunks, "stats": nexus_app.rag.stats()}

    # ── Chat ────────────────────────────────────────────────────────────

    @app.post("/api/chat")
    async def chat(req: ChatRequest):
        session_id = req.session_id
        if not session_id:
            session = memory.sessions.create(title=req.message[:60], project_id=req.project_id, channel="web")
            session_id = session["id"]
        else:
            memory.sessions.touch(session_id)

        inbound = InboundMessage(
            channel=ChannelKind.WEB,
            session_id=session_id,
            text=req.message,
            user_id="web",
            metadata={"project_id": req.project_id, "session_id": session_id},
        )
        response = await gateway.handle(inbound)
        memory.save_conversation("orchestrator", "user", req.message, session_id)
        memory.save_conversation("orchestrator", "assistant", response.text, session_id)

        return {
            "session_id": session_id,
            "response": response.text,
            "route": response.route,
            "requires_approval": response.requires_approval,
            "approval_id": response.approval_id,
            "success": response.success,
        }

    @app.post("/api/chat/approve")
    async def approve(req: ApprovalRequest):
        inbound = InboundMessage(
            channel=ChannelKind.WEB,
            session_id=req.session_id,
            text="yes" if req.approved else "no",
            user_id="web",
            metadata={"approval_decision": req.approved, "approval_id": req.approval_id},
        )
        response = await gateway.handle(inbound)
        return {"text": response.text, "success": response.success}

    @app.post("/api/chat/stream")
    async def chat_stream(req: ChatRequest):
        """Server-Sent Events streaming chat. Bypasses orchestrator for low-latency conversational responses.

        Wire format: each event is `data: <json>\\n\\n`.
        Event types: `sources` (RAG citations), `chunk` (token), `command` (slash command result),
                     `done` (final metadata), `error` (failure).
        """
        from core import events as _events
        from core import slash as _slash
        from core import permissions as _permissions

        _events.emit("chat_received", req.message[:120], session_id=req.session_id or "", agent="chat_stream")

        session_id = req.session_id
        if not session_id:
            session = memory.sessions.create(title=req.message[:60], project_id=req.project_id, channel="web")
            session_id = session["id"]
        else:
            memory.sessions.touch(session_id)

        if req.message.lstrip().startswith("/"):
            ctx = {
                "llm": llm,
                "memory": memory,
                "agents": ["orchestrator", "osint", "analyst", "executor"],
                "bus_backend": "redis" if (hasattr(nexus_app, "_bus") and getattr(nexus_app._bus, "_redis", None)) else "memory",
                "cold_mode": True,
                "react_loop": True,
            }
            result = await _slash.dispatch(req.message, session_id, ctx)

            async def command_gen():
                payload = {
                    "type": "command",
                    "ok": result.ok,
                    "title": result.title,
                    "text": result.text,
                    "side_effect": result.side_effect,
                    "data": result.data or {},
                }
                yield f"data: {json.dumps(payload)}\n\n"
                memory.save_conversation("orchestrator", "user", req.message, session_id)
                memory.save_conversation("orchestrator", "assistant", result.text, session_id)
                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'content': result.text})}\n\n"

            return StreamingResponse(command_gen(), media_type="text/event-stream", headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            })

        history = memory.get_context("orchestrator", session_id=session_id)
        messages = [{"role": m["role"], "content": m["content"]} for m in history[-20:]]

        sources: list[dict] = []
        rag = getattr(nexus_app, "rag", None)
        if rag and hasattr(rag, "search"):
            try:
                hits = rag.search(req.message, n=3) or []
                for h in hits[:3]:
                    sources.append({
                        "content": (h.get("content", "") or "")[:400],
                        "source": (h.get("metadata") or {}).get("source", ""),
                        "url": (h.get("metadata") or {}).get("url", ""),
                        "title": (h.get("metadata") or {}).get("title", ""),
                        "distance": h.get("distance"),
                    })
                if sources:
                    context_block = "\n\n".join(
                        f"[{i+1}] {s['content']}" for i, s in enumerate(sources)
                    )
                    messages.insert(0, {
                        "role": "system",
                        "content": f"Use the following knowledge base excerpts to ground your answer when relevant. Cite as [1], [2], [3]:\n\n{context_block}",
                    })
            except Exception as exc:
                logger.debug("RAG context injection failed: %s", exc)

        messages.append({"role": "user", "content": req.message})

        async def event_gen():
            full_text = ""
            try:
                if sources:
                    yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
                async for token in llm.stream(messages, session_id=session_id, agent="chat_stream"):
                    if not token:
                        continue
                    full_text += token
                    yield f"data: {json.dumps({'type': 'chunk', 'content': token})}\n\n"
                memory.save_conversation("orchestrator", "user", req.message, session_id)
                memory.save_conversation("orchestrator", "assistant", full_text, session_id)
                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'content': full_text})}\n\n"
            except Exception as exc:
                _events.emit("error", f"chat_stream failed: {exc}", session_id=session_id, agent="chat_stream", level="error")
                logger.exception("Streaming chat failed")
                yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    @app.websocket("/ws")
    async def ws_chat(websocket: WebSocket):
        await websocket.accept()
        authenticated = False
        session_id = None

        if not ws_auth:
            authenticated = True

        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type", "")

                if msg_type == "auth":
                    token = data.get("api_key", "")
                    if ws_auth and not ws_auth.authenticate(token):
                        await websocket.send_json({"type": "auth_failed", "error": "Invalid API key"})
                        await websocket.close(code=4001, reason="Unauthorized")
                        return
                    authenticated = True
                    await websocket.send_json({"type": "auth_ok"})
                    continue

                if not authenticated:
                    await websocket.send_json({"type": "auth_required", "error": "Authenticate first"})
                    continue

                if msg_type == "approval_response":
                    approval_id = data.get("approval_id") or data.get("task_id", "")
                    inbound = InboundMessage(
                        channel=ChannelKind.WEB,
                        session_id=data.get("session_id", session_id or "web"),
                        text="yes" if data.get("approved") else "no",
                        user_id="web",
                        metadata={
                            "approval_decision": data.get("approved"),
                            "approval_id": approval_id,
                        },
                    )
                    await websocket.send_json({"type": "typing"})
                    response = await gateway.handle(inbound)
                    await websocket.send_json({
                        "type": "chat_response",
                        "content": response.text,
                        "route": response.route,
                        "session_id": session_id,
                    })
                    continue

                content = data.get("content") or data.get("text") or ""
                content = content.strip()
                if not content:
                    continue

                session_id = data.get("session_id") or session_id
                if not session_id:
                    s = memory.sessions.create(title=content[:60], channel="web")
                    session_id = s["id"]
                else:
                    memory.sessions.touch(session_id)

                inbound = InboundMessage(
                    channel=ChannelKind.WEB,
                    session_id=session_id,
                    text=content,
                    user_id="web",
                    metadata={"session_id": session_id},
                )

                await websocket.send_json({"type": "typing"})
                response = await gateway.handle(inbound)
                memory.save_conversation("orchestrator", "user", content, session_id)
                memory.save_conversation("orchestrator", "assistant", response.text, session_id)

                msg = {
                    "type": "chat_response",
                    "content": response.text,
                    "route": response.route,
                    "session_id": session_id,
                }
                if response.requires_approval:
                    msg["type"] = "approval_required"
                    msg["approval_id"] = response.approval_id
                    msg["description"] = response.text
                await websocket.send_json(msg)
        except WebSocketDisconnect:
            pass

    # ── Projects ──────────────────────────────────────────────────────

    @app.get("/api/projects")
    async def list_projects():
        return {"projects": memory.projects.list()}

    @app.post("/api/projects")
    async def create_project(body: ProjectCreate):
        return memory.projects.create(body.name, body.description)

    @app.get("/api/projects/{project_id}")
    async def get_project(project_id: str):
        p = memory.projects.get(project_id)
        if not p:
            raise HTTPException(404, "Project not found")
        p["sessions"] = memory.sessions.list(project_id=project_id)
        p["progress"] = memory.tasks.progress(project_id)
        p["tasks"] = memory.tasks.list(project_id=project_id)
        return p

    @app.get("/api/projects/{project_id}/tasks")
    async def list_project_tasks(project_id: str, status: str | None = None):
        return {"tasks": memory.tasks.list(project_id=project_id, status=status)}

    @app.post("/api/projects/{project_id}/tasks")
    async def create_project_task(project_id: str, request: Request):
        data = await request.json()
        title = data.get("title", "")
        if not title:
            raise HTTPException(400, "title is required")
        task = memory.tasks.create(
            project_id=project_id,
            title=title,
            description=data.get("description", ""),
            status=data.get("status", "pending"),
            metadata=data.get("metadata"),
        )
        return task

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, request: Request):
        data = await request.json()
        task = memory.tasks.update(task_id, **data)
        if not task:
            raise HTTPException(404, "Task not found")
        return task

    @app.delete("/api/tasks/{task_id}")
    async def delete_task(task_id: str):
        if not memory.tasks.delete(task_id):
            raise HTTPException(404, "Task not found")
        return {"deleted": True}

    @app.patch("/api/projects/{project_id}")
    async def update_project(project_id: str, body: ProjectUpdate):
        p = memory.projects.update(project_id, **body.model_dump(exclude_none=True))
        if not p:
            raise HTTPException(404, "Project not found")
        return p

    @app.delete("/api/projects/{project_id}")
    async def delete_project(project_id: str):
        if not memory.projects.delete(project_id):
            raise HTTPException(404, "Project not found")
        return {"deleted": True}

    # ── Sessions ──────────────────────────────────────────────────────

    @app.get("/api/sessions")
    async def list_sessions(project_id: str | None = None):
        return {"sessions": memory.sessions.list(project_id=project_id)}

    @app.post("/api/sessions")
    async def create_session(body: SessionCreate):
        return memory.sessions.create(body.title, body.project_id, body.channel)

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        s = memory.sessions.get(session_id)
        if not s:
            raise HTTPException(404, "Session not found")
        s["messages"] = memory.list_conversations(session_id=session_id)
        return s

    @app.get("/api/sessions/{session_id}/messages")
    async def get_session_messages(session_id: str):
        messages = memory.list_conversations(session_id=session_id)
        return {"messages": messages}

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        if not memory.sessions.delete(session_id):
            raise HTTPException(404, "Session not found")
        return {"deleted": True}

    # ── Memory ────────────────────────────────────────────────────────

    # ── Approvals ────────────────────────────────────────────────────

    @app.get("/api/approvals")
    async def list_approvals(include_expired: bool = False):
        pending = gateway.approvals.list_pending(include_expired=include_expired)
        return {"approvals": [a.to_dict() for a in pending]}

    @app.post("/api/approvals/{approval_id}/respond")
    async def respond_to_approval(approval_id: str, request: Request):
        data = await request.json()
        approved = data.get("approved", False)
        edited_text = data.get("edited_text")

        approval = gateway.approvals.get(approval_id)
        if not approval:
            raise HTTPException(404, "Approval not found or expired")

        gateway.approvals.clear(approval_id)

        inbound = InboundMessage(
            channel=ChannelKind.WEB,
            session_id=approval.session_id,
            text="yes" if approved else "no",
            user_id="web",
            metadata={
                "approval_decision": approved,
                "approval_id": approval_id,
                "edited_text": edited_text,
            },
        )
        response = await gateway.handle(inbound)
        return {"text": response.text, "success": response.success}

    @app.get("/api/memory/stats")
    async def memory_stats():
        return memory.stats()

    @app.get("/api/memory/knowledge")
    async def list_knowledge(limit: int = 100, offset: int = 0):
        return memory.list_knowledge(limit, offset)

    @app.get("/api/memory/search")
    async def search_memory(q: str, n: int = 10):
        results = memory.search_similar(q, n)
        scored = []
        for i, r in enumerate(results):
            scored.append({
                "content": r.get("content", ""),
                "metadata": r.get("metadata", {}),
                "score": 1.0 - (i * 0.1),
            })
        return {"results": scored}

    @app.delete("/api/memory/knowledge/{key}")
    async def delete_knowledge(key: str):
        if not memory.delete_knowledge(key):
            raise HTTPException(404, "Not found")
        return {"deleted": True}

    @app.get("/api/memory/conversations")
    async def list_conversations(session_id: str | None = None, agent: str | None = None, limit: int = 100):
        return memory.list_conversations(session_id, agent, limit)

    # ── Brain / Second Brain ────────────────────────────────────────────

    @app.get("/api/brain/stats")
    async def brain_stats():
        if not brain:
            return {"error": "Brain not initialized"}
        return brain.get_stats()

    @app.post("/api/brain/remember")
    async def brain_remember(request: Request):
        if not brain:
            return {"error": "Brain not initialized"}
        data = await request.json()
        entry = brain.remember(
            content=data.get("content", ""),
            memory_type=data.get("type", "episodic"),
            importance=data.get("importance", 0.5),
            tags=data.get("tags", []),
            sources=data.get("sources", []),
        )
        return entry.to_dict()

    @app.get("/api/brain/recall")
    async def brain_recall(q: str, type: str | None = None, limit: int = 10):
        if not brain:
            return {"error": "Brain not initialized"}
        results = brain.recall(q, memory_type=type, limit=limit)
        return [r.to_dict() for r in results]

    @app.post("/api/brain/think")
    async def brain_think(request: Request):
        if not brain:
            return {"error": "Brain not initialized"}
        data = await request.json()
        result = brain.think(context=data.get("context", ""), query=data.get("query", ""))
        return {"response": result}

    # ── Execution Copilot ──────────────────────────────────────────────

    @app.post("/api/copilot/workflow")
    async def create_workflow(request: Request):
        if not copilot:
            return {"error": "Copilot not initialized"}
        data = await request.json()
        workflow = copilot.create_workflow(
            name=data.get("name", "Untitled"),
            steps=data.get("steps", []),
            description=data.get("description", ""),
        )
        return workflow.to_dict()

    @app.post("/api/copilot/workflow/{workflow_id}/run")
    async def run_workflow(workflow_id: str):
        if not copilot:
            return {"error": "Copilot not initialized"}
        workflow = copilot.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(404, "Workflow not found")
        result = await copilot.execute_workflow(workflow)
        return result.to_dict()

    @app.get("/api/copilot/workflows")
    async def list_workflows():
        if not copilot:
            return {"error": "Copilot not initialized"}
        return copilot.list_workflows()

    @app.get("/api/copilot/suggest")
    async def suggest_workflow(intent: str):
        if not copilot:
            return {"error": "Copilot not initialized"}
        return copilot.suggest_workflow(intent)

    # ── Integrations ───────────────────────────────────────────────────

    @app.get("/api/integrations")
    async def list_integrations():
        if not integrations:
            return {"error": "Integrations not initialized"}
        return integrations.list_integrations()

    @app.post("/api/integrations")
    async def register_integration(request: Request):
        if not integrations:
            return {"error": "Integrations not initialized"}
        data = await request.json()
        from core.integrations import IntegrationType
        int_type = IntegrationType(data.get("type", "webhook"))
        result = integrations.register_integration(
            name=data.get("name", ""),
            integration_type=int_type,
            config=data.get("config", {}),
        )
        return result.to_dict()

    @app.delete("/api/integrations/{integration_id}")
    async def remove_integration(integration_id: str):
        if not integrations:
            return {"error": "Integrations not initialized"}
        if integrations.unregister_integration(integration_id):
            return {"deleted": True}
        raise HTTPException(404, "Integration not found")

    @app.post("/api/webhooks/{source}")
    async def receive_webhook(source: str, request: Request):
        if not integrations:
            return {"error": "Integrations not initialized"}
        data = await request.json()
        headers = dict(request.headers)
        event_type = data.get("event_type", data.get("action", "event"))
        if source == "github":
            event_type = headers.get("x-github-event", "event")
        return await integrations.process_webhook(source, event_type, data, headers)

    @app.get("/api/webhooks/events")
    async def list_webhook_events(limit: int = 20):
        if not integrations:
            return {"error": "Integrations not initialized"}
        return integrations.get_recent_events(limit)

    # ── Proactive Intelligence ─────────────────────────────────────────

    @app.get("/api/proactive/stats")
    async def proactive_stats():
        if not proactive:
            return {"error": "Proactive not initialized"}
        return proactive.get_stats()

    @app.get("/api/proactive/monitors")
    async def list_monitors():
        if not proactive:
            return {"error": "Proactive not initialized"}
        return proactive.list_monitors()

    @app.post("/api/proactive/monitors")
    async def create_monitor(request: Request):
        if not proactive:
            return {"error": "Proactive not initialized"}
        data = await request.json()
        from core.proactive import MonitorType
        mon_type = MonitorType(data.get("type", "domain"))
        result = proactive.register_monitor(
            name=data.get("name", ""),
            monitor_type=mon_type,
            target=data.get("target", ""),
            interval=data.get("interval", 3600),
            config=data.get("config", {}),
        )
        return result.to_dict()

    @app.get("/api/proactive/alerts")
    async def list_alerts(limit: int = 50, unacknowledged: bool = False):
        if not proactive:
            return {"error": "Proactive not initialized"}
        return proactive.get_alerts(limit, unacknowledged)

    @app.post("/api/proactive/alerts/{alert_id}/acknowledge")
    async def acknowledge_alert(alert_id: str):
        if not proactive:
            return {"error": "Proactive not initialized"}
        if proactive.acknowledge_alert(alert_id):
            return {"acknowledged": True}
        raise HTTPException(404, "Alert not found")

    @app.get("/api/proactive/suggest")
    async def proactive_suggest(q: str):
        if not proactive:
            return {"error": "Proactive not initialized"}
        return proactive.suggest(q)

    # ── Webhooks (WhatsApp, Slack, Teams) ───────────────────────────────

    whatsapp_ch = gateway.get_channel("whatsapp")
    slack_ch = gateway.get_channel("slack")
    teams_ch = gateway.get_channel("teams")

    @app.get("/webhooks/whatsapp")
    async def whatsapp_verify(request: Request):
        if not whatsapp_ch:
            raise HTTPException(404)
        result = await whatsapp_ch.verify_webhook(
            request.query_params.get("hub.mode", ""),
            request.query_params.get("hub.verify_token", ""),
            request.query_params.get("hub.challenge", ""),
        )
        if result:
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(result)
        raise HTTPException(403)

    @app.post("/webhooks/whatsapp")
    async def whatsapp_receive(request: Request):
        if whatsapp_ch:
            raw = await request.body()
            signature = request.headers.get("X-Hub-Signature-256", "")
            body = await request.json()
            await whatsapp_ch.handle_webhook(body, raw_body=raw, signature=signature)
        return {"ok": True}

    instagram_ch = gateway.get_channel("instagram")

    @app.get("/webhooks/instagram")
    async def instagram_verify(request: Request):
        if not instagram_ch:
            raise HTTPException(404)
        mode = request.query_params.get("hub.mode", "")
        token = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge", "")
        if mode == "subscribe" and token == instagram_ch.app_secret:
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(challenge)
        raise HTTPException(403)

    @app.post("/webhooks/instagram")
    async def instagram_receive(request: Request):
        if instagram_ch:
            raw = await request.body()
            signature = request.headers.get("X-Hub-Signature-256", "")
            body = await request.json()
            await instagram_ch.handle_webhook(body, raw_body=raw, signature=signature)
        return {"ok": True}

    @app.post("/webhooks/slack")
    async def slack_receive(request: Request):
        if not slack_ch:
            raise HTTPException(404)
        raw = await request.body()
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")
        if not slack_ch.verify_signature(timestamp, raw, signature):
            raise HTTPException(401)
        body = await request.json()
        challenge = await slack_ch.handle_webhook(body)
        if challenge:
            return challenge
        return {}

    @app.post("/webhooks/teams")
    async def teams_receive(request: Request):
        if not teams_ch:
            raise HTTPException(404)
        body = await request.json()
        return await teams_ch.handle_webhook(body)

    # ── Config Management ─────────────────────────────────────────────

    config_mgr = getattr(nexus_app, 'config_manager', None)

    @app.get("/api/config")
    async def get_config():
        if not config_mgr:
            return {"error": "Config manager not initialized"}
        return config_mgr.get_full_config()

    @app.get("/api/config/providers")
    async def list_config_providers():
        if not config_mgr:
            return {"providers": {}}
        return {"providers": config_mgr.list_providers()}

    @app.put("/api/config/providers/{name}/key")
    async def set_provider_key(name: str, request: Request):
        if not config_mgr:
            raise HTTPException(503, "Config manager not initialized")
        data = await request.json()
        api_key = data.get("api_key", "")
        if not api_key:
            raise HTTPException(400, "api_key is required")
        config_mgr.set_provider_key(name, api_key)
        return {"ok": True, "provider": name, "key_masked": config_mgr.get_provider_status(name).get("key_masked", "")}

    @app.delete("/api/config/providers/{name}/key")
    async def delete_provider_key(name: str):
        if not config_mgr:
            raise HTTPException(503, "Config manager not initialized")
        config_mgr.delete_provider_key(name)
        return {"ok": True, "deleted": name}

    @app.post("/api/config/providers/{name}/test")
    async def test_provider(name: str):
        if not config_mgr:
            raise HTTPException(503, "Config manager not initialized")
        key = config_mgr.get_provider_key(name)
        if name != "ollama" and not key:
            return {"ok": False, "error": "No API key configured"}
        try:
            import httpx
            router_name = config_mgr._resolve_name(name)
            provider = nexus_app.llm.router._provider_map.get(router_name)
            if not provider:
                return {"ok": False, "error": f"Unknown provider: {name}"}
            if name == "ollama":
                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.get(f"{provider.base_url}/api/tags")
                    return {"ok": resp.status_code == 200, "status": resp.status_code}
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            base = provider.base_url or provider._default_base_url()
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{base}/chat/completions",
                    json={"model": provider.model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
                    headers=headers,
                )
                return {"ok": resp.status_code == 200, "status": resp.status_code}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/config/providers/{name}/toggle")
    async def toggle_provider(name: str, request: Request):
        if not config_mgr:
            raise HTTPException(503, "Config manager not initialized")
        data = await request.json()
        enabled = data.get("enabled", True)
        config_mgr.set_provider_enabled(name, enabled)
        return {"ok": True, "provider": name, "enabled": enabled}

    @app.put("/api/config/providers/{name}/setting")
    async def set_provider_setting(name: str, request: Request):
        if not config_mgr:
            raise HTTPException(503, "Config manager not initialized")
        data = await request.json()
        key = data.get("key", "")
        value = data.get("value", "")
        if not key:
            raise HTTPException(400, "key is required")
        config_mgr.set_provider_setting(name, key, value)
        return {"ok": True, "provider": name, "key": key, "value": value}

    @app.get("/api/config/settings")
    async def get_settings():
        if not config_mgr:
            return {"settings": {}}
        return {"settings": config_mgr.list_settings()}

    @app.put("/api/config/settings")
    async def update_setting(request: Request):
        if not config_mgr:
            raise HTTPException(503, "Config manager not initialized")
        data = await request.json()
        key = data.get("key", "")
        value = data.get("value", "")
        if not key:
            raise HTTPException(400, "key is required")
        config_mgr.set_setting(key, value)
        return {"ok": True, "key": key, "value": value}

    @app.post("/api/config/reload")
    async def reload_config():
        if not config_mgr:
            raise HTTPException(503, "Config manager not initialized")
        config_mgr.reload()
        return {"ok": True, "message": "Config reloaded"}

    # ── Soul (personality) ────────────────────────────────────────────

    @app.get("/api/soul")
    async def get_soul():
        from core import soul as _soul_mod
        s = _soul_mod.get()
        return {
            "sections": s.sections,
            "stats": _soul_mod.section_stats(),
        }

    @app.get("/api/soul/{section}")
    async def get_soul_section(section: str):
        from core import soul as _soul_mod
        if section not in ("soul", "personality", "taste", "heartbeat"):
            raise HTTPException(404, "Unknown section")
        return {"section": section, "body": _soul_mod.get().section(section)}

    @app.put("/api/soul/{section}")
    async def save_soul_section(section: str, request: Request):
        from core import soul as _soul_mod
        if section not in ("soul", "personality", "taste", "heartbeat"):
            raise HTTPException(404, "Unknown section")
        data = await request.json()
        body = data.get("body", "")
        if not body.strip():
            raise HTTPException(400, "body cannot be empty")
        _soul_mod.save_section(section, body)
        return {"ok": True, "section": section}

    @app.post("/api/soul/reload")
    async def reload_soul():
        from core import soul as _soul_mod
        s = _soul_mod.reload()
        return {"ok": True, "loaded": list(s.sections.keys())}

    # ── Event log ──────────────────────────────────────────────────────

    @app.get("/api/events")
    async def get_events(limit: int = 100, since: float = 0.0, kind: str | None = None,
                         session_id: str | None = None):
        from core import events as _events_mod
        rows = _events_mod.query(limit=min(limit, 500), since=since, kind=kind, session_id=session_id)
        return {"events": rows, "count": len(rows)}

    @app.get("/api/events/stats")
    async def events_stats():
        from core import events as _events_mod
        return _events_mod.stats()

    # ── Permission modes (per session) ───────────────────────────────

    @app.get("/api/permissions/{session_id}")
    async def get_perm(session_id: str):
        from core import permissions as _perm_mod
        return _perm_mod.get(session_id).to_dict()

    @app.put("/api/permissions/{session_id}")
    async def set_perm(session_id: str, request: Request):
        from core import permissions as _perm_mod
        data = await request.json()
        mode = data.get("mode", "ask")
        if mode not in ("ask", "allow"):
            raise HTTPException(400, "mode must be 'ask' or 'allow'")
        return _perm_mod.set_mode(session_id, mode).to_dict()

    @app.get("/api/permissions")
    async def list_perms():
        from core import permissions as _perm_mod
        return {"permissions": _perm_mod.list_all()}

    return app

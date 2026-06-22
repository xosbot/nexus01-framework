"""FastAPI server — REST API, WebSocket chat, webhooks, static OS dashboard."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api.auth import AuthMiddleware, ws_auth
from gateway.types import ChannelKind, InboundMessage

logger = logging.getLogger(__name__)
WEB_ROOT = Path(__file__).parent.parent / "web" / "os"
ALLOWED_ORIGINS = os.getenv("NEXUS_ALLOWED_ORIGINS", "https://navos.space").split(",")


class ChatRequest(BaseModel):
    text: str
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
    source: str = "manual"


def create_api_app(nexus_app) -> FastAPI:
    app = FastAPI(title="NEXUS-01 OS", version="0.3.0")
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

    @app.get("/api/rag/stats")
    async def rag_stats():
        return nexus_app.rag.stats()

    @app.get("/api/rag/search")
    async def rag_search(q: str, n: int = 5):
        return nexus_app.rag.search(q, n)

    @app.post("/api/rag/ingest")
    async def rag_ingest(req: IngestRequest):
        RESTRICTED = ["/etc", "/proc", "/sys", "/dev", "/root/.ssh"]
        if req.path:
            from pathlib import Path
            p = Path(req.path).resolve()
            for restricted in RESTRICTED:
                if str(p).startswith(restricted):
                    raise HTTPException(403, f"Access to {restricted} is restricted")
        if req.text:
            chunks = nexus_app.rag.ingest_text(req.text, source=req.source)
        elif req.path:
            p = Path(req.path)
            if p.is_dir():
                stats = nexus_app.rag.ingest_directory(p)
                return stats
            chunks = nexus_app.rag.ingest_file(p, source=req.source)
        else:
            raise HTTPException(400, "Provide text or path")
        return {"chunks": chunks, "stats": nexus_app.rag.stats()}

    # ── Chat ────────────────────────────────────────────────────────────

    @app.post("/api/chat")
    async def chat(req: ChatRequest):
        session_id = req.session_id
        if not session_id:
            session = memory.sessions.create(title=req.text[:60], project_id=req.project_id, channel="web")
            session_id = session["id"]
        else:
            memory.sessions.touch(session_id)

        inbound = InboundMessage(
            channel=ChannelKind.WEB,
            session_id=session_id,
            text=req.text,
            user_id="web",
            metadata={"project_id": req.project_id, "session_id": session_id},
        )
        response = await gateway.handle(inbound)
        memory.save_conversation("orchestrator", "user", req.text, session_id)
        memory.save_conversation("orchestrator", "assistant", response.text, session_id)

        return {
            "session_id": session_id,
            "text": response.text,
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

    @app.websocket("/ws/chat")
    async def ws_chat(websocket: WebSocket):
        token = websocket.query_params.get("token") or websocket.headers.get("Authorization", "").replace("Bearer ", "")
        if not ws_auth.authenticate(token):
            await websocket.close(code=4001, reason="Unauthorized")
            return
        client_ip = websocket.client.host if websocket.client else "unknown"
        if ws_auth.is_rate_limited(client_ip):
            await websocket.close(code=4029, reason="Rate limit exceeded")
            return
        await websocket.accept()
        session_id = None
        try:
            while True:
                data = await websocket.receive_json()
                text = data.get("text", "").strip()
                if not text:
                    continue
                if data.get("type") == "approve":
                    inbound = InboundMessage(
                        channel=ChannelKind.WEB,
                        session_id=data.get("session_id", session_id or "web"),
                        text="yes" if data.get("approved") else "no",
                        user_id="web",
                        metadata={
                            "approval_decision": data.get("approved"),
                            "approval_id": data.get("approval_id"),
                        },
                    )
                else:
                    session_id = data.get("session_id") or session_id
                    if not session_id:
                        s = memory.sessions.create(title=text[:60], channel="web")
                        session_id = s["id"]
                    else:
                        memory.sessions.touch(session_id)
                    inbound = InboundMessage(
                        channel=ChannelKind.WEB,
                        session_id=session_id,
                        text=text,
                        user_id="web",
                        metadata={"session_id": session_id},
                    )

                await websocket.send_json({"type": "typing"})
                response = await gateway.handle(inbound)
                if text and data.get("type") != "approve":
                    memory.save_conversation("orchestrator", "user", text, session_id)
                    memory.save_conversation("orchestrator", "assistant", response.text, session_id)

                await websocket.send_json({
                    "type": "response",
                    "session_id": session_id,
                    "text": response.text,
                    "route": response.route,
                    "requires_approval": response.requires_approval,
                    "approval_id": response.approval_id,
                })
        except WebSocketDisconnect:
            pass

    # ── Projects ──────────────────────────────────────────────────────

    @app.get("/api/projects")
    async def list_projects():
        return memory.projects.list()

    @app.post("/api/projects")
    async def create_project(body: ProjectCreate):
        return memory.projects.create(body.name, body.description)

    @app.get("/api/projects/{project_id}")
    async def get_project(project_id: str):
        p = memory.projects.get(project_id)
        if not p:
            raise HTTPException(404, "Project not found")
        p["sessions"] = memory.sessions.list(project_id=project_id)
        return p

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
        return memory.sessions.list(project_id=project_id)

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

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        if not memory.sessions.delete(session_id):
            raise HTTPException(404, "Session not found")
        return {"deleted": True}

    # ── Memory ────────────────────────────────────────────────────────

    @app.get("/api/memory/stats")
    async def memory_stats():
        return memory.stats()

    @app.get("/api/memory/knowledge")
    async def list_knowledge(limit: int = 100, offset: int = 0):
        return memory.list_knowledge(limit, offset)

    @app.get("/api/memory/search")
    async def search_memory(q: str, n: int = 10):
        return memory.search_similar(q, n)

    @app.delete("/api/memory/knowledge/{key}")
    async def delete_knowledge(key: str):
        if not memory.delete_knowledge(key):
            raise HTTPException(404, "Not found")
        return {"deleted": True}

    @app.get("/api/memory/conversations")
    async def list_conversations(session_id: str | None = None, agent: str | None = None, limit: int = 100):
        return memory.list_conversations(session_id, agent, limit)

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
            await whatsapp_ch.handle_webhook(await request.json())
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

    return app

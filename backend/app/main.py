"""JEEVAN API — FastAPI application entrypoint.

Serves:
  /            -> cinematic landing page
  /login /signup /forgot-password /citizen ... /admin -> SPA client
  /api/v1/...  -> REST API (auth, cctv, role dashboards)
  /ws          -> realtime event stream (token-authenticated)
"""
import asyncio
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import HOME_DIR, settings
from .database import SessionLocal, init_db
from .rbac import ws_auth
from .routers import auth, core, cctv
from .services.ws_manager import manager

app = FastAPI(title="JEEVAN API", version="1.0.0",
              description="Emergency Response Platform — auth, RBAC, dashboards, CCTV AI pipeline")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

app.include_router(auth.router)
app.include_router(cctv.router)
app.include_router(core.router)

LANDING = os.path.join(HOME_DIR, "landing.html")
SPA = os.path.join(HOME_DIR, "platform.html")
SPA_PREFIXES = ("/login", "/signup", "/forgot-password",
                "/citizen", "/ambulance", "/hospital", "/police", "/admin")


@app.on_event("startup")
async def _startup() -> None:
    init_db()
    manager.main_loop = asyncio.get_running_loop()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": settings.APP_NAME, "version": "1.0.0"}


@app.get("/", include_in_schema=False)
def landing():
    return FileResponse(LANDING, media_type="text/html")


@app.get("/ws", include_in_schema=False)
async def websocket_endpoint(ws: WebSocket):
    db = SessionLocal()
    try:
        user = await ws_auth(ws, db)
        if user is None:
            await ws.close(code=4401)
            return
        await manager.connect(ws, user.role, user.id)
        await manager.broadcast({
            "type": "presence", "user": user.name, "role": user.role,
        })
        try:
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text('{"type":"pong"}')
        except WebSocketDisconnect:
            await manager.disconnect(ws)
    except Exception:
        pass
    finally:
        db.close()


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    p = "/" + full_path.lstrip("/")
    if p.startswith(SPA_PREFIXES):
        return FileResponse(SPA, media_type="text/html")
    return JSONResponse(status_code=404, content={
        "detail": {"code": "not_found", "message": "Resource not found."}})

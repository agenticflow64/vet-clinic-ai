"""FastAPI-приложение: чат-API ассистента, заявки, статика виджета и админки.

Запуск:
    uvicorn app.main:app --port 8010
"""

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import store
from .assistant import Assistant
from .config import settings
from .search import PriceSearch

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Vet Clinic AI", docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

_conn = store.connect(settings.db_path)
_search = PriceSearch(store.get_services(_conn), _conn)
assistant = Assistant(_conn, _search)


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class StatusUpdate(BaseModel):
    status: str


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "services": len(_search)}


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    session_id = req.session_id or store.new_session_id()
    result = assistant.handle_message(session_id, req.message)
    result["session_id"] = session_id
    return result


@app.get("/api/appointments")
def appointments() -> list[dict]:
    return store.list_appointments(_conn)


@app.patch("/api/appointments/{appointment_id}")
def update_status(appointment_id: int, body: StatusUpdate) -> dict:
    if not store.update_appointment_status(_conn, appointment_id, body.status):
        raise HTTPException(status_code=400, detail="invalid id or status")
    return {"ok": True}


@app.get("/widget")
def widget_page():
    return FileResponse(STATIC_DIR / "widget.html", media_type="text/html")


@app.get("/embed.js")
def embed_script():
    return FileResponse(STATIC_DIR / "embed.js", media_type="application/javascript")


@app.get("/demo")
def demo_page():
    return FileResponse(STATIC_DIR / "demo.html", media_type="text/html")


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html", media_type="text/html")

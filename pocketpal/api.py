"""HTTP API.

Conversations stay in the browser: the server never stores what people said. It keeps only staff accounts,
settings, an audit log and per-message metadata (category, route, provider, latency) for the admin console.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from pathlib import Path
from typing import Literal, Optional

import os

from dotenv import load_dotenv

# Project .env first, then a shared one in the parent folder (existing values are not overwritten).
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")
load_dotenv(_ROOT.parent / ".env")
# Accept the common misspelling GROK_API_KEY for a Groq key (gsk_...).
if not os.environ.get("GROQ_API_KEY") and os.environ.get("GROK_API_KEY", "").startswith("gsk_"):
    os.environ["GROQ_API_KEY"] = os.environ["GROK_API_KEY"]

from fastapi import FastAPI, File, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from pocketpal import persona  # noqa: E402
from pocketpal.admin import build_router  # noqa: E402
from pocketpal.agent import Companion, Turn  # noqa: E402
from pocketpal.auth import Auth, create_staff, load_secret  # noqa: E402
from pocketpal.db import DB  # noqa: E402
from pocketpal.llm import Provider, build_providers, chat_with_fallback  # noqa: E402
from pocketpal.speech import SpeechError, build_stt, build_tts, speakable  # noqa: E402

log = logging.getLogger("pocketpal")
STATIC = Path(__file__).parent / "static"
MAX_AUDIO = 10 * 1024 * 1024


class Msg(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatIn(BaseModel):
    messages: list[Msg] = Field(min_length=1, max_length=200)
    memory: str = Field(default="", max_length=2000)
    region: Optional[str] = Field(default=None, max_length=8)
    name: Optional[str] = Field(default=None, pattern=r"^[A-Za-z][A-Za-z -]{0,19}$")


class ChatOut(BaseModel):
    reply: str
    crisis: bool
    helplines: list[dict[str, str]]
    provider: str
    category: str = "support"
    route: str = "support"
    action: Optional[dict] = None


class SummaryIn(BaseModel):
    messages: list[Msg] = Field(min_length=1, max_length=200)
    memory: str = Field(default="", max_length=2000)


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    voice: Literal["female", "male"] = "female"


BLOCKED_REPLY = "Pocket Pal isn't available on this device right now."


def create_app(providers: Optional[list[Provider]] = None, stt=..., tts=..., db: Optional[DB] = None,
               secret: Optional[bytes] = None) -> FastAPI:
    app = FastAPI(title="Pocket Pal", version="0.2.0")
    providers = providers if providers is not None else build_providers()
    stt = build_stt() if stt is ... else stt
    tts = build_tts() if tts is ... else tts
    db = db or DB()
    secret = secret or load_secret()
    auth = Auth(db, secret)
    companion = Companion(providers, db.settings)
    bootstrap_super_admin(db)

    def device_of(request: Request) -> Optional[str]:
        """The browser sends a random anonymous id; we keep only a keyed hash of it."""
        raw = request.headers.get("x-device-id", "")[:64]
        return hmac.new(secret, raw.encode(), hashlib.sha256).hexdigest()[:24] if raw else None

    def guard(request: Request) -> Optional[str]:
        device = device_of(request)
        if db.is_blocked(device):
            raise HTTPException(403, BLOCKED_REPLY)
        return device

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "llm": [p.name for p in providers], "stt": stt is not None, "tts": tts is not None}

    @app.post("/api/chat", response_model=ChatOut)
    def chat(req: ChatIn, request: Request) -> ChatOut:
        device = guard(request)
        if req.messages[-1].role != "user":
            raise HTTPException(400, "last message must be from the user")
        res = companion.respond(Turn([m.model_dump() for m in req.messages], req.memory, req.region, req.name))
        db.event("chat", device, res.category, res.route, tuple(res.flags) + tuple(res.trace), res.provider, res.latency_ms)
        return ChatOut(reply=res.reply, crisis=res.crisis, helplines=res.helplines, provider=res.provider,
                       category=res.category, route=res.route, action=res.action)

    @app.post("/api/summarize")
    def summarize(req: SummaryIn, request: Request) -> dict:
        guard(request)
        convo = "\n".join(f"{m.role}: {m.content}" for m in req.messages[-40:])
        user = (f"Previous notes:\n{req.memory}\n\n" if req.memory else "") + f"Conversation:\n{convo}"
        notes, _ = chat_with_fallback(providers, [{"role": "system", "content": persona.SUMMARY_PROMPT},
                                                  {"role": "user", "content": user}], max_tokens=200)
        return {"memory": notes[:2000]}

    @app.post("/api/transcribe")
    async def transcribe(request: Request, audio: UploadFile = File(...)) -> dict:
        guard(request)
        if stt is None:
            raise HTTPException(503, "server speech-to-text not configured")
        data = await audio.read()
        if not data or len(data) > MAX_AUDIO:
            raise HTTPException(400, "audio missing or too large")
        try:
            return {"text": stt.transcribe(data, audio.filename or "audio.webm")}
        except SpeechError as e:
            log.warning("stt failed: %s", e)
            raise HTTPException(502, "speech-to-text failed") from e

    @app.post("/api/speak")
    def speak(req: SpeakIn, request: Request) -> Response:
        guard(request)
        if tts is None:
            return Response(status_code=204)  # browser uses its own voice
        try:
            out = tts.synthesize(speakable(req.text), req.voice)
            audio, mime = out if isinstance(out, tuple) else (out, "audio/mpeg")
            return Response(audio, media_type=mime)
        except SpeechError as e:
            log.warning("tts failed, browser voice will be used: %s", e)
            return Response(status_code=204)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/admin", include_in_schema=False)
    def admin_page() -> FileResponse:
        return FileResponse(STATIC / "admin.html")

    app.include_router(build_router(db, auth))
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def bootstrap_super_admin(db: DB) -> None:
    """First run on a server without a terminal: create the first super admin from env vars, once."""
    email, password = os.environ.get("SUPERADMIN_EMAIL"), os.environ.get("SUPERADMIN_PASSWORD")
    if email and password and not db.one("SELECT 1 AS x FROM staff LIMIT 1"):
        create_staff(db, email, os.environ.get("SUPERADMIN_NAME", "Super admin"), "super_admin", password)
        db.audit(None, "staff.bootstrap", email, {"role": "super_admin"})
        log.warning("created first super admin %s from environment; remove SUPERADMIN_PASSWORD now", email)


app = create_app() if os.environ.get("POCKETPAL_NO_APP") != "1" else None

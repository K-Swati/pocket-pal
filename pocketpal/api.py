"""HTTP API. Stateless: the browser keeps the conversation and memory, the server keeps nothing."""

from __future__ import annotations

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

from fastapi import FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from pocketpal import persona, safety  # noqa: E402
from pocketpal.llm import Provider, build_providers, chat_with_fallback  # noqa: E402
from pocketpal.speech import SpeechError, build_stt, build_tts, speakable  # noqa: E402

log = logging.getLogger("pocketpal")
STATIC = Path(__file__).parent / "static"
MAX_HISTORY = 20
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


class SummaryIn(BaseModel):
    messages: list[Msg] = Field(min_length=1, max_length=200)
    memory: str = Field(default="", max_length=2000)


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    voice: Literal["female", "male"] = "female"


def create_app(providers: list[Provider] | None = None, stt=..., tts=...) -> FastAPI:
    app = FastAPI(title="Pocket Pal", version="0.1.0")
    providers = providers if providers is not None else build_providers()
    stt = build_stt() if stt is ... else stt
    tts = build_tts() if tts is ... else tts

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "llm": [p.name for p in providers], "stt": stt is not None, "tts": tts is not None}

    @app.post("/api/chat", response_model=ChatOut)
    def chat(req: ChatIn) -> ChatOut:
        last = req.messages[-1]
        if last.role != "user":
            raise HTTPException(400, "last message must be from the user")
        if safety.is_crisis(last.content):
            return ChatOut(reply=safety.crisis_reply(req.region), crisis=True,
                           helplines=safety.helplines(req.region), provider="safety")
        system = persona.SYSTEM_PROMPT
        if req.name and req.name != "Pocket Pal":
            system += f"\nYour name is {req.name}. Use it if you introduce yourself; you are still an AI friend.\n"
        if req.memory.strip():
            system += "\n" + persona.MEMORY_PREFIX + req.memory.strip()
        msgs = [{"role": "system", "content": system}] + [m.model_dump() for m in req.messages[-MAX_HISTORY:]]
        reply, used = chat_with_fallback(providers, msgs)
        return ChatOut(reply=reply, crisis=False, helplines=[], provider=used)

    @app.post("/api/summarize")
    def summarize(req: SummaryIn) -> dict:
        convo = "\n".join(f"{m.role}: {m.content}" for m in req.messages[-40:])
        user = (f"Previous notes:\n{req.memory}\n\n" if req.memory else "") + f"Conversation:\n{convo}"
        notes, _ = chat_with_fallback(providers, [{"role": "system", "content": persona.SUMMARY_PROMPT},
                                                  {"role": "user", "content": user}], max_tokens=200)
        return {"memory": notes[:2000]}

    @app.post("/api/transcribe")
    async def transcribe(audio: UploadFile = File(...)) -> dict:
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
    def speak(req: SpeakIn) -> Response:
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

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()

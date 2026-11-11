"""Chat providers behind one interface, tried in order so a rate limit on one free tier falls through to the next."""

from __future__ import annotations

import logging
import os
import random
import re
from typing import Any, Optional, Protocol

import httpx

log = logging.getLogger("pocketpal.llm")
Messages = list[dict[str, str]]


class ProviderError(Exception):
    pass


class Provider(Protocol):
    name: str

    def chat(self, messages: Messages, max_tokens: int = 300) -> str: ...


class OpenAICompatible:
    """Groq and Gemini both expose an OpenAI-style /chat/completions endpoint."""

    def __init__(self, name: str, base_url: str, api_key: str, model: str, client: Optional[httpx.Client] = None,
                 extra: Optional[dict[str, Any]] = None):
        self.name, self.base_url, self.api_key, self.model = name, base_url.rstrip("/"), api_key, model
        self.client = client or httpx.Client(timeout=30)
        self.extra = extra or {}

    def chat(self, messages: Messages, max_tokens: int = 300) -> str:
        try:
            r = self.client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.8, **self.extra},
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.name}: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"{self.name}: HTTP {r.status_code} {r.text[:200]}")
        text = (r.json()["choices"][0]["message"].get("content") or "")
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # some models inline their reasoning
        if not text:
            raise ProviderError(f"{self.name}: empty reply")
        return text


class MockProvider:
    """Offline stand-in so the app runs and tests pass with no keys. Not a real conversation partner."""

    name = "mock"
    _replies = [
        "That sounds really heavy. I'm here, take your time. What's been weighing on you most?",
        "I hear you. It makes sense to feel that way. Do you want to tell me more about it?",
        "Thank you for sharing that with me. How are you feeling right now, in this moment?",
        "That's a lot to carry on your own. Is there anyone around you who knows how you're doing?",
    ]

    def chat(self, messages: Messages, max_tokens: int = 300) -> str:
        if messages and messages[0]["role"] == "system" and "Summarise" in messages[0]["content"]:
            return "- They chatted with Pocket Pal recently."
        return random.choice(self._replies)


def build_providers() -> list[Provider]:
    order = [p.strip().lower() for p in os.environ.get("LLM_ORDER", "groq,gemini,mock").split(",") if p.strip()]
    out: list[Provider] = []
    for name in order:
        if name == "groq" and os.environ.get("GROQ_API_KEY"):
            key, base = os.environ["GROQ_API_KEY"], "https://api.groq.com/openai/v1"
            # Fast primary model, then a second Groq model in case the first is rate limited or retired.
            out.append(OpenAICompatible("groq", base, key, os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b")))
            backup = os.environ.get("GROQ_BACKUP_MODEL", "openai/gpt-oss-120b")
            if backup:
                extra = {"reasoning_effort": "low"} if backup.startswith("openai/gpt-oss") else {}
                out.append(OpenAICompatible("groq-backup", base, key, backup, extra=extra))
        elif name == "gemini" and os.environ.get("GEMINI_API_KEY"):
            out.append(OpenAICompatible("gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
                                        os.environ["GEMINI_API_KEY"], os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")))
        elif name == "mock":
            out.append(MockProvider())
    return out or [MockProvider()]


SORRY = "Sorry, I lost my train of thought for a second. Could you say that again?"


def chat_with_fallback(providers: list[Provider], messages: Messages, max_tokens: int = 300) -> tuple[str, str]:
    """Return (reply, provider name). Never raises: the person should never see a stack trace."""
    for p in providers:
        try:
            return p.chat(messages, max_tokens), p.name
        except ProviderError as e:
            log.warning("provider failed, trying next: %s", e)
    return SORRY, "none"

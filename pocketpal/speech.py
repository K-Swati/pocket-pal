"""Server-side speech. Each part is optional: when a key is missing the browser's own speech is used instead."""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

import httpx


class SpeechError(Exception):
    pass


class GroqWhisper:
    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None):
        self.api_key, self.model, self.client = api_key, model, client or httpx.Client(timeout=60)

    def transcribe(self, audio: bytes, filename: str = "audio.webm") -> str:
        try:
            r = self.client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data={"model": self.model, "response_format": "json"},
                files={"file": (filename, audio)},
            )
        except httpx.HTTPError as e:
            raise SpeechError(str(e)) from e
        if r.status_code != 200:
            raise SpeechError(f"HTTP {r.status_code} {r.text[:200]}")
        return r.json().get("text", "").strip()


# Warm, gentle voices from the ElevenLabs default library (available on the free tier). Override in .env.
DEFAULT_VOICES = {
    "female": "EXAVITQu4vr4xnSDxMaL",  # Sarah: soft, reassuring
    "male": "JBFqnCBsd6RMkjVDRZzb",    # George: warm, calm
}
# Lower stability = more natural expression; a touch of style and a slightly slower pace sound more caring.
VOICE_SETTINGS = {"stability": 0.45, "similarity_boost": 0.8, "style": 0.25, "use_speaker_boost": True, "speed": 0.92}


class ElevenLabsTTS:
    name, mime = "elevenlabs", "audio/mpeg"

    def __init__(self, api_key: str, voices: dict[str, str], model: str, client: httpx.Client | None = None):
        self.api_key, self.voices, self.model = api_key, voices, model
        self.client = client or httpx.Client(timeout=60)

    def synthesize(self, text: str, voice: str = "female") -> bytes:
        voice_id = self.voices.get(voice, self.voices["female"])
        try:
            r = self.client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": self.api_key, "accept": "audio/mpeg"},
                params={"output_format": "mp3_44100_128"},
                json={"text": text, "model_id": self.model, "voice_settings": VOICE_SETTINGS},
            )
        except httpx.HTTPError as e:
            raise SpeechError(str(e)) from e
        if r.status_code != 200:  # out of free credits shows up here as 401/429
            raise SpeechError(f"HTTP {r.status_code} {r.text[:200]}")
        return r.content


class GroqOrpheusTTS:
    """Expressive TTS on Groq. Needs a one-time terms acceptance in the Groq console for the model."""

    name, mime = "groq-orpheus", "audio/wav"

    def __init__(self, api_key: str, voices: dict[str, str], model: str, client: Optional[httpx.Client] = None):
        self.api_key, self.voices, self.model = api_key, voices, model
        self.client = client or httpx.Client(timeout=60)

    def synthesize(self, text: str, voice: str = "female") -> bytes:
        try:
            r = self.client.post(
                "https://api.groq.com/openai/v1/audio/speech",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "voice": self.voices.get(voice, self.voices["female"]),
                      "input": text, "response_format": "wav"},
            )
        except httpx.HTTPError as e:
            raise SpeechError(str(e)) from e
        if r.status_code != 200:
            raise SpeechError(f"HTTP {r.status_code} {r.text[:200]}")
        return r.content


class ChainTTS:
    """Try each voice service in order. A service that fails for a permanent reason (bad key, terms not
    accepted, out of credits) is skipped for a while instead of being retried on every reply."""

    def __init__(self, engines: list, cooldown: float = 600.0):
        self.engines, self.cooldown, self._skip_until = engines, cooldown, {}

    def synthesize(self, text: str, voice: str = "female") -> tuple[bytes, str]:
        import time
        now = time.monotonic()
        for e in self.engines:
            if self._skip_until.get(e.name, 0) > now:
                continue
            try:
                return e.synthesize(text, voice), e.mime
            except SpeechError as err:
                logging.getLogger("pocketpal.speech").warning("%s failed: %s", e.name, err)
                if re.search(r"HTTP (400|401|402|403|404|429)", str(err)):
                    self._skip_until[e.name] = now + self.cooldown
        raise SpeechError("no voice service available")


def build_stt() -> GroqWhisper | None:
    key = os.environ.get("GROQ_API_KEY")
    return GroqWhisper(key, os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")) if key else None


def build_tts() -> Optional[ChainTTS]:
    engines = []
    if os.environ.get("ELEVENLABS_API_KEY"):
        voices = {
            "female": os.environ.get("ELEVENLABS_VOICE_FEMALE") or DEFAULT_VOICES["female"],
            "male": os.environ.get("ELEVENLABS_VOICE_MALE") or DEFAULT_VOICES["male"],
        }
        engines.append(ElevenLabsTTS(os.environ["ELEVENLABS_API_KEY"], voices,
                                     os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")))
    if os.environ.get("GROQ_API_KEY") and os.environ.get("GROQ_TTS", "on").lower() != "off":
        voices = {"female": os.environ.get("GROQ_VOICE_FEMALE", "autumn"), "male": os.environ.get("GROQ_VOICE_MALE", "daniel")}
        engines.append(GroqOrpheusTTS(os.environ["GROQ_API_KEY"], voices,
                                      os.environ.get("GROQ_TTS_MODEL", "canopylabs/orpheus-v1-english")))
    return ChainTTS(engines) if engines else None


def speakable(text: str) -> str:
    """Strip markdown and emoji the model may add anyway, so the voice doesn't read symbols aloud."""
    text = re.sub(r"[*#_`>\[\]]", "", text)
    text = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", text)
    return re.sub(r"\s+", " ", text).strip()

"""Browser tests: a real Chromium drives the real page against a local server with fake LLM and speech services."""

import io
import math
import socket
import struct
import threading
import time
import wave

import pytest
import uvicorn

from playwright.sync_api import expect

from pocketpal.api import create_app

expect.set_options(timeout=10_000)


def tone_wav(seconds: float = 1.2, rate: int = 16000, silence_after: float = 0.0) -> bytes:
    """A tone whose loudness rises and falls (so lip sync has something to follow), optionally followed by silence."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        n = int(seconds * rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(12000 * (0.3 + 0.7 * abs(math.sin(math.pi * 3 * i / n))) * math.sin(2 * math.pi * 220 * i / rate)))
            for i in range(n)) + b"\0\0" * int(silence_after * rate))
    return buf.getvalue()


class FakeLLM:
    name = "fake"

    def __init__(self):
        self.calls = []

    def chat(self, messages, max_tokens=300):
        self.calls.append(messages)
        return "I'm right here with you, and I'm not going anywhere. What's been on your mind tonight?"


class FakeSTT:
    def __init__(self):
        self.calls = 0

    def transcribe(self, audio, filename="audio.webm"):
        self.calls += 1
        return "I feel a bit lonely tonight"


class FakeTTS:
    def __init__(self):
        self.voices, self.texts = [], []

    def synthesize(self, text, voice="female"):
        self.voices.append(voice)
        self.texts.append(text)
        time.sleep(0.4)  # like a real voice service
        return tone_wav(), "audio/wav"


class Server:
    def __init__(self, tts=True):
        self.llm, self.stt, self.tts = FakeLLM(), FakeSTT(), (FakeTTS() if tts else None)
        app = create_app(providers=[self.llm], stt=self.stt, tts=self.tts)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
        self._t = threading.Thread(target=self._srv.run, daemon=True)

    def __enter__(self):
        self._t.start()
        for _ in range(100):
            if self._srv.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("server did not start")

    def __exit__(self, *a):
        self._srv.should_exit = True
        self._t.join(5)


@pytest.fixture
def server():
    with Server() as s:
        yield s


@pytest.fixture
def server_no_tts():
    with Server(tts=False) as s:
        yield s


@pytest.fixture(scope="session")
def fake_mic(tmp_path_factory):
    p = tmp_path_factory.mktemp("mic") / "mic.wav"
    p.write_bytes(tone_wav(1.0, silence_after=3.0))  # "speaks" for 1 s then pauses; Chrome loops the file
    return p


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args, fake_mic):
    return {**browser_type_launch_args, "args": [
        "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
        f"--use-file-for-fake-audio-capture={fake_mic}",
    ]}


@pytest.fixture
def browser_context_args(browser_context_args):
    return {**browser_context_args, "permissions": ["microphone"], "locale": "en-IN"}


@pytest.fixture
def errors(page):
    """Collects uncaught page errors; every test asserts there were none."""
    found = []
    page.on("pageerror", lambda e: found.append(str(e)))
    return found

# Pocket Pal

A voice companion to talk to when you feel sad, lonely or low. Pocket Pal listens, keeps you company and answers in a warm voice.

> **Pocket Pal is an AI, not a therapist, counsellor or medical service.** It does not diagnose, treat or give medical advice. If you are in danger or thinking about harming yourself, contact a crisis line or your local emergency number.

## What it does

- **Talk, don't type.** Tap the mic and speak; a short pause sends it. In hands-free mode it keeps listening after each reply, like a phone call.
- **A character to talk to.** Five original companions (Mochi, Miso, Bao, Clover, Nimbus) blink, listen, think, lip-sync to their voice and react to how the conversation is going. Each has fixed signature colours, defined in `pocketpal/static/characters.js`.
- **Warm voices.** Female or male, with words appearing in time with the speech.
- **Six themes**, each with its own gentle animated scene (aurora, sunrise, ocean, meadow, candy, night sky).
- **A magical first-time intro** where your companion appears with a wave of a wand and explains what it is (and isn't).
- **Private by default.** Conversations and memories stay in your browser.

## Built on free tiers

| Part | Service | Without a key |
|---|---|---|
| Conversation | Groq (Qwen 3.8 27B, then GPT-OSS 120B), then Gemini as backup | Offline mock replies |
| Speech to text | Groq Whisper | Browser speech recognition (Chrome, Edge, Safari) |
| Voice | ElevenLabs, then Groq Orpheus (free; accept its terms once in the Groq console) | Browser's built-in voice |
| Hosting | Render / Hugging Face Spaces / Fly.io | Runs locally |

The order in `LLM_ORDER` is tried left to right, so when one free tier hits its rate limit the next one answers. Voices are tried in the same way: ElevenLabs, then Orpheus, then the browser voice. Orpheus voices: autumn, diana, hannah (female), austin, daniel, troy (male); set them with `GROQ_VOICE_FEMALE` / `GROQ_VOICE_MALE`.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # add GROQ_API_KEY (free: https://console.groq.com/keys)
pytest -q                   # unit tests: offline, no keys needed
playwright install chromium # once, for the browser tests
pytest -m e2e               # browser tests: real Chromium, fake mic, fake LLM/voice (no keys, ~90 s)
PORT=8077 python -m pocketpal  # open http://localhost:8077
```

The microphone needs `localhost` or HTTPS. On a phone, use the deployed HTTPS URL and "Add to Home Screen" to install it like an app.

## Safety design

- **Crisis check in code, before the model** (`pocketpal/safety.py`). Messages about suicide or self-harm never reach the LLM: Pocket Pal replies with a fixed, caring message and helplines for the user's region (from the browser language), then keeps talking. Tested for common phrasings and for ordinary sadness ("this traffic is killing me") that should *not* trigger it.
- **"Need help now?"** is always visible in the header.
- **First-run notice** with an 18+ and "this is an AI" acknowledgement.
- **Persona rules** (`pocketpal/persona.py`): short spoken replies, listening before advice, no diagnosis or medication talk, honesty about being an AI, and gentle encouragement toward real people in the user's life.
- The browser can only send `user` and `assistant` messages; the system prompt is set by the server.

Keyword detection misses indirect phrasing. A second check (an LLM classifier on each message) would catch more and is the next safety improvement worth making.

## Privacy

- The server is stateless: it stores no conversations, logs no message text.
- Chats and the short "memory" summary live in the browser's local storage. "Forget everything about me" in the ⋯ menu erases them.
- Messages do pass through the LLM and speech providers. Read their data policies; **Gemini's free tier may use prompts to improve Google's products**, so leave `GEMINI_API_KEY` empty if that matters to you.

## Deploy free on Render

1. Push this folder to a GitHub repo.
2. Render → New → Web Service → pick the repo. Runtime: Docker (uses the `Dockerfile`).
3. Add environment variables from `.env.example` (at least `GROQ_API_KEY`).
4. Free instances sleep when idle, so the first visit after a while takes ~30–60 s.

## Layout

```
pocketpal/
  persona.py      who the companion is: system prompt and memory prompts
  safety.py       crisis detection and regional helplines
  llm.py          Groq / Gemini / mock providers with fallback
  speech.py       Groq Whisper, ElevenLabs and Groq Orpheus voices, all optional
  api.py          FastAPI: /api/chat, /api/summarize, /api/transcribe, /api/speak
  static/
    index.html    the app (single page, installable)
    characters.js the five characters and their brand colours
tests/            unit tests (offline)
tests/e2e/        Playwright browser tests (real Chromium, fake mic and services)
```

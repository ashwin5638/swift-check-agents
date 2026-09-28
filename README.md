# Wire Room — Daily Maritime News-Reel Pipeline

LangGraph state machine (Python) + a React control-room dashboard. Picks one
**major marine-industry event** a day, writes a narration, renders a 20–30s
vertical reel with burned-in captions, and posts it to Facebook and LinkedIn.

## Domain

Shipping, logistics & cargo, crew/safety, classification, and offshore energy —
drawn from 9 verified maritime feeds (gCaptain, The Loadstar, Shipping Telegraph,
Hellenic Shipping News, Container News, Marine Insight, DNV, Splash247,
Offshore Wind.biz). IMO and USCG publish no usable RSS, so regulation coverage
would need a scraper if you want it.

The Research Agent is domain-locked: it only accepts casualties, groundings,
spills and regulator action, new rules entering force, record orders, rate
moves, and shipping-lane disruption. Routine regional items, corporate
financials and cruise news are rejected. If nothing qualifies the run fails
cleanly rather than inventing a story.

## Architecture

```
research ──▶ scriptwriter ──▶ [length window check] ──▶ render ──▶ post ──▶ done
                                     │  ▲                        │
                                     ▼  │ loop                   ▼
                                   critic                    recovery
                              (LLM, only if outside       (LLM, only on
                               the 20-30s window)          Pexels/FFmpeg error)
                                                              │
                                                              └──▶ back to render
```

- **State** (`backend/app/state.py`) — the single `PipelineState` TypedDict every node reads/writes.
- **Agent 1 — Research** (`agents/research_agent.py`) — calls the code-only `fetch_trending_headlines()` tool (`tools/rss_tool.py`), which parses/dedupes RSS XML to ≤15 short strings *before* anything touches an LLM context window, then applies the marine-event selection rules.
- **Agent 2 — Scriptwriter** (`agents/scriptwriter_agent.py`) — Grok/xAI call under the Caveman/PAX standard (JSON-only, no filler) via `llm_client.py`, plus a deterministic word-count length estimate. Accuracy rules are enforced in the prompt: only facts present in the headline, no invented IMO numbers or clause references, no fault attribution, units on every number.
- **Agent 3 — Critic** (`agents/critic_agent.py`) — only invoked by `route_after_duration_check` when the estimate falls *outside* the 20–30s window in either direction. Capped at 2 revisions so it can never loop.
- **Agent 4 — Recovery** (`agents/recovery_agent.py`) — only when `render/ffmpeg_render.py` raises a `RenderError`. Returns a new `image_query` and the graph routes back to `render`.
- **Routing** — every edge in `graph.py` is plain Python (`route_after_*`). No LLM is ever asked "what should happen next."

## Length guarantee

The output is **always 20–30s**. This is enforced twice, because the cheap check
isn't accurate enough to be trusted alone:

1. **Graph gate** — word count ÷ 2.4 must land in the window, else the Critic runs.
2. **Render node** — narration is synthesized first, then *measured*. `plan_duration()`
   picks an `atempo` factor (0.85–1.50) and, if the narration is still too short, a
   frozen tail hold; if it's too long to fit by pacing, the mux is hard-trimmed to
   the ceiling. Every stock clip is trimmed to its own beat's corrected narration
   length, so the video length tracks the audio instead of running 2–3× over.

## Narration and captions

`render/tts.py` synthesizes **each beat separately** — that's what lets the render
know per-beat durations. `edge-tts` is free and needs no key; its `WordBoundary`
events give per-word timings, which `render/captions.py` groups into short cues
and writes as a styled ASS file that libass burns in at 1080×1920. Caption timings
are rescaled by the same tempo factor applied to the audio.

## Backend setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill in your Groq, Pexels, Facebook, LinkedIn keys
python -m uvicorn app.server:app --reload --port 8000
```

Running from the repo root instead also works:
`$env:PYTHONPATH="backend"; python -m uvicorn app.server:app --port 8000`

Requires `ffmpeg` on PATH — `scoop install ffmpeg` (Windows), `brew install ffmpeg`
(macOS), `apt install ffmpeg` (Linux). The render node resolves the binary up front
and raises a `RenderError` with install instructions if it's missing.

`GROQ_API_KEY` (Groq) or `GROK_API_KEY` (xAI) selects the LLM provider; the base
URL and model default to whichever is present.

## Daily automation

Set `DAILY_RUN_ENABLED=true` plus `DAILY_RUN_HOUR` / `DAILY_RUN_MINUTE`, and an
in-process APScheduler cron fires the pipeline on the FastAPI lifespan. No Task
Scheduler, no cron, no second service. `DAILY_RUN_TIMEZONE` must be an IANA name
(`Asia/Kolkata`) — Windows zone ids like `India Standard Time` raise
`ZoneInfoNotFoundError`. `GET /schedule` reports the armed job and next run.

## Dashboard setup

```bash
cd dashboard
npm install
npm run dev   # http://localhost:5173, proxies /api and /ws to :8000
```

Click **Run Pipeline**. The dashboard opens a WebSocket per run and streams every
state mutation and log line live. The **Runs** column lists every run via
`GET /runs`; click one to pull its state and full log back via `GET /runs/{run_id}`.
The active run id is kept in `localStorage`, so reloading resumes the run you were
watching, and a dropped WebSocket reconnects with backoff.

## Notes on what's live vs. stubbed

- **Research / RSS**: real, hits the maritime feeds in `config.py` (or `RSS_FEEDS`).
- **Scriptwriter / Critic / Recovery**: real LLM calls via the OpenAI-compatible API.
- **Narration**: real edge-tts. Requires network access to Microsoft's speech service.
- **Render**: real Pexels lookup + real local `ffmpeg` (needs libass for captions).
- **Facebook / LinkedIn posting**: real Graph/Video API calls, gated behind your own
  tokens. If a token is missing or a call fails, the error lands in `error_log` on
  the dashboard rather than crashing the run — the reel still renders.
- **LinkedIn upload is chunked, not a single PUT.** The Videos API splits the file
  into 4 MiB parts and returns one `uploadInstructions` entry per part. You must
  PUT each part to its own URL, keep the `ETag` from each response, then call
  `finalizeUpload` with those ids in order. Sending the whole file to the first
  `uploadUrl` fails with **413 Payload Too Large** on any reel over 4 MiB — which
  is all of them.

## Extending

- Add feeds: edit `RSS_FEEDS` in `.env` (comma-separated) or `DEFAULT_RSS_FEEDS` in `config.py`.
- Change reel length: `MIN_REEL_SECONDS` / `TARGET_REEL_SECONDS` / `MAX_REEL_SECONDS`.
- Change voice: `TTS_VOICE` to any Edge neural voice name.
- New platform (e.g. Instagram): add `social/instagram_post.py` with a
  `post_reel_to_instagram(path, caption) -> url` function and call it from `post_node`.
- Approval workflow before auto-posting: `post_node` in `graph.py` is the single
  place that publishes.

# Wire Room — Daily Maritime News-Reel Pipeline

A LangGraph state machine (Python) plus a React control-room dashboard. It picks **one major marine-industry event a day**, writes a narration, renders a 20–30s vertical reel with burned-in captions, and posts it to Facebook and LinkedIn — but only after a human approves it.

---

## Table of Contents

1. [What It Does](#1-what-it-does)
2. [Tech Stack](#2-tech-stack)
3. [Repository Layout](#3-repository-layout)
4. [The Pipeline at a Glance](#4-the-pipeline-at-a-glance)
5. [How the Agents Work](#5-how-the-agents-work)
6. [How State Flows Between Agents](#6-how-state-flows-between-agents)
7. [LLM Token Usage](#7-llm-token-usage)
8. [The Length Guarantee](#8-the-length-guarantee)
9. [Narration and Captions](#9-narration-and-captions)
10. [The Human Approval Gate](#10-the-human-approval-gate)
11. [Backend Setup](#11-backend-setup)
12. [Frontend Setup](#12-frontend-setup)
13. [Daily Automation](#13-daily-automation)
14. [API Reference](#14-api-reference)
15. [Live vs. Stubbed](#15-live-vs-stubbed)
16. [Configuration Reference](#16-configuration-reference)
17. [Extending the System](#17-extending-the-system)
18. [Troubleshooting](#18-troubleshooting)

---

## 1. What It Does

1. **Reads** 9 verified maritime RSS feeds.
2. **Filters** them in plain Python down to ≤15 short headlines — before any LLM context is spent.
3. **Picks one story** that qualifies as a major marine event, or fails the run cleanly.
4. **Writes** a 4-beat voiceover script (hook → context → payoff → cta).
5. **Renders** a 1080×1920 vertical MP4: TTS narration, Pexels stock footage, burned-in captions.
6. **Guarantees** the final file lands inside 20–30 seconds.
7. **Waits** for a human to approve or reject it on the dashboard.
8. **Posts** to Facebook and LinkedIn only after approval.

**Domain covered:** shipping, logistics & cargo, crew/safety, classification, and offshore energy.


**What counts as a "major marine event":**
- Casualty, grounding, collision, sinking, fire or explosion on a vessel
- Spill, pollution, or a regulator / port-state-control action
- A law, sanction, IMO/EU measure or rule entering or proposed into force
- Record-breaking order, delivery, charter, or rate move
- Significant port, canal, or shipping-lane disruption
- Sanctions, seizures, or force involving commercial shipping
- Major offshore wind / subsea / OSV project decision or milestone

**What gets rejected:** routine regional items, opinion pieces, corporate financials with no operational impact, and cruise/tourism news. If nothing qualifies, the run fails — it never invents a story.

---

## 2. Tech Stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph `StateGraph` |
| LLM | Groq (default) or xAI/Grok — OpenAI-compatible API |
| Narration | `edge-tts` (free, no API key) |
| Footage | Pexels Video API |
| Rendering | Local `ffmpeg` (needs libass for captions) |
| API server | FastAPI + WebSocket |
| Scheduling | APScheduler (in-process cron) |
| Dashboard | React 18 + Vite |

---

## 3. Repository Layout

```
backend/
  app/
    graph.py                  # Pipeline wiring + all routing logic
    state.py                  # PipelineState — the single shared object
    config.py                 # All settings, resolved from .env
    llm_client.py             # OpenAI-compatible JSON-only LLM wrapper
    media.py                  # Where finished reels are stored
    scheduler.py              # APScheduler daily job
    server.py                 # FastAPI routes + WebSocket streaming
    agents/
      research_agent.py       # Agent 1 — picks the story
      scriptwriter_agent.py   # Agent 2 — writes the narration
      critic_agent.py         # Agent 3 — fixes length (runs rarely)
      recovery_agent.py       # Agent 4 — fixes render errors (runs rarely)
    tools/
      rss_tool.py             # Pure-Python RSS parse + dedupe
      pexels_tool.py          # Stock footage lookup
    render/
      tts.py                  # Per-beat speech synthesis
      captions.py             # Word timings -> ASS subtitle file
      ffmpeg_render.py        # Clip assembly, pacing, mux
    social/
      facebook_post.py        # Graph API upload
      linkedin_post.py        # Videos API chunked upload
  requirements.txt
  .env.example

frontend/
  src/
    App.jsx                   # Main shell
    api.js                    # REST + WebSocket client
    components/
      RunList.jsx             # Every run, newest first
      GraphFlow.jsx           # Live pipeline node diagram
      StateViewer.jsx         # Raw state per node
      LogPanel.jsx            # Streaming log lines
      ReelPlayer.jsx          # Plays the finished reel
      ApprovalCard.jsx        # Approve / Reject with caption edit
  vite.config.js
```

---

## 4. The Pipeline at a Glance

```
  research ──▶ scriptwriter ──▶ [length check] ──▶ render ──▶ approval ──▶ END
                  ▲                   │ ▲            │                        │
                  │                   │ │            │                        │
             (revise, max 2)      critic │            ▼                        │
                  │                   └──────┘      recovery                     │
                  └────────────────────────────────────┘                       │
                                                                               │
                                                       publish_node ◀──────────┘
                                                       (called by API on approve)
```

**Node order:**

1. `research` — always runs first.
2. `scriptwriter` — always runs after a successful research.
3. **Deterministic length check** — plain Python, no LLM. Decides the next step.
4. `critic` — **only** if the check failed. Loops back at most 2 times.
5. `render` — deterministic render. On failure it does not crash; it flags state.
6. `recovery` — **only** if render raised an error. Loops back to render.
7. `approval` — terminal. Waits for a human.
8. `publish_node` — **not a graph node.** A plain function the API calls on approve.

---

## 5. How the Agents Work

Four LLM agents exist. **Two of them run on every successful pipeline; two almost never run at all.** All four return strict JSON and nothing else.

### Agent 1 — Research (`agents/research_agent.py`)

1. Calls `fetch_trending_headlines()` — **pure Python, no LLM**. It parses ~200 RSS entries and dedupes them down to ≤15 short strings. This keeps raw XML out of the context window entirely.
2. Sends only those 15 strings to the LLM with a domain-locked selection prompt.
3. The LLM returns `{"selected_story_id": "...", "reason": "..."}`.

**Fails cleanly** (no story invented) when:
- No feed returned any headline.
- The model returns `"none"` — nothing qualified.
- The model picks an unknown story id.

### Agent 2 — Scriptwriter (`agents/scriptwriter_agent.py`)

1. Receives one headline.
2. Writes a 4-beat script: `hook`, `context`, `payoff`, `cta`. Each beat carries a voiceover line and a 2–4 word stock-footage search query.
3. Computes duration itself, in Python: `word_count ÷ 2.4`. No extra LLM call is needed to decide whether the Critic should run.

**Accuracy rules enforced in the prompt** (this content names real vessels and regulators):
- Only facts present in the headline. No invented IMO numbers, tonnage, dates, locations, prices, or casualty counts.
- Never allege fault or blame a named company or person.
- Every number carries its unit.
- The cta invites a professional action, never "like and follow".

### Agent 3 — Critic (`agents/critic_agent.py`)

1. **Invoked only** when the word-count estimate falls outside 20–30s, in either direction.
2. Rewrites the script to hit the 25s target — cutting descriptive filler if too long, expanding facts already present if too short.
3. Hard cap of **2 revisions** (`MAX_REVISIONS`). After that it force-passes so the graph can never loop.

> Inside the window, this agent costs **zero tokens**. That is the point of it.

### Agent 4 — Recovery (`agents/recovery_agent.py`)

1. **Invoked only** when `render` raises a `RenderError` (Pexels 404, FFmpeg failure).
2. Reads the raw error string and returns either a new `image_query` or an FFmpeg parameter change.
3. The graph routes straight back to `render`.
4. Hard cap of **3 attempts** (`MAX_RECOVERY_ATTEMPTS`), then the run fails.

### Routing: zero LLM cost

- Every edge in `graph.py` is a plain Python function named `route_after_*`.
- The LLM is **never** asked "what should happen next."
- It only ever answers questions about *content* — which story, how to shorten, how to fix.

---

## 6. How State Flows Between Agents

- `PipelineState` (`backend/app/state.py`) is the single `TypedDict` every node reads from and writes to.
- Nodes **never call each other.** They return a partial dict; LangGraph merges it back into the state.
- All cross-node data travels through state, which is why the dashboard can stream every mutation live.

**Lifecycle of `status`:**

`researching` → `writing` → `reviewing` → `rendering` → `recovering` → `awaiting_approval` → `posting` → `done`

Terminal alternatives: `rejected`, `failed`.

---

## 7. LLM Token Usage

There are exactly **4 places in the codebase that call an LLM** — one per agent, all through `llm_client.py`. Everything else is plain Python.

> **A normal successful run spends 2 LLM calls. The worst case is 7.**

### Consumes tokens

| Node | Calls | When tokens are spent | Weight per call |
|---|---|---|---|
| `research` | 1 | Only if RSS returned at least one headline. Zero if the feeds came back empty — it fails before calling. | small |
| `scriptwriter` | 1 | Always, once research succeeded. | medium |
| `critic` | 0–2 | **Zero if the word-count estimate already lands in 20–30s.** Otherwise one call per revision. | large |
| `recovery` | 0–3 | **Zero unless render raised a `RenderError`.** Otherwise one call per failure. | small |

**Read the `Weight` column this way:** Research and Scriptwriter are the fixed cost of every run. Critic and Recovery are the *variable* cost — and both are designed to usually be zero. A run that needs no rewrite and no error fix costs the same as one that never touched the graph twice.

### Costs nothing — pure Python

- **RSS fetch, parse, dedupe** — `tools/rss_tool.py` reduces ~200 entries to ≤15 strings before any LLM is involved. This is why raw XML never reaches a context window.
- **The duration estimate** — `word_count ÷ 2.4`, a one-line calculation.
- **All routing** — every `route_after_*` function in `graph.py`. The LLM is never asked what happens next.
- **The entire render node** — TTS, Pexels lookup, ffmpeg, caption generation, the `atempo` pacing factor, the tail hold, and the final trim. `render/ffmpeg_render.py` is pure code by design.
- **The approval gate** — no LLM decides whether to post.
- **Publishing** — `publish_node` and its default caption are plain string formatting.

### How the design keeps the bill low

1. **Filter before you prompt.** Dedupe to 15 short strings in Python, so the model reads a summary instead of raw XML.
2. **Never use an LLM for control flow.** Routing is Python, so a malformed decision can neither loop the graph nor spend tokens discovering the next step.
3. **Fix length with audio filters, not rewrites.** If narration is off, the render node changes `atempo` or adds a tail hold rather than asking a model to rewrite the script.
4. **Stop at the human gate.** A run that sits at `awaiting_approval` spends nothing further, no matter how long it waits.

### Per-call cost notes

- `CAVEMAN_SYSTEM_SUFFIX` (`llm_client.py:17`) is appended to **every** system prompt, so that overhead is paid on each of the 2–7 calls a run makes.
- The Critic is the heaviest call in the pipeline: `critic_agent.py:77` re-sends the entire current script on every revision, so its cost scales with how wrong the first draft was.

### Two caveats, stated as current behaviour

- **Output length is uncapped.** The request payload in `llm_client.py:45` sets no `max_tokens`, so the JSON-only instruction is the only guard against a verbose model.
- **There is no retry.** If a model returns malformed JSON, `json.loads` raises at `llm_client.py:64`, nothing catches it, and the run ends as `failed` — the tokens are spent and there is no second attempt.

---

## 8. The Length Guarantee

The output is **always 20–30s**. It is enforced twice, because the cheap check is not accurate enough to trust alone.

1. **Graph gate** — `word_count ÷ 2.4` must land in the window, else the Critic runs.
2. **Render node** — the narration is synthesized first, then *measured*.
   - `plan_duration()` picks an `atempo` factor between 0.85 and 1.50.
   - If the narration is still too short, a frozen tail hold pads it to the minimum.
   - If it is too long to fit by pacing alone, the mux is hard-trimmed to the ceiling.
   - Every stock clip is trimmed to its own beat's corrected narration length — so the video tracks the audio instead of running 2–3× over.

---

## 9. Narration and Captions

- `render/tts.py` synthesizes **each beat separately.** That is what lets the render know per-beat durations.
- `edge-tts` is free and needs no API key.
- Its `WordBoundary` events give per-word timings.
- `render/captions.py` groups those into short cues and writes a styled **ASS** file, which libass burns in at 1080×1920.
- Caption timings are rescaled by the same tempo factor applied to the audio.

---

## 10. The Human Approval Gate

Nothing reaches a social platform automatically.

- `approval_gate_node` (`graph.py:70`) is a deliberate dead end. It sets `status = "awaiting_approval"` and the graph ends.
- Publishing is **not** a graph node. `publish_node` (`graph.py:88`) is a plain function — being called at all *is* the approval.
- Only `POST /runs/{run_id}/approve` calls it, and only after a run is parked at the gate.
- Because publishing is outside the graph, no reroute or retry can skip the human.
- `POST /runs/{run_id}/reject` keeps the reel on the dashboard but never sends it anywhere.

Each platform is attempted independently, so one bad token lands in `error_log` without hiding a post that succeeded.

---

## 11. Backend Setup

**Requirements:** Python 3.10+ and `ffmpeg` on your `PATH`.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill in your Groq, Pexels, Facebook, LinkedIn keys
python -m uvicorn app.server:app --reload --port 8000
```

Running from the repo root works too:

```bash
$env:PYTHONPATH="backend"; python -m uvicorn app.server:app --port 8000
```

**Install `ffmpeg`:**
- Windows — `scoop install ffmpeg`
- macOS — `brew install ffmpeg`
- Linux — `apt install ffmpeg`

The render node resolves the binary up front and raises a `RenderError` with install instructions if it is missing.

---

## 12. Frontend Setup

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173, proxies /api and /ws to :8000
```

**How to use it:**
1. Click **Run Pipeline**. The dashboard opens a WebSocket for that run and streams every state mutation and log line live.
2. Watch the pipeline fill in on the node diagram, then read the logs and the raw state per node.
3. The finished reel appears in the player. Edit the caption if you want, then **Approve** or **Reject**.
4. The **Runs** list is served by `GET /runs`. Click any run to pull its full state and log back via `GET /runs/{run_id}`.
5. The active run id is kept in `localStorage`, so reloading resumes the run you were watching, and a dropped WebSocket reconnects with backoff.

---

## 13. Daily Automation

- Set `DAILY_RUN_ENABLED=true` plus `DAILY_RUN_HOUR` and `DAILY_RUN_MINUTE`.
- An in-process APScheduler cron fires the pipeline on the FastAPI lifespan.
- **No** Task Scheduler, **no** system cron, **no** second service.
- `DAILY_RUN_TIMEZONE` must be an **IANA** name (`Asia/Kolkata`). Windows zone ids like `India Standard Time` raise `ZoneInfoNotFoundError`.
- `GET /schedule` reports the armed job, the next run, the length window, the voice, the feed count, and which platforms are configured.

---

## 14. API Reference

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/runs` | Start a manual run. Returns `run_id`. |
| `GET` | `/runs` | List all runs, newest first. |
| `GET` | `/runs/{run_id}` | Full state snapshot + complete log. |
| `POST` | `/runs/{run_id}/approve` | **The human gate.** Queues the upload. Optional body: `{"caption": "...", "note": "..."}`. |
| `POST` | `/runs/{run_id}/reject` | Discard. Keeps the reel local. Optional body: `{"note": "..."}`. |
| `GET` | `/schedule` | Scheduler state, length window, voice, feeds, ready platforms. |
| `WS` | `/ws/{run_id}` | Live state + log stream. Sends a full snapshot on connect. |
| `GET` | `/media/reels/...` | Static mount for finished MP4s. |

---

## 15. Live vs. Stubbed

| Component | Status | Notes |
|---|---|---|
| Research / RSS | **Real** | Hits the maritime feeds in `config.py` or `RSS_FEEDS`. |
| Scriptwriter / Critic / Recovery | **Real** | LLM calls via the OpenAI-compatible API. |
| Narration | **Real** | edge-tts. Needs network access to Microsoft's speech service. |
| Render | **Real** | Pexels lookup + local `ffmpeg`. Captions need libass. |
| Facebook posting | **Real** | Graph API, gated behind your own Page token. |
| LinkedIn posting | **Real** | Videos API, gated behind your own token. |
| Approval gate | **Real** | Blocking human decision via the API. |

A missing or failing platform token logs to `error_log` on the dashboard rather than crashing the run — **the reel still renders.**

> **LinkedIn uploads are chunked, not a single PUT.** The Videos API splits the file into 4 MiB parts and returns one `uploadInstructions` entry per part. You must PUT each part to its own URL, keep the `ETag` from each response, then call `finalizeUpload` with those ids in order. Sending the whole file to the first `uploadUrl` fails with **413 Payload Too Large** on any reel over 4 MiB — which is all of them.

---

## 16. Configuration Reference

All settings live in `backend/.env`. See `.env.example` for the annotated template.

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | — | Groq key. Takes precedence if present. |
| `GROK_API_KEY` | — | xAI/Grok key. Use instead of Groq. |
| `GROQ_MODEL` / `GROK_MODEL` | provider default | Override the chat model. |
| `PEXELS_API_KEY` | — | Stock footage lookup. |
| `FACEBOOK_APP_ID` / `_PAGE_ID` / `_PAGE_ACCESS_TOKEN` | — | Facebook Graph posting. |
| `LINKEDIN_MEMBER_ID` / `_ACCESS_TOKEN` | — | LinkedIn personal profile posting. |
| `LINKEDIN_ORG_URN` | — | Use instead for an organization page. |
| `MIN_REEL_SECONDS` | `20` | Lower bound of the length window. |
| `TARGET_REEL_SECONDS` | `25` | What the script aims for. |
| `MAX_REEL_SECONDS` | `30` | Upper bound. |
| `WORDS_PER_SECOND` | `2.4` | Used by the deterministic estimate. |
| `TTS_VOICE` | `en-GB-SoniaNeural` | Any Edge neural voice name. |
| `TTS_RATE` | `+8%` | Speech rate. |
| `CAPTIONS_ENABLED` | `true` | Burn-in on/off. |
| `CAPTION_FONT` | `arialbd.ttf` | Path to the caption font file. |
| `DAILY_RUN_ENABLED` | `false` | Turns the daily cron on. |
| `DAILY_RUN_HOUR` / `_MINUTE` | `8` / `0` | When the daily run fires. |
| `DAILY_RUN_TIMEZONE` | `UTC` | **IANA** name, e.g. `Asia/Kolkata`. |
| `RSS_FEEDS` | 9 maritime feeds | Comma-separated override. |
| `PORT` | `8000` | Server port. |

---

## 17. Extending the System

- **Add feeds** — set `RSS_FEEDS` in `.env` (comma-separated), or edit `DEFAULT_RSS_FEEDS` in `config.py`.
- **Change reel length** — adjust `MIN_REEL_SECONDS` / `TARGET_REEL_SECONDS` / `MAX_REEL_SECONDS`.
- **Change voice** — set `TTS_VOICE` to any Edge neural voice name.
- **Add a platform (e.g. Instagram)** — add `social/instagram_post.py` exposing `post_reel_to_instagram(path, caption) -> url`, then add it to the `targets` tuple in `publish_node` (`graph.py:101`).
- **Change publishing rules** — `publish_node` (`graph.py:88`) is the single place anything is uploaded. It is deliberately outside the graph so the approval gate cannot be bypassed.
- **Add an agent** — write a node returning a partial `PipelineState` dict, register it in `build_graph()`, and add a `route_after_*` function. Never let an LLM decide the next node.

---

## 18. Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `ffmpeg not found` on render | Install ffmpeg and put it on `PATH`. |
| Run fails at research with "No major marine industry event found" | Genuinely no qualifying story today. The run failed rather than inventing one. This is correct behaviour. |
| Captions missing | ffmpeg was built without libass, or `CAPTIONS_ENABLED=false`. |
| LinkedIn returns **413** | The uploader is not chunking. See the note in [§15](#15-live-vs-stubbed). |
| `ZoneInfoNotFoundError` on scheduler start | `DAILY_RUN_TIMEZONE` is a Windows zone id. Use `Asia/Kolkata`. |
| Approve returns **409** | The run is not at `status: awaiting_approval`, has no finished reel, or is already publishing. |
| Dashboard reconnects repeatedly | Backend is not on `:8000`, or the run id in `localStorage` no longer exists — the snapshot replay clears it. |
| TTS fails | No network access to Microsoft's speech service. |

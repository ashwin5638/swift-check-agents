import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import media, scheduler as scheduler_module
from app.graph import build_graph, publish_node

_runs: dict[str, dict[str, Any]] = {}          # run_id -> latest state
_run_events: dict[str, list[dict]] = {}         # run_id -> log lines
_subscribers: dict[str, list[WebSocket]] = {}
_publishing: set[str] = set()                   # run_ids with an upload in flight


def log_event(node: str, message: str) -> None:
    """Broadcast to every open dashboard, not tied to any one run."""
    entry = {"ts": time.time(), "node": node, "message": message}
    for run_id in list(_subscribers):
        _run_events.setdefault(run_id, []).append(entry)
    print(f"[{node}] {message}")


async def _broadcast(run_id: str, payload: dict) -> None:
    for ws in list(_subscribers.get(run_id, [])):
        try:
            await ws.send_json(payload)
        except Exception:
            _unsubscribe(run_id, ws)


async def _run_pipeline(run_id: str, trigger: str = "manual") -> None:
    state: dict = {
        "run_id": run_id,
        "status": "researching",
        "error_log": [],
        "trigger": trigger,
    }
    _runs[run_id] = state
    _log(run_id, "system", f"Run started ({trigger})")
    await _broadcast(run_id, {"type": "state", "state": state})
    await _broadcast(run_id, {"type": "log", "entry": _run_events[run_id][-1]})

    try:
        async for step in _graph.astream(state):
            node_name, patch = next(iter(step.items()))
            state = {**state, **patch}
            _runs[run_id] = state
            _log(run_id, node_name, f"completed -> status={state.get('status')}")
            await _broadcast(run_id, {"type": "state", "state": state})
            await _broadcast(run_id, {"type": "log", "entry": _run_events[run_id][-1]})
    except Exception as e:  # noqa: BLE001
        state["status"] = "failed"
        _log(run_id, "system", f"Fatal error: {e}")
        await _broadcast(run_id, {"type": "state", "state": state})
        await _broadcast(run_id, {"type": "log", "entry": _run_events[run_id][-1]})


_graph = build_graph()


def _start_run(trigger: str = "manual") -> str:
    run_id = str(uuid.uuid4())
    _runs[run_id] = {"status": "queued", "trigger": trigger}
    _run_events[run_id] = []
    asyncio.create_task(_run_pipeline(run_id, trigger))
    return run_id


@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler_module.start(_start_run)
    try:
        yield
    finally:
        scheduler_module.shutdown()


app = FastAPI(title="Agentic Reel Pipeline", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Finished reels, so the dashboard can play what it is about to approve.
app.mount(media.MEDIA_MOUNT, StaticFiles(directory=media.MEDIA_ROOT), name="reels")


def _log(run_id: str, node: str, message: str) -> None:
    entry = {"ts": time.time(), "node": node, "message": message}
    _run_events.setdefault(run_id, []).append(entry)


def _snapshot(run_id: str) -> dict[str, Any]:
    """
    One authoritative frame of a run. Served by GET /runs/{run_id} and used
    as the single replay frame when a WebSocket attaches, so a late or
    reconnecting dashboard can *replace* its state instead of appending a
    duplicate log stream.
    """
    return {
        "type": "snapshot",
        "state": _runs.get(run_id, {}),
        "logs": _run_events.get(run_id, []),
    }


def _run_summary(run_id: str, state: dict[str, Any]) -> dict[str, Any]:
    events = _run_events.get(run_id, [])
    story = state.get("selected_story") or {}
    render = state.get("render_result") or {}
    return {
        "run_id": run_id,
        "status": state.get("status"),
        "trigger": state.get("trigger", "manual"),
        "created_at": events[0]["ts"] if events else None,
        "title": story.get("title") or state.get("script", {}).get("title"),
        "duration_sec": render.get("duration_sec"),
        "video_url": render.get("video_url") or "",
        "approval": (state.get("approval") or {}).get("decision", "pending"),
    }


def _unsubscribe(run_id: str, websocket: WebSocket) -> None:
    subscribers = _subscribers.get(run_id)
    if subscribers and websocket in subscribers:
        subscribers.remove(websocket)


async def _push_state(run_id: str, state: dict[str, Any], node: str, message: str) -> None:
    """Persist a state change, log it, and stream both to open dashboards."""
    _runs[run_id] = state
    _log(run_id, node, message)
    await _broadcast(run_id, {"type": "state", "state": state})
    await _broadcast(run_id, {"type": "log", "entry": _run_events[run_id][-1]})


async def _publish(run_id: str, caption: Optional[str]) -> None:
    """
    Upload a reel that has already been approved. Runs off the event loop
    because the platform adapters block for the length of a multi-MB
    upload, and streamed so every open dashboard sees each result.
    """
    try:
        patch = await asyncio.to_thread(publish_node, _runs[run_id], caption)
    except Exception as e:  # noqa: BLE001
        patch = {
            "status": "failed",
            "error_log": _runs[run_id].get("error_log", [])
            + [{"node": "post", "message": str(e), "resolved": False}],
        }
    finally:
        _publishing.discard(run_id)

    urls = (patch.get("social_post_urls") or {})
    await _push_state(
        run_id,
        {**_runs[run_id], **patch},
        "post",
        f"Published to {', '.join(urls) if urls else 'no platform'}",
    )


class DecisionRequest(BaseModel):
    caption: Optional[str] = None
    note: Optional[str] = None


def _awaiting(run_id: str) -> dict[str, Any]:
    """Fetch a run that is parked at the approval gate, or explain why not."""
    state = _runs.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Unknown run {run_id}")
    if state.get("status") != "awaiting_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Run is not awaiting approval (status={state.get('status')})",
        )
    return state


@app.post("/runs")
async def start_run():
    return {"run_id": _start_run("manual")}


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    if run_id not in _runs:
        raise HTTPException(status_code=404, detail=f"Unknown run {run_id}")
    return _snapshot(run_id)


@app.post("/runs/{run_id}/approve")
async def approve_run(run_id: str, payload: Optional[DecisionRequest] = None):
    """
    The human gate. Returns as soon as the upload is queued — results
    stream to the dashboard over the run's WebSocket.
    """
    state = _awaiting(run_id)
    render = state.get("render_result") or {}
    if render.get("status") != "success" or not render.get("output_path"):
        raise HTTPException(status_code=409, detail="This run has no finished reel")
    if run_id in _publishing:
        raise HTTPException(status_code=409, detail="Already publishing this run")

    caption = (payload.caption if payload else None) or None
    _publishing.add(run_id)
    await _push_state(
        run_id,
        {
            **state,
            "status": "posting",
            "approval": {
                "decision": "approved",
                "decided_at": time.time(),
                "note": payload.note if payload else None,
                "caption": caption,
            },
        },
        "approve",
        f"Approved by admin{f' with caption {caption!r}' if caption else ''} — publishing",
    )
    asyncio.create_task(_publish(run_id, caption))
    return {"run_id": run_id, "status": "posting"}


@app.post("/runs/{run_id}/reject")
async def reject_run(run_id: str, payload: Optional[DecisionRequest] = None):
    """Keeps the reel on the dashboard but never sends it anywhere."""
    state = _awaiting(run_id)
    note = (payload.note if payload else None) or None
    await _push_state(
        run_id,
        {
            **state,
            "status": "rejected",
            "approval": {
                "decision": "rejected",
                "decided_at": time.time(),
                "note": note,
                "caption": None,
            },
        },
        "reject",
        f"Rejected by admin{f': {note}' if note else ''} — not published",
    )
    return {"run_id": run_id, "status": "rejected"}


@app.get("/runs")
async def list_runs():
    summaries = [_run_summary(rid, s) for rid, s in _runs.items()]
    summaries.sort(key=lambda r: r["created_at"] or 0, reverse=True)
    return summaries


@app.get("/schedule")
async def get_schedule():
    """Daily automation state, so the dashboard can show the next run."""
    from app.config import settings

    return {
        **scheduler_module.describe(),
        "length_window": [
            settings.min_reel_seconds,
            settings.max_reel_seconds,
        ],
        "voice": settings.tts_voice,
        "captions": settings.captions_enabled,
        "feeds": len(settings.rss_feeds),
        "platforms": [
            name
            for name, ready in (
                (
                    "facebook",
                    bool(settings.facebook_page_id and settings.facebook_access_token),
                ),
                (
                    "linkedin",
                    bool(settings.linkedin_author_urn and settings.linkedin_access_token),
                ),
            )
            if ready
        ],
    }


@app.websocket("/ws/{run_id}")
async def ws_run(websocket: WebSocket, run_id: str):
    await websocket.accept()
    _subscribers.setdefault(run_id, []).append(websocket)

    # Replay what's happened so far so a late-connecting dashboard catches up.
    if run_id in _runs:
        await websocket.send_json(_snapshot(run_id))

    try:
        while True:
            await websocket.receive_text()  # dashboard sends nothing; keeps conn open
    except WebSocketDisconnect:
        _unsubscribe(run_id, websocket)

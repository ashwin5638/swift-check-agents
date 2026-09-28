"""
Agent 4 — Recovery Agent (Error Handler)

Takes one raw error string (e.g. "Pexels returned 404 for query:
'abstract global warming'" or an FFmpeg stderr tail) and returns a
state mutation the graph can route back into rendering with. This
agent never emits chat text — only a JSON patch.
"""

from app.llm_client import get_client
from app.state import PipelineState

SYSTEM_PROMPT = """You are a recovery agent for a video-rendering
pipeline. You will get one error string from either the Pexels stock
video API or FFmpeg. Diagnose the likely cause and propose the
smallest fix that lets the pipeline retry successfully.

- If the error mentions Pexels/404/query, propose a broader or more
  literal replacement search query (avoid abstract/metaphorical terms
  stock libraries rarely have footage for).
- If the error mentions FFmpeg, propose a safe parameter change
  (e.g. drop an unsupported filter, reduce resolution, fix a codec).

Return JSON exactly shaped as:
{"fix_type": "image_query" | "ffmpeg_param", "value": "<the new value>", "note": "<max 10 words>"}"""

MAX_RECOVERY_ATTEMPTS = 3


def recovery_node(state: PipelineState, error_message: str) -> dict:
    attempts = state.get("recovery_attempts", 0) + 1
    error_log = state.get("error_log", []) + [
        {"node": "render", "message": error_message, "resolved": False}
    ]

    if attempts > MAX_RECOVERY_ATTEMPTS:
        error_log[-1]["resolved"] = False
        return {
            "error_log": error_log,
            "recovery_attempts": attempts,
            "status": "failed",
        }

    client = get_client()
    fix = client.json_completion(SYSTEM_PROMPT, user_prompt=error_message)
    error_log[-1]["resolved"] = True

    patch: dict = {
        "error_log": error_log,
        "recovery_attempts": attempts,
        "status": "rendering",
    }

    if fix["fix_type"] == "image_query":
        render_result = dict(state.get("render_result", {}))
        render_result["status"] = "pending"
        render_result["image_query_used"] = fix["value"]
        patch["render_result"] = render_result

    return patch

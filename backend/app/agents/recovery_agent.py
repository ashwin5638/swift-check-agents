"""
Agent 4 — Recovery Agent (Error Handler)

Takes one raw error string (e.g. "Pexels returned 404 for query:
'abstract global warming'") and returns a state mutation the graph can route
back into rendering with. The only fix it can apply is a replacement footage
query: the render node's ffmpeg parameters are fixed, so anything else would
be discarded and only burn a retry.
"""

from app.llm_client import get_client
from app.state import PipelineState

SYSTEM_PROMPT = """You are a recovery agent for a video-rendering
pipeline. You will get one error string from the Pexels stock video API.
Diagnose the likely cause and propose the smallest replacement search
query that lets the pipeline retry successfully.

Propose a broader or more literal query: stock libraries rarely have
footage for abstract or metaphorical terms (ships, ports, cranes, tankers,
offshore rigs, containers, open sea and weather all have plenty).

Return JSON exactly shaped as:
{"fix_type": "image_query", "value": "<the new query>", "note": "<max 10 words>"}"""

MAX_RECOVERY_ATTEMPTS = 3


def recovery_node(state: PipelineState, error_message: str) -> dict:
    attempts = state.get("recovery_attempts", 0) + 1
    error_log = state.get("error_log", []) + [
        {"node": "render", "message": error_message, "resolved": False}
    ]

    if attempts > MAX_RECOVERY_ATTEMPTS:
        return {
            "error_log": error_log,
            "recovery_attempts": attempts,
            "status": "failed",
        }

    client = get_client()
    fix = client.json_completion(SYSTEM_PROMPT, user_prompt=error_message)

    render_result = dict(state.get("render_result", {}))
    render_result["status"] = "pending"
    render_result["image_query_used"] = fix["value"]

    return {
        "error_log": [*error_log[:-1], {**error_log[-1], "resolved": True}],
        "recovery_attempts": attempts,
        "render_result": render_result,
        "status": "rendering",
    }

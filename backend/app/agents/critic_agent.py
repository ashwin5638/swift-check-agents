"""
Agent 3 — Critic / Refiner (Reflection Pattern)

IMPORTANT: this agent is only ever invoked via a conditional edge after
a deterministic, code-only length check (see route_after_duration_check).
No LLM call happens when the script already fits the time window.

The window has two edges. A script that is too long gets cut; one that is
too short gets built out with context that is already present in the
source. The Critic is never allowed to invent a reason to run.
"""

from app.config import settings
from app.llm_client import get_client
from app.state import PipelineState

SYSTEM_PROMPT = """You are a script editor for a 30-second vertical maritime
news reel. You will get a script and a target spoken duration in seconds.

Rewrite it so the spoken word count matches the target, keeping the same
4 beats (hook, context, payoff, cta).

ACCURACY RULES — this content names real vessels, operators and regulators:
- Use ONLY facts present in the current script. Never introduce a new
  figure, vessel name, IMO number, date, location, price or casualty count.
- Never allege fault or blame a named company or person.
- Keep correct maritime terminology and keep units on every number.
- If you must add words to reach the target, expand on facts already in the
  script (what it means operationally, who is affected). If you must cut,
  remove descriptive or hedging language, never a required fact.
- Keep the cta beat a specific professional prompt, never "like and follow",
  and never cite a specific clause or article number.

Return JSON exactly shaped as:
{
  "title": "<short title, max 6 words>",
  "beats": [
    {"beat": "hook", "voiceover": "...", "image_query": "..."},
    {"beat": "context", "voiceover": "...", "image_query": "..."},
    {"beat": "payoff", "voiceover": "...", "image_query": "..."},
    {"beat": "cta", "voiceover": "...", "image_query": "..."}
  ]
}"""

MAX_REVISIONS = 2


def _estimate_duration(voiceover_full: str) -> float:
    word_count = len(voiceover_full.split())
    return round(word_count / settings.words_per_second, 1)


def critic_node(state: PipelineState) -> dict:
    script = state["script"]
    current = script["est_duration_sec"]
    revision_count = state.get("critic_revision_count", 0) + 1

    if current > settings.max_reel_seconds:
        direction = "too long"
        target = settings.target_reel_seconds
        delta = round(current - settings.max_reel_seconds, 1)
        instruction = f"Cut about {delta}s of spoken text."
    else:
        direction = "too short"
        target = settings.target_reel_seconds
        delta = round(settings.min_reel_seconds - current, 1)
        instruction = (
            f"Add about {delta}s of spoken text using context already in the script."
        )

    client = get_client()
    result = client.json_completion(
        SYSTEM_PROMPT,
        user_prompt=(
            f"Current spoken duration: {current}s. Target: {target}s. {instruction}\n"
            f"Title: {script['title']}\n"
            f"Current script: {script}"
        ),
    )

    voiceover_full = " ".join(b["voiceover"] for b in result["beats"])
    duration = _estimate_duration(voiceover_full)

    revised_script = {
        "title": result["title"],
        "voiceover_full": voiceover_full,
        "beats": result["beats"],
        "est_duration_sec": duration,
    }

    # Force-pass after MAX_REVISIONS so the graph can never loop forever.
    # The render node still guarantees the final file lands in the window.
    in_window = (
        settings.min_reel_seconds <= duration <= settings.max_reel_seconds
    )
    passed = in_window or revision_count >= MAX_REVISIONS

    return {
        "script": revised_script,
        "duration_check_passed": passed,
        "critic_revision_count": revision_count,
        "critic_direction": direction,
        "status": "reviewing",
    }

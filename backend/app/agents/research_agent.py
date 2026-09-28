"""
Agent 1 — Research Agent (Tool Caller)

Never sees raw XML/HTML. It calls fetch_trending_headlines(), which
already filtered ~200 RSS entries down to <=15 short strings, then
reasons over just that array to pick one story.

Selection is domain-locked to major events in the marine industry:
shipping, logistics, offshore energy, maritime regulation and safety.
"""

from app.llm_client import get_client
from app.state import PipelineState
from app.tools.rss_tool import fetch_trending_headlines

SYSTEM_PROMPT = """You are an editor for a B2B maritime news reel that
runs daily for shipping and offshore-energy professionals. You will get a
JSON array of headlines, each with id, title, source. Pick the ONE story
that is a MAJOR EVENT in the marine industry today.

A story qualifies only if it involves one of:
- casualty, grounding, collision, sinking, fire or explosion on a vessel
- spill, pollution, or a regulator/port-state-control action
- a law, sanction, IMO/EU measure or rule entering into force or proposed
- a record-breaking order, delivery, charter, or rate move
- significant port, canal, or shipping-lane disruption
- sanctions, seizures, or force involving commercial shipping
- a major offshore wind / subsea / OSV project decision or milestone

REJECT anything that is routine, opinion-only, a small regional item,
corporate-financial trivia with no operational impact, or cruise/tourism
news. If nothing qualifies, return {"selected_story_id": "none"}.

Prefer events with clear visual potential and hard numbers.

Never invent details. Use only the headline text given to you.

Return JSON exactly shaped as:
{"selected_story_id": "<id or none>", "reason": "<max 12 words>"}"""


def research_node(state: PipelineState) -> dict:
    headlines = fetch_trending_headlines()

    if not headlines:
        return {
            "raw_headlines": [],
            "status": "failed",
            "error_log": state.get("error_log", []) + [
                {"node": "research_agent", "message": "No headlines returned from any RSS feed", "resolved": False}
            ],
        }

    client = get_client()
    result = client.json_completion(
        SYSTEM_PROMPT,
        user_prompt=str(headlines),
    )

    selected_id = result.get("selected_story_id")
    if not selected_id or selected_id == "none":
        return {
            "raw_headlines": headlines,
            "status": "failed",
            "error_log": state.get("error_log", []) + [
                {"node": "research_agent", "message": "No major marine industry event found in today's feeds", "resolved": False}
            ],
        }

    selected = next((h for h in headlines if h["id"] == selected_id), None)
    if selected is None:
        return {
            "raw_headlines": headlines,
            "status": "failed",
            "error_log": state.get("error_log", []) + [
                {"node": "research_agent", "message": f"Model picked unknown story id {selected_id!r}", "resolved": False}
            ],
        }

    return {
        "raw_headlines": headlines,
        "selected_story_id": selected["id"],
        "selected_story": selected,
        "selection_reason": result.get("reason", ""),
        "status": "writing",
    }

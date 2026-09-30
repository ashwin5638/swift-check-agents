"""
Agent 2 — Scriptwriter

Writes the narration for a 30-second vertical maritime news reel. The
output is spoken by a text-to-speech voice and burned in as captions, so
every line must be speakable and self-contained.

ACCURACY RULES (non-negotiable, this content names real vessels, operators
and regulators):
- Use ONLY facts present in the supplied headline. Never add an IMO number,
  a tonnage, a date, a location, a price or a casualty count that is not
  stated in the source.
- Never allege fault, negligence or blame a named company or person.
- Use correct maritime terminology (casualty, grounding, PSC detention,
  berth, teu, dwt, IMO, MR, tanker, container, feeder, FSO, SOV).
- If a number is used it must carry its unit.

The "Caveman Standard" (PAX protocol) applies: pure compressed JSON, no
conversational filler. Duration is computed here deterministically so the
graph's conditional edge doesn't need another LLM call to know whether
the Critic is needed.
"""

from app.config import settings
from app.llm_client import get_client
from app.state import PipelineState

SYSTEM_PROMPT = """You write voiceover scripts for short vertical news
reels about the marine industry, for an audience of shipowners, maritime
lawyers, port operators and offshore developers. The audience is
professional and time-poor: respect their knowledge, do not over-explain.

The finished reel is spoken aloud and must run between {min_sec} and
{max_sec} seconds. Aim for about {target_sec} seconds, which is roughly
{lo}-{hi} spoken words in total across all four beats.

Input is one maritime news headline. Produce a tight script with 4 beats:
hook, context, payoff, cta. Each beat needs one or two short spoken
sentences and a 2-4 word stock-footage search query for generic maritime
imagery (ships, ports, cranes, tankers, offshore rigs, containers, weather).

RULES:
- Only use facts contained in the headline. Do not add any figure, vessel
  name, IMO number, date or location that is not in the input.
- Do not blame or allege fault. Attribute to the source, not to opinion.
- Be specific and informative. No hype, no "shocking", no clickbait.
- Numbers must include their unit. Speak numbers the way a person says them.
- The cta beat must invite a specific professional response (reading the
  regulation, checking a charter party clause, reviewing a charter party),
  not "like and follow". Refer to clauses, articles or regulations
  generically — never cite a specific clause or article number, because you
  cannot know which one applies.

Return JSON exactly shaped as:
{{
  "title": "<short title, max 6 words>",
  "beats": [
    {{"beat": "hook", "voiceover": "...", "image_query": "..."}},
    {{"beat": "context", "voiceover": "...", "image_query": "..."}},
    {{"beat": "payoff", "voiceover": "...", "image_query": "..."}},
    {{"beat": "cta", "voiceover": "...", "image_query": "..."}}
  ]
}}"""


def _prompt() -> str:
    lo = int(settings.min_reel_seconds * settings.words_per_second)
    hi = int(settings.max_reel_seconds * settings.words_per_second)
    return SYSTEM_PROMPT.format(
        min_sec=int(settings.min_reel_seconds),
        max_sec=int(settings.max_reel_seconds),
        target_sec=int(settings.target_reel_seconds),
        lo=lo,
        hi=hi,
    )


def estimate_duration(voiceover_full: str) -> float:
    word_count = len(voiceover_full.split())
    return round(word_count / settings.words_per_second, 1)


def in_length_window(duration: float) -> bool:
    return settings.min_reel_seconds <= duration <= settings.max_reel_seconds


def scriptwriter_node(state: PipelineState) -> dict:
    story = state["selected_story"]
    client = get_client()

    result = client.json_completion(
        _prompt(),
        user_prompt=f"Headline: {story['title']}\nSource: {story['source']}",
    )

    duration = estimate_duration(" ".join(b["voiceover"] for b in result["beats"]))

    script = {
        "title": result["title"],
        "beats": result["beats"],
        "est_duration_sec": duration,
    }

    return {
        "script": script,
        "duration_check_passed": in_length_window(duration),
        "critic_revision_count": state.get("critic_revision_count", 0),
        "status": "reviewing",
    }

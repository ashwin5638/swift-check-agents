"""
Central State object for the LangGraph pipeline.

Every node reads a slice of this state and returns a partial dict of
mutations. LangGraph merges those mutations back into the state — nodes
never talk to each other directly, they only hand off through State.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict


class Headline(TypedDict):
    id: str
    title: str
    source: str


class ScriptBeat(TypedDict):
    beat: str          # e.g. "hook", "context", "payoff", "cta"
    voiceover: str
    image_query: str


class Script(TypedDict):
    title: str
    voiceover_full: str
    beats: list[ScriptBeat]
    est_duration_sec: float


class ErrorLogEntry(TypedDict):
    node: str
    message: str
    resolved: bool


class RenderResult(TypedDict):
    status: Literal["pending", "success", "failed"]
    output_path: Optional[str]        # durable on-disk path, safe to re-read
    video_url: Optional[str]          # /media/reels/... — what the dashboard plays
    image_query_used: Optional[str]
    duration_sec: Optional[float]      # final, guaranteed inside the window
    narration_sec: Optional[float]    # raw TTS length before tempo correction
    tempo: Optional[float]             # atempo factor applied to narration
    tail_hold_sec: Optional[float]     # frozen tail used to reach the minimum
    trimmed: bool                     # narration had to be cut to fit
    narrated: bool
    voice: Optional[str]
    caption_cues: int


class ApprovalGate(TypedDict):
    """
    The human gate between "reel exists" and "reel is public". Nothing
    reaches a social platform while `decision` is "pending".
    """
    decision: Literal["pending", "approved", "rejected"]
    decided_at: Optional[float]
    note: Optional[str]               # rejection reason, or approval remark
    caption: Optional[str]            # final caption, if the admin edited it


class PipelineState(TypedDict, total=False):
    # Set by the server before the graph starts; names the stored artifact.
    run_id: str

    # Agent 1 output
    raw_headlines: list[Headline]
    selected_story_id: str
    selected_story: Headline
    selection_reason: str

    # Agent 2 output
    script: Script

    # Deterministic length check + Agent 3 (Critic) output
    duration_check_passed: bool
    critic_revision_count: int
    critic_direction: Optional[str]    # "too long" | "too short"

    # Agent 4 (Recovery) + render node
    render_result: RenderResult
    recovery_attempts: int

    # Cross-cutting
    error_log: list[ErrorLogEntry]
    status: Literal[
        "researching", "writing", "reviewing", "rendering",
        "recovering", "awaiting_approval", "posting", "done",
        "rejected", "failed",
    ]
    approval: ApprovalGate
    social_post_urls: dict[str, str]
    published_at: Optional[float]
    trigger: Literal["manual", "scheduled"]

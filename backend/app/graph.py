"""
Graph wiring. Every edge here is hardcoded — the only "decision" an
LLM ever makes is inside a node's own reasoning (which story, how to
shorten a script, how to fix an error). Routing between nodes is plain
Python, which costs zero tokens.
"""

import time

from langgraph.graph import END, StateGraph

from app.agents.critic_agent import critic_node
from app.agents.recovery_agent import recovery_node
from app.agents.research_agent import research_node
from app.agents.scriptwriter_agent import scriptwriter_node
from app.render.ffmpeg_render import RenderError, render_node
from app.social.facebook_post import post_reel_to_facebook
from app.social.linkedin_post import post_reel_to_linkedin
from app.state import PipelineState


# ---- Deterministic code nodes / routers (no LLM calls) --------------------

def route_after_research(state: PipelineState) -> str:
    return "end" if state.get("status") == "failed" else "scriptwriter"


def route_after_duration_check(state: PipelineState) -> str:
    """
    The core token-optimization rule for Agent 3: only pay for a Critic
    call when the deterministic word_count / 2.4 estimate falls OUTSIDE the
    length window in either direction. Inside the window, no LLM is spent.
    """
    return "render" if state.get("duration_check_passed") else "critic"


def render_with_recovery_node(state: PipelineState) -> dict:
    """
    Wraps the deterministic render step. On failure it does NOT crash
    the graph — it stores the error string so route_after_render can
    send state to the Recovery Agent instead.
    """
    try:
        return render_node(state)
    except RenderError as e:
        render_result = dict(state.get("render_result", {}))
        render_result["status"] = "failed"
        return {
            "render_result": render_result,
            "_last_render_error": str(e),  # transient, consumed by recovery_node_wrapper
            "status": "recovering",
        }


def recovery_node_wrapper(state: PipelineState) -> dict:
    error_message = state.get("_last_render_error", "Unknown render failure")
    return recovery_node(state, error_message)


def route_after_render(state: PipelineState) -> str:
    if state.get("status") == "recovering":
        return "recovery"
    return "approval"


def route_after_recovery(state: PipelineState) -> str:
    return "end" if state.get("status") == "failed" else "render"


def approval_gate_node(state: PipelineState) -> dict:
    """
    Terminal node of the graph, and deliberately a dead end.

    The reel is finished and stored; publishing is not part of the graph
    any more. `publish_node` is called by the server only after an admin
    presses Approve, so the human gate cannot be skipped by a reroute.
    """
    return {
        "approval": {"decision": "pending", "decided_at": None, "note": None, "caption": None},
        "status": "awaiting_approval",
    }


def default_caption(title: str) -> str:
    return f"{title} #news #shorts"


def publish_node(state: PipelineState, caption: str | None = None) -> dict:
    """
    Push an approved reel to every social platform.

    Plain function, not a graph node — being called at all *is* the
    approval. Each platform is attempted independently so one bad token
    lands in error_log without hiding a post that did succeed.
    """
    result = state["render_result"]
    text = (caption or default_caption(state.get("script", {}).get("title", ""))).strip()
    urls: dict[str, str] = dict(state.get("social_post_urls", {}))
    errors = list(state.get("error_log", []))

    targets = (
        ("facebook", post_reel_to_facebook),
        ("linkedin", post_reel_to_linkedin),
    )
    for platform, publish in targets:
        try:
            urls[platform] = publish(result["output_path"], text)
        except Exception as e:  # noqa: BLE001 - surfaced in error_log, not fatal
            errors.append(
                {"node": f"post_{platform}", "message": str(e), "resolved": False}
            )

    return {
        "social_post_urls": urls,
        "error_log": errors,
        "approval": {
            "decision": "approved",
            "decided_at": state.get("approval", {}).get("decided_at"),
            "note": state.get("approval", {}).get("note"),
            "caption": text,
        },
        "published_at": time.time(),
        "status": "done",
    }


# ---- Build the graph --------------------------------------------------------

def build_graph():
    graph = StateGraph(PipelineState)

    graph.add_node("research", research_node)
    graph.add_node("scriptwriter", scriptwriter_node)
    graph.add_node("critic", critic_node)
    graph.add_node("render", render_with_recovery_node)
    graph.add_node("recovery", recovery_node_wrapper)
    graph.add_node("approval", approval_gate_node)

    graph.set_entry_point("research")

    graph.add_conditional_edges("research", route_after_research, {
        "scriptwriter": "scriptwriter",
        "end": END,
    })

    # Hardcoded edge: writer finishes -> deterministic duration check runs
    # automatically as part of scriptwriter_node's own return value, then
    # we branch purely on that boolean.
    graph.add_conditional_edges("scriptwriter", route_after_duration_check, {
        "render": "render",
        "critic": "critic",
    })
    graph.add_conditional_edges("critic", route_after_duration_check, {
        "render": "render",
        "critic": "critic",
    })

    graph.add_conditional_edges("render", route_after_render, {
        "approval": "approval",
        "recovery": "recovery",
    })
    graph.add_conditional_edges("recovery", route_after_recovery, {
        "render": "render",
        "end": END,
    })

    # Hardcoded edge: a finished reel stops here and waits for an admin.
    graph.add_edge("approval", END)

    return graph.compile()

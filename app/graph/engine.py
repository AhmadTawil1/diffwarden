import logging
from functools import partial

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app import llm
from app.config import settings
from app.graph.state import BatchInput, ReviewState
from app.render import annotate, filter_files, make_batches

log = logging.getLogger("diffwarden")


def plan_batches(state: ReviewState, max_chars: int = 60_000) -> dict:
    kept, skipped = filter_files(state["files"])
    batches = make_batches([annotate(f) for f in kept], max_chars=max_chars)
    return {"batches": batches, "skipped": [f["filename"] for f in skipped]}


def fan_out(state: ReviewState):
    if not state["batches"]:
        return END
    return [Send("review_batch", {"prompt": p}) for p in state["batches"]]


async def review_batch(state: BatchInput) -> dict:
    findings = await llm.review(state["prompt"])
    log.info("review_batch: %d chars -> %d finding(s)", len(state["prompt"]), len(findings))
    return {"raw_findings": findings}


def skip_verify(state: ReviewState) -> dict:
    return {"verified": state.get("raw_findings", [])}


def build_engine(use_verifier: bool = settings.verify_findings, max_chars: int = 60_000):
    g = StateGraph(ReviewState)
    g.add_node("plan_batches", partial(plan_batches, max_chars=max_chars))
    g.add_node("review_batch", review_batch)
    g.add_node("verify", skip_verify)  # the real verifier arrives in Task 2.6
    g.add_edge(START, "plan_batches")
    g.add_conditional_edges("plan_batches", fan_out, ["review_batch", END])
    g.add_edge("review_batch", "verify")  # waits for all parallel reviews
    g.add_edge("verify", END)
    return g.compile()

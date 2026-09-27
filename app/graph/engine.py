import logging
from functools import partial

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app import llm
from app.config import settings
from app.graph.state import BatchInput, ReviewState
from app.render import annotate, filter_files, make_batches, snippet

log = logging.getLogger("diffwarden")
VERIFY_GROUP = 20  # candidates per verifier call


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


async def verify(state: ReviewState) -> dict:
    files = {f["filename"]: f for f in state["files"]}
    candidates = [c for c in state.get("raw_findings", []) if c.path in files]
    kept = []
    for start in range(0, len(candidates), VERIFY_GROUP):
        group = candidates[start:start + VERIFY_GROUP]
        prompt = "\n\n".join(
            f"#{i} {c.path}:{c.line} - {c.title}\n{c.explanation}\n"
            f"<code>\n{snippet(files[c.path], c.line, radius=15)}\n</code>"
            for i, c in enumerate(group)
        )
        verdicts = {v.id: v for v in await llm.verify(prompt)}
        for i, c in enumerate(group):
            v = verdicts.get(i)
            keep = bool(v and v.keep)  # no verdict -> drop
            log.info("verify %s %s:%d %s | %s", "KEEP" if keep else "DROP", c.path, c.line,
                     c.title, v.reason if v else "no verdict returned")
            if keep:
                kept.append(c)
    return {"verified": kept}


def skip_verify(state: ReviewState) -> dict:
    return {"verified": state.get("raw_findings", [])}


def build_engine(use_verifier: bool = settings.verify_findings, max_chars: int = 60_000):
    g = StateGraph(ReviewState)
    g.add_node("plan_batches", partial(plan_batches, max_chars=max_chars))
    g.add_node("review_batch", review_batch)
    g.add_node("verify", verify if use_verifier else skip_verify)
    g.add_edge(START, "plan_batches")
    g.add_conditional_edges("plan_batches", fan_out, ["review_batch", END])
    g.add_edge("review_batch", "verify")  # waits for all parallel reviews
    g.add_edge("verify", END)
    return g.compile()

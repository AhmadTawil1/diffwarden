from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from app.config import settings
from app.github import get_all
from app.graph.engine import build_engine
from app.graph.state import ReviewJob, ReviewState
from app.lines import commentable_lines, new_side_lines
from app.render import existing_fingerprints, fingerprint, neutralize, render_comment, render_summary

__all__ = ["ReviewJob", "build_review_graph", "review_graph"]

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


def _pr(job: ReviewJob) -> str:
    return f"/repos/{job.owner}/{job.repo}/pulls/{job.pull_number}"


async def fetch_files(state: ReviewState, config: RunnableConfig) -> dict:
    gh = config["configurable"]["gh"]
    return {"files": await get_all(gh, f"{_pr(state['job'])}/files")}


async def validate(state: ReviewState, config: RunnableConfig) -> dict:
    """Keep only findings GitHub will accept and we haven't posted before."""
    gh, job = config["configurable"]["gh"], state["job"]
    line_maps = {f["filename"]: commentable_lines(f["patch"])
                 for f in state["files"] if f.get("patch")}
    texts = {f["filename"]: new_side_lines(f["patch"])
             for f in state["files"] if f.get("patch")}
    seen = await existing_fingerprints(gh, f"{_pr(job)}/comments")

    final = []
    for f in state.get("verified", []):
        lines = line_maps.get(f.path, {})
        if f.line not in lines or f.confidence < settings.min_confidence:
            continue
        if f.start_line == f.line:
            f = f.model_copy(update={"start_line": None})  # a one-line range is just a line
        if f.start_line is not None and (f.start_line not in lines or f.start_line > f.line
                                         or lines[f.start_line] != lines[f.line]):
            # The range is invalid, so the suggestion would replace the wrong lines.
            f = f.model_copy(update={"start_line": None, "suggestion": None})
        fp = fingerprint(f, texts[f.path][f.line])
        if fp in seen:
            continue
        seen.add(fp)                        # also dedupes within this run
        final.append((neutralize(f), fp))  # "@name" -> "@\u200bname"
    final.sort(key=lambda pair: SEVERITY_ORDER[pair[0].severity])
    final = final[: settings.max_comments]

    r = await gh.get(_pr(job))
    r.raise_for_status()
    return {"final": [f for f, _ in final], "fingerprints": [fp for _, fp in final],
            "stale": r.json()["head"]["sha"] != job.head_sha}


def should_post(state: ReviewState) -> str:
    return "post_review" if state["final"] and not state["stale"] else END


async def post_review(state: ReviewState, config: RunnableConfig) -> dict:
    gh, job = config["configurable"]["gh"], state["job"]
    comments = []
    for f, fp in zip(state["final"], state["fingerprints"]):
        c = {"path": f.path, "line": f.line, "side": "RIGHT", "body": render_comment(f, fp)}
        if f.start_line:
            c |= {"start_line": f.start_line, "start_side": "RIGHT"}
        comments.append(c)
    r = await gh.post(f"{_pr(job)}/reviews", json={
        "commit_id": job.head_sha, "event": "COMMENT",
        "body": render_summary(state), "comments": comments,
    })
    r.raise_for_status()
    return {}


def build_review_graph():
    g = StateGraph(ReviewState)
    g.add_node("fetch_files", fetch_files, retry_policy=RetryPolicy(max_attempts=3))
    g.add_node("engine", build_engine())            # compiled subgraph as a node
    g.add_node("validate", validate, retry_policy=RetryPolicy(max_attempts=3))
    g.add_node("post_review", post_review)           # no retry: posting is not idempotent
    g.add_edge(START, "fetch_files")
    g.add_edge("fetch_files", "engine")
    g.add_edge("engine", "validate")
    g.add_conditional_edges("validate", should_post, ["post_review", END])
    g.add_edge("post_review", END)
    return g.compile()


review_graph = build_review_graph()

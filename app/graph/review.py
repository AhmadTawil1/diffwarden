from langchain_core.runnables import RunnableConfig

from app.config import settings
from app.graph.state import ReviewJob, ReviewState
from app.lines import commentable_lines, new_side_lines
from app.render import existing_fingerprints, fingerprint, neutralize

__all__ = ["ReviewJob", "validate"]

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


def _pr(job: ReviewJob) -> str:
    return f"/repos/{job.owner}/{job.repo}/pulls/{job.pull_number}"


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
        final.append((neutralize(f), fp))  # "@name" -> "@​name"
    final.sort(key=lambda pair: SEVERITY_ORDER[pair[0].severity])
    final = final[: settings.max_comments]

    r = await gh.get(_pr(job))
    r.raise_for_status()
    return {"final": [f for f, _ in final], "fingerprints": [fp for _, fp in final],
            "stale": r.json()["head"]["sha"] != job.head_sha}

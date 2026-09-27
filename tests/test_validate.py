import asyncio

import httpx

from app.config import settings
from app.graph.review import ReviewJob, validate
from app.render import fingerprint, render_comment
from app.schema import Finding

JOB = ReviewJob(installation_id=1, owner="o", repo="r", pull_number=7, head_sha="abc")

# Commentable lines: 10-13 in hunk 0, 50-51 in hunk 1.
PATCH = (
    "@@ -10,3 +10,4 @@\n"
    " a = 1\n"
    "+b = 2\n"
    " c = 3\n"
    " d = 4\n"
    "@@ -48,2 +50,2 @@\n"
    " x = 1\n"
    "+y = 2"
)
FILES = [{"filename": "app/m.py", "status": "modified", "patch": PATCH}]


def finding(**changes) -> Finding:
    base = dict(path="app/m.py", start_line=None, line=11, severity="major", category="bug",
                confidence=0.9, title="t", explanation="e", suggestion=None)
    return Finding(**(base | changes))


# Already posted on the PR: a finding on line 13 ("d = 4").
POSTED = fingerprint(finding(line=13), "d = 4")


def run(verified: list[Finding], head_sha: str = "abc") -> dict:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comments"):
            return httpx.Response(200, json=[{"body": render_comment(finding(line=13), POSTED)}])
        return httpx.Response(200, json={"head": {"sha": head_sha}})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     base_url="https://api.github.com") as gh:
            state = {"job": JOB, "files": FILES, "verified": verified}
            return await validate(state, config={"configurable": {"gh": gh}})

    return asyncio.run(go())


def test_valid_finding_is_kept():
    result = run([finding()])
    assert [f.line for f in result["final"]] == [11]
    assert result["stale"] is False


def test_non_commentable_line_is_dropped():
    assert run([finding(line=30)])["final"] == []


def test_low_confidence_is_dropped():
    assert run([finding(confidence=settings.min_confidence - 0.1)])["final"] == []


def test_already_posted_fingerprint_is_dropped():
    assert run([finding(line=13, title="reworded")])["final"] == []


def test_duplicate_in_one_run_keeps_one():
    assert len(run([finding(title="first"), finding(title="second")])["final"]) == 1


def test_start_line_in_another_hunk_is_cleared_with_its_suggestion():
    [f] = run([finding(start_line=11, line=51, suggestion="y = 3")])["final"]
    assert f.start_line is None and f.suggestion is None


def test_valid_range_keeps_start_line_and_suggestion():
    [f] = run([finding(start_line=10, line=12, suggestion="a = 1\nb = 3\nc = 3")])["final"]
    assert (f.start_line, f.suggestion) == (10, "a = 1\nb = 3\nc = 3")


def test_sorted_by_severity():
    result = run([finding(line=10, severity="minor"), finding(line=11, severity="critical")])
    assert [f.severity for f in result["final"]] == ["critical", "minor"]


def test_moved_head_marks_stale():
    assert run([finding()], head_sha="newer")["stale"] is True


def test_suggestion_longer_than_its_range_is_dropped_but_comment_kept():
    [f] = run([finding(line=11, suggestion="a = 1\nb = 3")])["final"]
    assert f.line == 11 and f.suggestion is None


def test_suggestion_matching_its_range_is_kept():
    [f] = run([finding(line=11, suggestion="b = 3")])["final"]
    assert f.suggestion == "b = 3"


def test_suggestion_shorter_than_its_range_is_dropped_but_comment_kept():
    [f] = run([finding(start_line=10, line=12, suggestion="b = 3")])["final"]
    assert (f.start_line, f.suggestion) == (10, None)

import asyncio
import json

import httpx
from langgraph.graph import END

from app.graph.review import ReviewJob, post_review, should_post
from app.schema import Finding

JOB = ReviewJob(installation_id=1, owner="o", repo="r", pull_number=7, head_sha="abc")


def finding(**changes) -> Finding:
    base = dict(path="app/m.py", start_line=None, line=11, severity="major", category="bug",
                confidence=0.9, title="t", explanation="e", suggestion=None)
    return Finding(**(base | changes))


def test_nothing_to_post_ends():
    assert should_post({"final": [], "stale": False}) == END


def test_stale_pr_ends():
    assert should_post({"final": [finding()], "stale": True}) == END


def test_fresh_findings_are_posted():
    assert should_post({"final": [finding()], "stale": False}) == "post_review"


def test_post_review_sends_one_review_with_inline_comments():
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     base_url="https://api.github.com") as gh:
            state = {"job": JOB, "final": [finding(), finding(start_line=20, line=22)],
                     "fingerprints": ["1" * 40, "2" * 40], "skipped": []}
            await post_review(state, config={"configurable": {"gh": gh}})

    asyncio.run(go())
    [(method, path, body)] = sent
    assert (method, path) == ("POST", "/repos/o/r/pulls/7/reviews")
    assert body["commit_id"] == "abc" and body["event"] == "COMMENT"
    single, ranged = body["comments"]
    assert single["line"] == 11 and "start_line" not in single
    assert (ranged["start_line"], ranged["line"], ranged["start_side"]) == (20, 22, "RIGHT")

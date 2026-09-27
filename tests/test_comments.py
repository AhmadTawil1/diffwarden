import asyncio

import httpx

from app.render import existing_fingerprints, fingerprint, neutralize, render_comment, render_summary
from app.schema import Finding

CODE = 'cur = conn.execute(f"SELECT * FROM users WHERE id = {user_id}")'


def finding(**changes) -> Finding:
    base = dict(path="shop/users.py", start_line=None, line=4, severity="critical",
                category="security", confidence=0.9, title="SQL injection",
                explanation="user_id is formatted into the query.", suggestion=None)
    return Finding(**(base | changes))


def test_same_code_on_another_line_keeps_the_fingerprint():
    assert fingerprint(finding(line=4), CODE) == fingerprint(finding(line=40), CODE)


def test_different_title_keeps_the_fingerprint():
    assert fingerprint(finding(title="SQL injection"), CODE) == \
        fingerprint(finding(title="Unparameterized query"), CODE)


def test_whitespace_changes_keep_the_fingerprint():
    assert fingerprint(finding(), CODE) == fingerprint(finding(), "    " + CODE.replace(" = ", "  =  "))


def test_different_code_changes_the_fingerprint():
    assert fingerprint(finding(), CODE) != fingerprint(finding(), "return cur.fetchone()")


def test_suggestion_block_only_when_suggestion_is_set():
    assert "```suggestion" not in render_comment(finding(), "a" * 40)
    body = render_comment(finding(suggestion="    cur = conn.execute(q, (user_id,))"), "a" * 40)
    assert "```suggestion\n    cur = conn.execute(q, (user_id,))\n```" in body


def test_comment_ends_with_the_hidden_marker():
    assert render_comment(finding(), "b" * 40).endswith(f"<!-- diffwarden:fp={'b' * 40} -->")


def test_neutralize_breaks_mentions_in_prose_but_not_code():
    f = neutralize(finding(explanation="Ask @octocat.", suggestion="@property"))
    assert f.explanation == "Ask @​octocat."
    assert f.suggestion == "@property"


def test_summary_counts_severities_and_lists_skipped_files():
    text = render_summary({"final": [finding(), finding(severity="minor")], "skipped": ["uv.lock"]})
    assert "found 2 issue(s): 1 critical, 1 minor." in text
    assert "- `uv.lock`" in text


def test_existing_fingerprints_reads_markers_from_pr_comments():
    fp1, fp2 = "1" * 40, "2" * 40
    comments = [
        {"body": render_comment(finding(), fp1)},
        {"body": f"a human comment\n<!-- diffwarden:fp={fp2} -->"},
        {"body": "no marker here"},
    ]

    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=comments))
        async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as gh:
            return await existing_fingerprints(gh, "/repos/o/r/pulls/1/comments")

    assert asyncio.run(run()) == {fp1, fp2}

import asyncio

from app import llm
from app.graph import engine
from app.render import annotate

PATCH = "@@ -1,1 +1,1 @@\n-a = 1\n+a = 2"


def batch(n: int) -> str:
    return "\n".join(
        annotate({"filename": f"app/m{i}.py", "status": "modified", "patch": PATCH}) for i in range(n)
    )


def test_review_batch_splits_when_output_is_cut_off(monkeypatch):
    calls = []

    async def fake_review(prompt: str):
        calls.append(prompt.count("<file "))
        if prompt.count("<file ") > 1:
            raise llm.BatchTooLarge()
        return [prompt.split('"')[1]]  # one "finding" per file: its path

    monkeypatch.setattr(llm, "review", fake_review)
    result = asyncio.run(engine.review_batch({"prompt": batch(4)}))
    assert sorted(result["raw_findings"]) == ["app/m0.py", "app/m1.py", "app/m2.py", "app/m3.py"]
    assert calls[0] == 4 and sorted(calls[1:3]) == [2, 2]


def test_review_batch_skips_a_single_file_that_is_too_large(monkeypatch):
    async def always_too_large(prompt: str):
        raise llm.BatchTooLarge()

    monkeypatch.setattr(llm, "review", always_too_large)
    assert asyncio.run(engine.review_batch({"prompt": batch(1)})) == {"raw_findings": []}


def test_verify_numbers_candidates_from_1_and_matches_ids(monkeypatch):
    from app.schema import Finding, Verdict

    prompts = []

    async def fake_verify(prompt: str):
        prompts.append(prompt)
        return [Verdict(id=1, keep=True, reason="real"), Verdict(id=2, keep=False, reason="fake")]

    def finding(line: int) -> Finding:
        return Finding(path="app/m0.py", start_line=None, line=line, severity="major", category="bug",
                       confidence=0.9, title=f"t{line}", explanation="e", suggestion=None)

    monkeypatch.setattr(llm, "verify", fake_verify)
    files = [{"filename": "app/m0.py", "status": "modified", "patch": PATCH}]
    result = asyncio.run(engine.verify({"files": files, "raw_findings": [finding(1), finding(1)]}))
    assert prompts[0].startswith("#1 ") and "\n\n#2 " in prompts[0]
    assert [f.title for f in result["verified"]] == ["t1"]

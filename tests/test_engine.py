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

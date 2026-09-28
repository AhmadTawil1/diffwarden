import asyncio
from types import SimpleNamespace

from app import llm
from app.config import settings
from app.graph import engine
from app.render import annotate


def fake_response(text: str, input_tokens: int, output_tokens: int):
    return SimpleNamespace(
        stop_reason="end_turn", stop_details=None,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def test_cost_uses_configured_prices():
    usage = llm.Usage(calls=1, input_tokens=1_000_000, output_tokens=100_000)
    assert usage.cost_usd == settings.input_price_per_mtok + settings.output_price_per_mtok / 10


def test_calls_in_parallel_graph_nodes_are_all_counted(monkeypatch):
    async def create(**kwargs):
        return fake_response('{"findings": []}', input_tokens=1000, output_tokens=200)

    monkeypatch.setattr(llm.client.messages, "create", create)
    patch = "@@ -1,1 +1,1 @@\n-a = 1\n+a = 2"
    files = [{"filename": f"app/m{i}.py", "status": "modified", "patch": patch} for i in range(3)]

    async def go():
        usage = llm.track_usage()
        await engine.build_engine(use_verifier=False, max_chars=100).ainvoke({"files": files})
        return usage

    usage = asyncio.run(go())
    assert (usage.calls, usage.input_tokens, usage.output_tokens) == (3, 3000, 600)


def test_no_tracker_means_no_counting(monkeypatch):
    async def create(**kwargs):
        return fake_response('{"findings": []}', input_tokens=1000, output_tokens=200)

    monkeypatch.setattr(llm.client.messages, "create", create)
    assert asyncio.run(llm.review(annotate({"filename": "a.py", "patch": "@@ -1 +1 @@\n+x"}))) == []

import asyncio
import json

import eval.run as eval_run
from eval.run import aggregate, keep, load_cases, matches, review_case, score, score_config
from app.schema import Finding

TRUTH = {"path": "app/items.py", "start": 35, "end": 35, "category": "bug"}


def finding(**changes) -> Finding:
    base = dict(path="app/items.py", start_line=None, line=35, severity="major", category="bug",
                confidence=0.9, title="t", explanation="e", suggestion=None)
    return Finding(**(base | changes))


def test_match_needs_same_file_and_overlap_within_3_lines():
    assert matches(finding(line=35), TRUTH)
    assert matches(finding(line=38), TRUTH)
    assert not matches(finding(line=39), TRUTH)
    assert matches(finding(start_line=20, line=32), TRUTH)  # a range reaching into the window
    assert not matches(finding(path="app/other.py"), TRUTH)
    assert not matches(finding(), {"path": "app/items.py", "clean": True})


def test_keep_drops_non_commentable_and_low_confidence():
    patch = "@@ -1,1 +1,2 @@\n a = 1\n+b = 2"
    kept = keep([finding(line=2), finding(line=9), finding(line=2, confidence=0.4)], patch, 0.7)
    assert [f.line for f in kept] == [2]


def test_score():
    base = {"error": None, "skipped": False}
    results = [
        base | {"truth": TRUTH, "found": True, "latency_s": 2.0, "cost_usd": 0.02,
                "findings": [{"match": True}, {"match": False}]},
        base | {"truth": TRUTH, "found": False, "latency_s": 4.0, "cost_usd": 0.04, "findings": []},
        base | {"truth": {"path": "x", "clean": True}, "found": False, "latency_s": 3.0,
                "cost_usd": 0.03, "findings": [{"match": False}]},
        base | {"truth": TRUTH, "found": False, "latency_s": 0.0, "cost_usd": 0.0, "findings": [],
                "skipped": True},  # skipped by the budget: not counted as a miss
    ]
    m = score(results)
    assert (m["recall"], m["precision"], m["fp_per_clean"], m["avg_latency_s"]) == (0.5, 1 / 3, 1.0, 3.0)
    assert round(m["avg_cost_usd"], 6) == 0.03 and round(m["total_cost_usd"], 6) == 0.09


def test_all_20_cases_load():
    cases = load_cases()
    assert len(cases) == 20
    assert sum(1 for c in cases if c["truth"].get("clean")) == 5


def test_case_is_skipped_once_the_budget_is_spent():
    class NeverCalled:
        async def ainvoke(self, state):
            raise AssertionError("engine must not run when the budget is spent")

    case = {"name": "01", "truth": TRUTH, "patch": "@@ -1 +1 @@\n+x"}
    out = asyncio.run(review_case(NeverCalled(), case, asyncio.Semaphore(1), {"spent": 1.0, "max": 1.0}))
    assert out["skipped"] and out["raw"] == [] and out["review"]["cost_usd"] == 0.0


def test_review_case_verifies_the_same_findings(monkeypatch):
    real, fake = finding(line=35, title="real"), finding(line=30, title="fake")

    class Reviewer:
        async def ainvoke(self, state):
            return {"verified": [real, fake]}

    async def fake_verify(state):
        assert [f.title for f in state["raw_findings"]] == ["real", "fake"]
        return {"verified": [real]}

    monkeypatch.setattr(eval_run, "verify", fake_verify)
    case = {"name": "01", "truth": TRUTH, "patch": "@@ -1 +1 @@\n+x"}
    budget = {"spent": 0.0, "max": 1.0}
    out = asyncio.run(review_case(Reviewer(), case, asyncio.Semaphore(1), budget))
    assert [f["title"] for f in out["raw"]] == ["real", "fake"]
    assert [f["title"] for f in out["verified"]] == ["real"]
    assert out["error"] is None and not out["skipped"]


def _saved_case(name, raw, verified, review_cost=0.01, verify_cost=0.005):
    step = lambda cost: {"latency_s": 1.0, "calls": 1, "input_tokens": 0, "output_tokens": 0,
                         "cost_usd": cost}
    return {"case": name, "skipped": False, "error": None,
            "raw": [f.model_dump() for f in raw], "verified": [f.model_dump() for f in verified],
            "review": step(review_cost), "verify": step(verify_cost)}


PATCH_35 = "@@ -30,6 +30,6 @@\n" + "".join(f" line{n}\n" for n in range(30, 35)) + "+bug\n"
CASES = {"bug": {"name": "bug", "truth": TRUTH, "patch": PATCH_35},
         "clean": {"name": "clean", "truth": {"path": "app/items.py", "clean": True}, "patch": PATCH_35}}


def test_verifier_on_is_scored_from_the_same_findings_and_costs_both_steps():
    real, noise = finding(line=35), finding(line=31, confidence=0.9)
    run = [_saved_case("bug", [real, noise], [real]), _saved_case("clean", [noise], [])]
    off = score_config(run, CASES, verifier=False, threshold=0.7)
    on = score_config(run, CASES, verifier=True, threshold=0.7)
    assert on["recall"] <= off["recall"]
    assert (off["fp_per_clean"], on["fp_per_clean"]) == (1.0, 0.0)
    assert round(off["avg_cost_usd"], 6) == 0.01 and round(on["avg_cost_usd"], 6) == 0.015


def test_aggregate_reports_mean_min_max():
    agg = aggregate([{"recall": 0.8}, {"recall": 1.0}, {"recall": 0.9}])
    assert agg["recall"] == {"mean": 0.9, "min": 0.8, "max": 1.0}


def test_rescoring_saved_runs_needs_no_api(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_run, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(eval_run, "load_cases", lambda: list(CASES.values()))
    for i, found in enumerate(([finding(line=35)], []), start=1):
        run = [_saved_case("bug", found, found), _saved_case("clean", [], [])]
        (tmp_path / f"stamp-run{i}.json").write_text(json.dumps({"run": i, "cases": run}))
    summary = asyncio.run(eval_run.main(runs=0, thresholds=[0.7], max_cost=0.0, from_stamp="stamp"))
    row = next(r for r in summary["rows"] if r["verifier"])
    assert row["summary"]["recall"] == {"mean": 0.5, "min": 0.0, "max": 1.0}
    assert (tmp_path / "stamp-summary.json").exists()

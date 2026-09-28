"""Run the engine on every eval case and score every verifier/threshold configuration.

Each run reviews every case once (verifier off), then runs the verifier on those same
findings. All configurations are scored from that data, so "verifier on" vs "off"
measures only the verifier, not run-to-run differences in the review.

    uv run python -m eval.run --runs 3                  # new runs (costs API credit)
    uv run python -m eval.run --from 20260928-180000    # re-score saved runs (free)
"""

import argparse
import asyncio
import json
import logging
import statistics
import time
from datetime import datetime
from pathlib import Path

from app import llm
from app.config import settings
from app.graph.engine import build_engine, verify
from app.lines import commentable_lines
from app.schema import Finding

EVAL_DIR = Path(__file__).parent
CASES_DIR = EVAL_DIR / "cases"
RESULTS_DIR = EVAL_DIR / "results"
MARGIN = 3        # a finding matches if it overlaps [start - 3, end + 3]
PARALLEL = 3      # cases in flight at once, to stay under rate limits
THRESHOLDS = [0.5, 0.7, 0.8]


def load_cases(cases_dir: Path = CASES_DIR) -> list[dict]:
    cases = []
    for folder in sorted(p for p in cases_dir.iterdir() if p.is_dir()):
        truth = json.loads((folder / "truth.json").read_text(encoding="utf-8"))
        patch = (folder / "case.patch").read_text(encoding="utf-8")
        cases.append({"name": folder.name, "truth": truth, "patch": patch})
    return cases


def matches(f: Finding, truth: dict) -> bool:
    """Same file, and the finding's lines overlap the truth range widened by MARGIN."""
    if truth.get("clean") or f.path != truth["path"]:
        return False
    start = f.start_line or f.line
    return start <= truth["end"] + MARGIN and f.line >= truth["start"] - MARGIN


def keep(findings: list[Finding], patch: str, threshold: float) -> list[Finding]:
    """What production would post: commentable lines only, confidence at or above the threshold."""
    lines = commentable_lines(patch)
    return [f for f in findings if f.line in lines and f.confidence >= threshold]


def score(results: list[dict]) -> dict:
    """Recall over seeded cases, precision over all findings, false positives per clean case."""
    results = [r for r in results if not r["skipped"]]
    seeded = [r for r in results if not r["truth"].get("clean")]
    clean = [r for r in results if r["truth"].get("clean")]
    findings = [f for r in results for f in r["findings"]]
    true_pos = [f for f in findings if f["match"]]
    return {
        "recall": sum(r["found"] for r in seeded) / len(seeded) if seeded else 0.0,
        "precision": len(true_pos) / len(findings) if findings else 0.0,
        "fp_per_clean": sum(len(r["findings"]) for r in clean) / len(clean) if clean else 0.0,
        "avg_latency_s": sum(r["latency_s"] for r in results) / len(results) if results else 0.0,
        "avg_cost_usd": sum(r["cost_usd"] for r in results) / len(results) if results else 0.0,
        "total_cost_usd": sum(r["cost_usd"] for r in results),
        "errors": sum(1 for r in results if r["error"]),
    }


def _step(usage: llm.Usage, latency: float) -> dict:
    return {"latency_s": round(latency, 2), "calls": usage.calls, "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens, "cost_usd": round(usage.cost_usd, 5)}


async def review_case(reviewer, case: dict, limit: asyncio.Semaphore, budget: dict) -> dict:
    """Review one case, then verify the same findings. Records both steps separately."""
    files = [{"filename": case["truth"]["path"], "status": "modified", "patch": case["patch"]}]
    out = {"case": case["name"], "skipped": False, "error": None, "raw": [], "verified": [],
           "review": _step(llm.Usage(), 0.0), "verify": _step(llm.Usage(), 0.0)}
    async with limit:
        if budget["spent"] >= budget["max"]:  # stop starting new cases once the budget is used
            return out | {"skipped": True}
        try:
            usage, started = llm.track_usage(), time.perf_counter()  # counts only this case's calls
            try:
                raw = (await reviewer.ainvoke({"files": files})).get("verified", [])
            finally:
                out["review"] = _step(usage, time.perf_counter() - started)
            out["raw"] = [f.model_dump() for f in raw]

            usage, started = llm.track_usage(), time.perf_counter()
            try:
                verified = (await verify({"files": files, "raw_findings": raw}))["verified"]
            finally:
                out["verify"] = _step(usage, time.perf_counter() - started)
            out["verified"] = [f.model_dump() for f in verified]
        except Exception as exc:  # one broken case shouldn't sink the whole run
            out["error"] = f"{type(exc).__name__}: {exc}"
        budget["spent"] += out["review"]["cost_usd"] + out["verify"]["cost_usd"]
    return out


def score_config(run: list[dict], cases: dict[str, dict], verifier: bool, threshold: float) -> dict:
    """Score one saved run for one configuration. Verifier on only filters the reviewer's findings."""
    results = []
    for c in run:
        case = cases[c["case"]]
        pool = [Finding(**f) for f in c["verified" if verifier else "raw"]]
        found = [{"match": matches(f, case["truth"])} for f in keep(pool, case["patch"], threshold)]
        steps = [c["review"], c["verify"]] if verifier else [c["review"]]
        results.append({
            "truth": case["truth"], "skipped": c["skipped"], "error": c["error"], "findings": found,
            "found": any(f["match"] for f in found),
            "latency_s": sum(s["latency_s"] for s in steps), "cost_usd": sum(s["cost_usd"] for s in steps),
        })
    return score(results)


def aggregate(per_run: list[dict]) -> dict:
    """Mean, min, and max of each metric across runs."""
    return {k: {"mean": statistics.fmean(m[k] for m in per_run),
                "min": min(m[k] for m in per_run), "max": max(m[k] for m in per_run)}
            for k in per_run[0]}


def _pct(m: dict) -> str:
    if m["min"] == m["max"]:
        return f"{m['mean']:.0%}"
    return f"{m['mean']:.0%} ({m['min']:.0%}–{m['max']:.0%})"


def _num(m: dict) -> str:
    if m["min"] == m["max"]:
        return f"{m['mean']:.2f}"
    return f"{m['mean']:.2f} ({m['min']:.2f}–{m['max']:.2f})"


async def new_runs(runs: int, max_cost: float, cases: list[dict], stamp: str) -> list[list[dict]]:
    reviewer = build_engine(use_verifier=False)
    budget = {"spent": 0.0, "max": max_cost}
    limit = asyncio.Semaphore(PARALLEL)
    saved = []
    for i in range(1, runs + 1):
        run = await asyncio.gather(*(review_case(reviewer, c, limit, budget) for c in cases))
        path = RESULTS_DIR / f"{stamp}-run{i}.json"
        path.write_text(json.dumps({"model": settings.anthropic_model, "run": i, "cases": run}, indent=2),
                        encoding="utf-8")
        cost = sum(c["review"]["cost_usd"] + c["verify"]["cost_usd"] for c in run)
        print(f"run {i}/{runs}: ${cost:.4f}  (total so far ${budget['spent']:.4f})  saved {path.name}")
        saved.append(run)
    return saved


def load_runs(stamp: str) -> list[list[dict]]:
    paths = sorted(RESULTS_DIR.glob(f"{stamp}-run*.json"))
    if not paths:
        raise SystemExit(f"no saved runs match eval/results/{stamp}-run*.json")
    return [json.loads(p.read_text(encoding="utf-8"))["cases"] for p in paths]


def report(runs: list[list[dict]], cases: list[dict], thresholds: list[float], stamp: str) -> dict:
    by_name = {c["name"]: c for c in cases}
    rows = []
    for verifier in (False, True):
        for t in thresholds:
            per_run = [score_config(run, by_name, verifier, t) for run in runs]
            rows.append({"verifier": verifier, "threshold": t, "per_run": per_run,
                         "summary": aggregate(per_run)})

    # Per-case recall at the default threshold: how often each seeded bug was found.
    t0 = settings.min_confidence if settings.min_confidence in thresholds else thresholds[0]
    print(f"\nfound per seeded case at threshold {t0} (off / on, out of {len(runs)} runs)")
    for name, case in by_name.items():
        if case["truth"].get("clean"):
            continue
        counts = []
        for key in ("raw", "verified"):
            n = 0
            for run in runs:
                c = next(c for c in run if c["case"] == name)
                pool = keep([Finding(**f) for f in c[key]], case["patch"], t0)
                n += any(matches(f, case["truth"]) for f in pool)
            counts.append(n)
        flag = "" if counts == [len(runs)] * 2 else "   <-"
        print(f"  {name:<28} {counts[0]}/{len(runs)} / {counts[1]}/{len(runs)}{flag}")

    print(f"\n{len(runs)} run(s); mean (min–max) across runs")
    print("| Verifier | Threshold | Recall | Precision | FP / clean case | Avg latency | Avg cost |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        s = r["summary"]
        print(f"| {'on' if r['verifier'] else 'off'} | {r['threshold']} | {_pct(s['recall'])} "
              f"| {_pct(s['precision'])} | {_num(s['fp_per_clean'])} "
              f"| {s['avg_latency_s']['mean']:.1f}s | ${s['avg_cost_usd']['mean']:.4f} |")

    skipped = sum(c["skipped"] for run in runs for c in run)
    errors = sum(bool(c["error"]) for run in runs for c in run)
    if skipped:
        print(f"warning: {skipped} case run(s) skipped by --max-cost; those runs are partial")
    if errors:
        print(f"warning: {errors} case run(s) errored; see the run JSON files")

    summary = {"stamp": stamp, "model": settings.anthropic_model, "runs": len(runs),
               "thresholds": thresholds, "rows": rows}
    path = RESULTS_DIR / f"{stamp}-summary.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"saved {path.name}")
    return summary


async def main(runs: int, thresholds: list[float], max_cost: float, from_stamp: str | None) -> dict:
    RESULTS_DIR.mkdir(exist_ok=True)
    cases = load_cases()
    if from_stamp:
        stamp, saved = from_stamp, load_runs(from_stamp)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        saved = await new_runs(runs, max_cost, cases, stamp)
        spent = sum(c["review"]["cost_usd"] + c["verify"]["cost_usd"] for run in saved for c in run)
        print(f"total API cost: ${spent:.4f}")
    return report(saved, cases, thresholds, stamp)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score DiffWarden on the eval cases.")
    parser.add_argument("--runs", type=int, default=3, help="independent runs (default 3)")
    parser.add_argument("--thresholds", type=float, nargs="+", default=THRESHOLDS)
    parser.add_argument("--max-cost", type=float, default=1.0,
                        help="stop starting new cases once this many USD are spent (default 1.00)")
    parser.add_argument("--from", dest="from_stamp", metavar="STAMP",
                        help="re-score saved runs eval/results/STAMP-run*.json (no API calls)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main(args.runs, args.thresholds, args.max_cost, args.from_stamp))

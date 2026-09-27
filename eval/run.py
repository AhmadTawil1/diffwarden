"""Run the engine subgraph on every eval case and score it.

    uv run python -m eval.run --verifier on --threshold 0.7
"""

import argparse
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.graph.engine import build_engine
from app.lines import commentable_lines
from app.schema import Finding

EVAL_DIR = Path(__file__).parent
CASES_DIR = EVAL_DIR / "cases"
RESULTS_DIR = EVAL_DIR / "results"
MARGIN = 3        # a finding matches if it overlaps [start - 3, end + 3]
PARALLEL = 3      # cases in flight at once, to stay under rate limits


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
    seeded = [r for r in results if not r["truth"].get("clean")]
    clean = [r for r in results if r["truth"].get("clean")]
    findings = [f for r in results for f in r["findings"]]
    true_pos = [f for f in findings if f["match"]]
    return {
        "recall": sum(r["found"] for r in seeded) / len(seeded) if seeded else 0.0,
        "precision": len(true_pos) / len(findings) if findings else 0.0,
        "fp_per_clean": sum(len(r["findings"]) for r in clean) / len(clean) if clean else 0.0,
        "avg_latency_s": sum(r["latency_s"] for r in results) / len(results) if results else 0.0,
        "errors": sum(1 for r in results if r["error"]),
    }


async def run_case(engine, case: dict, threshold: float, limit: asyncio.Semaphore) -> dict:
    truth = case["truth"]
    files = [{"filename": truth["path"], "status": "modified", "patch": case["patch"]}]
    async with limit:
        started = time.perf_counter()
        error, raw = None, []
        try:
            state = await engine.ainvoke({"files": files})
            raw = state.get("verified", [])
        except Exception as exc:  # one broken case shouldn't sink the whole run
            error = f"{type(exc).__name__}: {exc}"
        latency = time.perf_counter() - started
    kept = keep(raw, case["patch"], threshold)
    found = [{**f.model_dump(), "match": matches(f, truth)} for f in kept]
    return {
        "case": case["name"], "truth": truth, "latency_s": round(latency, 2), "error": error,
        "found": any(f["match"] for f in found), "findings": found,
    }


async def main(verifier: bool, threshold: float) -> dict:
    engine = build_engine(use_verifier=verifier)
    limit = asyncio.Semaphore(PARALLEL)
    cases = load_cases()
    results = await asyncio.gather(*(run_case(engine, c, threshold, limit) for c in cases))
    metrics = score(results)

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RESULTS_DIR / f"{stamp}.json"
    config = {"verifier": verifier, "threshold": threshold, "model": settings.anthropic_model,
              "cases": len(cases)}
    out.write_text(json.dumps({"config": config, "metrics": metrics, "results": results}, indent=2),
                   encoding="utf-8")

    for r in results:
        mark = "ERROR" if r["error"] else ("clean" if r["truth"].get("clean") else
                                          ("found" if r["found"] else "MISSED"))
        print(f"{r['case']:<28} {mark:<6} {len(r['findings'])} finding(s)  {r['latency_s']:>5.1f}s"
              + (f"  {r['error']}" if r["error"] else ""))
    print(f"\nsaved {out.relative_to(EVAL_DIR.parent)}")
    print("| Verifier | Threshold | Recall | Precision | FP / clean case | Avg latency |")
    print("|---|---|---|---|---|---|")
    print(f"| {'on' if verifier else 'off'} | {threshold} | {metrics['recall']:.0%} "
          f"| {metrics['precision']:.0%} | {metrics['fp_per_clean']:.2f} "
          f"| {metrics['avg_latency_s']:.1f}s |")
    if metrics["errors"]:
        print(f"warning: {metrics['errors']} case(s) errored; see the JSON")
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score DiffWarden on the eval cases.")
    parser.add_argument("--verifier", choices=["on", "off"], default="on")
    parser.add_argument("--threshold", type=float, default=settings.min_confidence)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main(args.verifier == "on", args.threshold))

# Eval results

20 cases: 15 seeded bugs (one per case, Python and JavaScript) and 5 clean refactors. Model `claude-sonnet-5`. One run per configuration, 2026-09-27. Raw results: `eval/results/*.json` (not committed).

| Verifier | Threshold | Recall | Precision | FP / clean case | Avg latency |
|---|---|---|---|---|---|
| off | 0.7 | 93% | 100% | 0.00 | 4.6s |
| on | 0.7 | 100% | 100% | 0.00 | 6.8s |
| on | 0.5 | 100% | 94% | 0.00 | 6.1s |
| on | 0.8 | 80% | 100% | 0.00 | 6.1s |

- **Recall**: seeded bugs with at least one finding in the right file within 3 lines of the planted bug.
- **Precision**: findings that match a planted bug, out of all findings posted.
- **FP / clean case**: findings on the 5 correct refactors, per case.

## What the errors show

- **No false alarms on clean code in any configuration.** The prompt's "an empty list is the normal answer" holds.
- **The only unmatched finding** (on / 0.5) was `page_count()` raising `ZeroDivisionError` for `per_page=0` in case 01, at confidence 0.5. It is a real, minor issue the seeded case didn't intend, so it is a gap in the ground truth rather than a hallucination. A 0.7 threshold filters it out.
- **Missed bugs were confidence, not detection.** Case 03 (`address` may be `None`) scored 0.6–0.75 across runs, so it is found at 0.5 and 0.7 but can fall under a 0.7 or 0.8 cut. At 0.8, cases 07 (unclosed connection) and 13 (N+1 query) were also lost, even though they scored 0.8–0.9 in other runs.
- **Extra findings on the same bug are real.** In case 11 (unvalidated transfer amount), lower thresholds added two plausible related issues next to the planted one (non-atomic balance check, unchecked destination account).

## What the verifier changed

On this set, the verifier added about 2 seconds per case and made no measurable difference to quality: precision was already 100% without it, and the one recall difference (case 03, missed with the verifier off) comes from the review pass scoring the bug below 0.7 in that run, not from verification.

## Caveats

- **One run per configuration.** Each case is 1 of 15 (about 7 points of recall), and confidences vary between runs, so differences of one case are within run-to-run noise.
- **The set is easy.** Short files, one obvious bug each, docstrings that state the intended behavior, and no unrelated changes. Real PRs are harder, so these numbers are an upper bound.

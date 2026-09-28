# Eval results

28 cases, model `claude-sonnet-5`, 3 independent runs (2026-09-28). Raw runs: `eval/results/20260928-173800-run*.json` (not committed).

| Kind | Cases | What it tests |
|---|---|---|
| Seeded | 15 | One planted bug in a short Python or JavaScript file |
| Long file | 3 | One bug buried in a new 216–294 line module |
| Two bugs | 2 | Two planted bugs in the same diff (22 bugs in total) |
| Clean | 5 | Correct refactors: rename, extract function, type hints, docstrings, comprehension |
| Decoy | 3 | Correct code that looks wrong: `except` that logs and re-raises, SQL built from an allow-listed column, intended integer division |

Mean of 3 runs, with the range in brackets when runs differed.

| Verifier | Threshold | Recall | Precision | FP / clean | FP / decoy | Avg latency | Avg cost / review |
|---|---|---|---|---|---|---|---|
| off | 0.5 | 100% | 100% | 0.00 | 0.00 | 7.2s | $0.0103 |
| off | 0.7 | 95% (91–100%) | 100% | 0.00 | 0.00 | 7.2s | $0.0103 |
| off | 0.8 | 77% (73–82%) | 100% | 0.00 | 0.00 | 7.2s | $0.0103 |
| on | 0.5 | 100% | 100% | 0.00 | 0.00 | 9.2s | $0.0127 |
| on | 0.7 | 95% (91–100%) | 100% | 0.00 | 0.00 | 9.2s | $0.0127 |
| on | 0.8 | 77% (73–82%) | 100% | 0.00 | 0.00 | 9.2s | $0.0127 |

- **Recall** is per planted bug: a finding in the right file within 3 lines of the bug's range. Findings and bugs are paired one-to-one, so one comment can't count for two nearby bugs.
- **Precision**: findings that hit a planted bug, out of all findings posted.
- **FP / clean** and **FP / decoy**: findings posted on correct code, per case.
- **Cost** is measured from the API's token counts (output includes thinking), at $2 / $10 per million input/output tokens.

## Method

Each run reviews every case once, then runs the verifier on those same findings. Every row is scored from that shared output: "verifier on" only filters "verifier off", and the thresholds only filter by confidence. So the on/off comparison measures the verifier alone, not run-to-run differences in the review, and verifier-on recall can never exceed verifier-off recall.

## What the results show

- **The verifier had no effect.** Across 3 runs the reviewer produced 74 findings and the verifier kept all 74, including on the decoys. It adds about 2 seconds and 24% cost per review for no measured change. The reviewer prompt ("report only problems caused by the changed lines, with a concrete failure; an empty list is the normal answer") already keeps false positives at zero on this set.
- **No false positives on correct code**, at any threshold: 0 on the 5 clean refactors and 0 on the 3 decoys.
- **Every bug is found; confidence is what loses them.** At 0.5, recall is 100% in every run. The misses at 0.7 are real bugs the model found but rated 0.6: the missing `await` in the lockout case (2 of 3 runs) and the unclosed connection in the exports case (1 of 3). At 0.8, the misses grow to about a quarter of all bugs.
- **On this set, a lower threshold is strictly better.** 0.5 gives full recall with no loss of precision. The deployed default is still 0.7, because 28 cases is a small sample and a real PR has more surface for low-confidence noise; lowering it should be checked on harder, real-world diffs first.
- **Long files and multiple bugs were not a problem.** All three bugs buried in 216–294 line modules were found in every run, and both two-bug cases were reported as two separate comments.

## Corrections made during this eval

Reading the errors found two mistakes in my own ground truth, not in DiffWarden:

- **Decoy 21 had a real bug.** DiffWarden reported that a CSV price of `"Infinity"` passes validation, which was true: `Decimal("Infinity")` parses and isn't negative. The decoy was fixed to reject non-finite prices and that case was re-run.
- **Case 27's bug ranges were too narrow.** DiffWarden reported the `None` access where `fetchone()` can return `None` and the leak where the function returns without closing the connection, both sensible places. The ranges were widened to cover those lines, and matching was made one-to-one, which also removed an earlier overcount on case 28.

## Caveats

- **Small and synthetic.** 28 hand-written cases, most of them short. Real PRs are larger, mix unrelated changes, and depend on code outside the diff, so these numbers are an upper bound.
- **3 runs.** Enough to separate noise from real differences on this set, not to give tight intervals.
- **The verifier may still help on harder input.** It measured no benefit here because the reviewer produced no false positives for it to remove; a set of real PRs with noisier reviews is the right test.

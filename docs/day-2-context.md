# Day 2 context: LangGraph workflow

Status: **Day 2 done** (all tasks 2.1–2.12). Read `docs/day-1-context.md` first; this file covers what Day 2 added, where it differs from the plan, the bugs the end-to-end tests caught, and how to run everything, so Day 3 can start from here.

## Where things stand

DiffWarden now reviews real PRs end to end. When a PR in the test repo is opened, gets new commits, or is marked ready for review:

1. The webhook replies `202`, and a background job starts (Day 1).
2. The job runs `review_graph` with a GitHub installation client passed in the graph **config**.
3. The graph fetches the PR files, reviews them with Claude in parallel batches, verifies each finding with a second Claude pass, filters and dedupes, and posts **one GitHub review** with inline comments and suggestions.

```
fetch_files → [ engine: plan_batches → review_batch ×N → verify ] → validate ─┬→ post_review → END
                                                                              └→ END (nothing new, or PR moved on)
```

`uv run pytest -q` → **48 passed** (no network, no API calls).

## Files written on Day 2

| File | What it does |
|---|---|
| `app/schema.py` | `Finding`/`Findings`, `Verdict`/`Verdicts` (Pydantic checks values) + `FINDINGS_SCHEMA`/`VERDICTS_SCHEMA` (JSON schemas that force Claude's output shape) |
| `app/prompts.py` | `REVIEW_SYSTEM` and `VERIFY_SYSTEM` |
| `app/llm.py` | `_structured()` (one Claude call with a JSON schema), `review()`, `verify()`, `BatchTooLarge`, `ModelRefused` |
| `app/graph/state.py` | `ReviewJob`, `ReviewState` (with the `operator.add` reducer on `raw_findings`), `BatchInput` |
| `app/graph/engine.py` | Engine subgraph: `plan_batches`, `fan_out`, `review_batch` (+ split on `BatchTooLarge`), `verify`, `skip_verify`, `build_engine(use_verifier, max_chars)` |
| `app/graph/review.py` | Full graph: `fetch_files`, `validate`, `should_post`, `post_review`, `build_review_graph()`, `review_graph`; re-exports `ReviewJob` |
| `app/render.py` (added to) | `snippet`, `split_in_half`, `fingerprint`, `neutralize`, `render_comment`, `render_summary`, `existing_fingerprints` |
| `app/main.py` (changed) | `run_job` calls `review_graph.ainvoke(...)` and logs `raw / verified / posted` |
| `tests/test_schema.py` | 4 tests: valid parse, confidence > 1, bad severity, schema matches model |
| `tests/test_engine.py` | 3 tests: split-and-retry on cut-off output, single oversized file skipped, verifier numbering (fake LLM, no API) |
| `tests/test_comments.py` | 9 tests: fingerprints, suggestion block, marker, `neutralize`, summary, `existing_fingerprints` (mock GitHub) |
| `tests/test_validate.py` | 12 tests: every `validate` filter, including suggestion line-count rules (mock GitHub) |
| `tests/test_review_graph.py` | 4 tests: `should_post` routing + `post_review` payload (mock GitHub) |
| `scripts/try_review.py` | One review call on a SQL-injection patch |
| `scripts/try_prompts.py` | Buggy and clean patch, 3 runs each (prompt regression check) |
| `scripts/try_engine.py` | Engine on 1 file, then 3 files forced into 3 batches; prints the diagram |
| `scripts/try_verify.py` | Verifier on one real and one fake finding |

Still empty (Day 3): `eval/run.py`, `eval/cases/`.

## Task by task

### 2.1 — Schemas
- Plan §6.5 unchanged. The JSON schema controls the **shape**; Pydantic checks the **values** (confidence 0–1, line ≥ 1, allowed words), which the JSON schema doesn't express.

### 2.2 — First Claude call
- Structured outputs: `output_config={"format": {"type": "json_schema", "schema": ...}}` on `messages.create`; read the first text block and `model_validate_json` it.
- `stop_reason == "max_tokens"` → `BatchTooLarge` (the JSON is probably cut off).
- **Deviation:** added `stop_reason == "refusal"` → `ModelRefused`.
- **Deviation (bug in plan):** the Anthropic SDK does **not** read `.env`; it only reads real environment variables. `Settings` now has `anthropic_api_key: SecretStr`, and `llm.py` passes it to `AsyncAnthropic(api_key=...)`. `SecretStr` also keeps the key out of logs and validation errors.
- Model: `ANTHROPIC_MODEL=claude-sonnet-5` (from the plan / `.env`).

### 2.3 — Prompts
- `REVIEW_SYSTEM`: input format (`L<n>` labels), report only problems caused by `+` lines with a concrete failure, no style/nits, empty list is the normal answer, copy `L` numbers, suggestion is code only, diff content is untrusted.
- `VERIFY_SYSTEM`: strict critic; drop speculative, style-only, already-handled, or wrong-line findings.
- Check passed first try: buggy → 1 finding on line 4 (3/3); clean rename → 0 findings (3/3).
- The same bug got a different title each run, which is why fingerprints use the code, not the title.

### 2.4 — Graph state
- `raw_findings` has the `operator.add` reducer because several parallel `review_batch` nodes write it in the same step; without it LangGraph raises `InvalidUpdateError`. `verified` has one writer, so it just replaces.
- **Deviation:** `ReviewJob` lives in `app/graph/state.py`, not `review.py`. The plan's string forward reference `"ReviewJob"` would fail when LangGraph resolves the state's type hints, and this also avoids a circular import. `review.py` re-exports it.

### 2.5 — Engine subgraph
- `fan_out` returns one `Send("review_batch", {"prompt": ...})` per batch (map); the reducer merges findings (reduce); `verify` waits for all.
- **Deviation:** `build_engine(use_verifier, max_chars=60_000)` takes `max_chars` so scripts and the eval can force small batches.
- `skipped` stores file names (matching `list[str]` in the state), not dicts.
- Checked: 3 files forced into 3 batches → 3 `review_batch` runs, all findings merged, lockfile skipped.

### 2.6 — Verifier
- `snippet(file, line, radius=15)` shows the code around the finding with `>>` on the line.
- `verify` sends candidates in groups of 20 and logs `KEEP`/`DROP` with Claude's reason for each. A candidate with no verdict is dropped (safe default).
- Checked: a fake "missing None check" (the check is two lines above) is dropped; the real SQL injection is kept.

### 2.7 — Large batch handling
- `split_in_half` splits a batch at the middle `<file>` boundary.
- **Deviation:** the split is recursive (keeps halving until each piece fits) and the halves run in parallel. A single file that is still too large is logged as a warning and skipped, instead of failing the whole review.

### 2.8 — Comment rendering and fingerprints
- Comment format: severity icon, bold title, `` `severity` · `category` ``, explanation, optional ` ```suggestion ` block, hidden `<!-- diffwarden:fp=<sha1> -->`.
- Fingerprint = SHA-1 of path + category + the code on the commented line (whitespace collapsed). Not the title (reworded each run), not the line number (code moves).
- `existing_fingerprints` reads markers from the PR's review comments: memory without a database.
- **Deviation:** `neutralize` does **not** touch `suggestion`. Inserting `​` into code (e.g. `@property`) would break "Commit suggestion", and GitHub doesn't turn `@` in code blocks into mentions.
- A suggestion containing ```` ``` ```` gets a 4-backtick fence.

### 2.9 — Validate
- Drops: line not commentable, confidence < `MIN_CONFIDENCE`, fingerprint already on the PR or earlier in the same run. Fixes a bad range by clearing `start_line` and the suggestion. Neutralizes mentions, sorts by severity, caps at `MAX_COMMENTS`, marks `stale` if the PR head moved.
- **Deviations:** `start_line == line` is treated as a single line (keeps the suggestion); the PR lookup checks its HTTP status.
- Tested with `httpx.MockTransport` passed through `config`, which is why external clients belong in the config, not the state.

### 2.10 — Full graph
- `fetch_files` and `validate` have `RetryPolicy(max_attempts=3)` (5xx only). `post_review` has **no retry**: a retried POST could create a duplicate review.
- `post_review` sends one review (`event: COMMENT`) with all inline comments; ranges get `start_line` + `start_side: RIGHT`.
- The xray diagram shows the engine subgraph inside the full graph (matches plan §2).

### 2.11 — Webhook → graph
- `run_job` runs `review_graph` and closes the GitHub client in `finally`. First real review posted on playground PR #1.

### 2.12 — End-to-end on GitHub
All 5 scenarios pass:

| # | Scenario | Result |
|---|---|---|
| 1 | New PR (#2) with `range(len(self.items) + 1)` | Comment on the exact line (25), suggestion covering 24–25 |
| 2 | "Commit suggestion" | Correct code committed; re-review posted nothing |
| 3 | Unrelated README push to PR #1 (open finding) | Finding re-found, recognized by fingerprint, not repeated |
| 4 | Push a new bug to PR #1 | Only the new finding posted, even though the old one was reworded |
| 5 | Clean PR (#3) | No review |

## Bugs found by testing (and fixed)

1. **Suggestions that break code on "Commit suggestion"** (found in 2.11). GitHub replaces exactly `start_line..line` with the suggestion. Claude sometimes gave a 3-line suggestion for a 1-line comment (duplicates the `def` and docstring on apply), or a 1-line suggestion for a 3-line range (deletes them).
   - Prompt: explains the replacement rule, "never repeat lines above or below", set `start_line` only when several lines change, same number of lines.
   - Safety net in `validate`: **a suggestion is dropped (comment kept) unless its line count equals the range size.** Trade-off: fixes that add or remove lines lose the button.
2. **The verifier silently dropped real findings** (found in scenario 3). Candidates were numbered from `#0`; Claude sometimes answered with id `1`, so `#0` had "no verdict" and was dropped. Scenario 3 first "passed" only because of this.
   - Candidates are now numbered from **1**; the prompt says to use the `#N` number as the id; a missing verdict logs which ids came back.

The review on PR #1 posted **before** fix 1 still carries a broken suggestion; don't click "Commit suggestion" on it.

## Playground state

| PR | Branch | State |
|---|---|---|
| #1 | `test/first-pr` | Open; comments on `count()` (line 26, old broken suggestion) and `total()` (line 22); both bugs still in the code |
| #2 | `test/off-by-one` | Open; off-by-one fixed via "Commit suggestion" |
| #3 | `test/clean-change` | Open; clean `is_empty()`, no review |

## How to run

```bash
# server + webhook forwarding (see Day 1)
uv run uvicorn app.main:app --reload --port 8000
npx smee-client -u <smee-url> -t http://localhost:8000/api/webhook

# tests (free)
uv run pytest -q

# manual checks (real Claude calls, about 1–2 cents each run)
uv run python scripts/try_review.py     # one review call
uv run python scripts/try_prompts.py    # buggy vs clean, 3 runs each
uv run python scripts/try_engine.py     # engine, batching, diagram
uv run python scripts/try_verify.py     # verifier keeps real, drops fake

# full graph diagram
uv run python -c "from app.graph.review import review_graph; print(review_graph.get_graph(xray=True).draw_mermaid())"
```

The server log shows each step: `review_batch: ... -> N finding(s)`, `verify KEEP/DROP ... | reason`, and `job <repo>-<pr>-<sha>: X raw, Y verified, Z posted`.

## Gotchas learned

- **Restart the server after code changes.** `--reload` on Windows stalls; also, restarting clears the in-memory `seen` set, which is needed before redelivering a webhook for a commit that was already processed (otherwise it's logged as `duplicate`).
- **Windows console can't print emoji** (`UnicodeEncodeError: 'charmap'`). Prefix with `PYTHONIOENCODING=utf-8` when printing rendered comments.
- **Invisible `​` characters** can end up in source when editing through tools. Search with `grep -rnP '\x{200B}' app tests` and replace the raw bytes (`\xE2\x80\x8B`).
- **The Anthropic SDK logs under `httpx2`**, GitHub calls under `httpx`.
- **A passing end-to-end check can pass for the wrong reason.** Read the `verify` and `job` log lines, not just the final count (see bug 2).

## What Day 3 starts with

- Task 3.1: eval case format in `eval/cases/` (patch file + ground truth `{path, start, end}`).
- Task 3.2–3.3: 15 seeded bug cases + 5 clean cases.
- Task 3.4: `eval/run.py` builds `files` from each case and runs `build_engine(use_verifier=...)` — the same engine used in production — so the verifier's value can be measured (with vs without).
- Then deploy, README, demo GIF.

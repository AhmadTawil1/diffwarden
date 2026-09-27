# Day 1 context: FastAPI and GitHub plumbing

Status: **Day 1 done** (all tasks 1.1–1.11). This file records what exists, how it works, where it differs from the plan, and how to run it, so Day 2 can start from here.

## Where things stand

When a PR is opened, gets new commits, or is marked ready for review in the test repo:

1. GitHub sends a webhook to a smee.io channel, and the smee client forwards it to `localhost:8000/api/webhook`.
2. The server checks the HMAC signature, filters the event, and replies `202` straight away.
3. After the reply, a background job fetches the PR's files, filters them, annotates them with line numbers, packs them into batches, and **logs the batches**.

Day 2 replaces step 3's "log the batches" with a LangGraph workflow that sends the batches to Claude and posts a review.

## Setup (outside the code)

| Item | Value |
|---|---|
| Main repo | https://github.com/AhmadTawil1/diffwarden (public, branch `main`) |
| Test repo | https://github.com/AhmadTawil1/diffwarden-playground (private), local folder `../diffwarden-playground` |
| Test PR | `diffwarden-playground` PR #1, branch `test/first-pr`, adds `Cart.count()` to `shop/cart.py` |
| GitHub App | `diffwarden-ahmadtawil1`: Pull requests read & write, Contents read, event `pull_request`, installed on the test repo only |
| Installation ID | `165148690` (used in `scripts/try_auth.py`) |
| Webhook URL | a smee.io channel (URL kept privately, not in this public repo) |
| Private key | `.pem` kept in `~/Downloads`, outside the project; stored base64-encoded in `.env` |
| Python | 3.13 via uv (`.python-version`); system Python is 3.11, so always use `uv run` |

`.env` (git-ignored) holds `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY_BASE64`, `GITHUB_WEBHOOK_SECRET`, `MIN_CONFIDENCE`, `MAX_COMMENTS`, `VERIFY_FINDINGS`. `.env.example` lists the same names without values.

## Files written on Day 1

| File | What it does |
|---|---|
| `app/config.py` | `Settings` (pydantic-settings) loaded from `.env`; `settings.private_key_pem` decodes the base64 key |
| `app/main.py` | FastAPI app: `GET /healthz`, `POST /api/webhook`, `verify_signature`, temporary `ReviewJob` model, `run_job` background task |
| `app/github.py` | `app_jwt()`, `installation_client(id)`, `get_all(gh, url)` pagination |
| `app/lines.py` | `commentable_lines(patch)` → `{new_line: hunk_index}`; `new_side_lines(patch)` → `{new_line: code}` |
| `app/render.py` | `filter_files`, `annotate`, `make_batches` |
| `scripts/try_auth.py` | Manual check: prints PR #1's title and its files/patches |
| `tests/test_signature.py` | 3 tests: correct / wrong / missing signature |
| `tests/test_lines.py` | 4 tests: one hunk, two hunks, deleted lines, no-newline marker |
| `tests/test_render.py` | 5 tests: filtering, labels match `commentable_lines`, deleted lines unlabeled, batching |

`uv run pytest -q` → **12 passed**.

Still empty (Day 2+): `app/schema.py`, `app/llm.py`, `app/graph/state.py`, `app/graph/engine.py`, `app/graph/review.py`, `eval/run.py`.

## Task by task

### Before Day 1 — setup
- Tools: uv 0.11.3, Git 2.45, Node 22 (for `npx smee-client`), Python 3.13 through uv.
- Created both GitHub repos with `gh`; renamed the local branch `master` → `main`.
- Playground has small, deliberately clean modules in `shop/` (`cart.py`, `discounts.py`, `users.py`) for bug-injection PRs later.

### 1.1 — Project skeleton
- Dependencies: fastapi, uvicorn[standard], httpx, pyjwt[crypto], anthropic, pydantic-settings, langgraph; dev: pytest. Versions are pinned in `uv.lock`.
- Empty `__init__.py` in `app/`, `app/graph/`, `eval/`.
- `.gitignore` additions: `.env`, `*.pem`, `eval/results/`.

### 1.2 — Settings
- `app/config.py` follows plan §5 **plus `extra="ignore"`**. Without it, pydantic-settings rejects `ANTHROPIC_API_KEY` in `.env` ("Extra inputs are not permitted"), because the Anthropic SDK reads that variable itself and it isn't a `Settings` field.
- A missing required variable fails at startup with `Field required`.
- Caution: pydantic's `ValidationError` prints the raw values it read (`input_value=...`), including secrets. Never send settings errors to logs or error trackers.

### 1.3 — Hello FastAPI
- `GET /healthz` → `{"status": "ok"}`; Swagger UI at `/docs`.

### 1.4 — GitHub App
- Created the App, generated the private key, and installed the App on `diffwarden-playground` only.
- The App's webhook secret was later set through the API (`PATCH /app/hook/config`) to exactly match `.env`, after a copy-paste mismatch caused `401`s (see 1.6).

### 1.5 — Signature verification
- `verify_signature(body, signature)` computes `"sha256=" + HMAC-SHA256(secret, raw body)` and compares with `hmac.compare_digest` (constant time, so it can't be timed).
- `pyproject.toml` has `[tool.pytest.ini_options] pythonpath = ["."]` so tests can `import app`.
- Tests read the real secret from `.env`. CI would need env vars or a test override.

### 1.6 — Webhook endpoint
- Replies `401` if the signature is bad; `{"status": "ignored"}` for non-PR events, draft PRs, and other actions.
- **Reviewed actions: `opened`, `reopened`, `synchronize`, `ready_for_review`.** `ready_for_review` isn't in the plan; without it, a draft marked ready wouldn't be reviewed until the next push.
- `ignored` and `accepted` both return HTTP `202`; tell them apart by the log line.
- `logging.basicConfig(level=logging.INFO)` is needed, otherwise uvicorn hides the `diffwarden` logger.
- The draft test passed: `converted_to_draft` and a push to a draft were both ignored.

### 1.7 — GitHub App authentication
- Two-step auth: `app_jwt()` signs a 9-minute RS256 JWT with the private key (`iss` = App ID); `installation_client()` exchanges it for a 1-hour installation token and returns an `httpx.AsyncClient` using it. **Close the client** (`await gh.aclose()`).
- `scripts/try_auth.py` printed PR #1's title.

### 1.8 — Fetch PR files with pagination
- `get_all()` requests 100 items per page until a page returns fewer than 100.
- Files without `patch` (binary or too large) are handled.

### 1.9 — Commentable lines (test-first)
- GitHub only accepts inline comments on added or context lines inside a hunk. A comment on any other line makes GitHub reject the **whole review**.
- `@@ -a,b +c,d @@`: the new-file side starts at line `c`. Deleted (`-`) lines and `\ No newline at end of file` don't advance the counter.
- Checked on the real PR: lines 20–26 match the file on GitHub.

### 1.10 — Filter, annotate, batch
- `filter_files` skips removed files, files without a patch, `*.lock`, `package-lock.json`, `uv.lock`, any `dist/` folder (at any depth), and `*.min.js`. It returns `(kept, skipped)`.
- `annotate` produces the prompt format (spacing is our own choice; the plan gave none):
  ```
  <file path="app/main.py">
  L1      a = 1
        - b = 2
  L2    + b = 3
  ...
  L41   + y = 2
  </file>
  ```
  `...` marks a gap between hunks. The model copies `L` labels instead of counting lines.
- `make_batches(blocks, max_chars=60_000)` packs blocks greedily; a single oversized block gets its own batch.

### 1.11 — Background task wiring
- `background.add_task(run_job, key, job)` runs after the `202` is sent.
- `asyncio.Semaphore(2)` allows at most 2 jobs at once.
- **Dedupe differs from the plan.** The plan's `in_flight` set forgets a key when the job ends, so a redelivery after a fast job would run again (and on Day 2, pay for a second review). We use `seen`: key = `"{repo_id}-{pr_number}-{head_sha}"`. It stays after success and is removed only on failure, so a failed job can be retried by redelivering. `seen` is in memory and resets when the server restarts.
- Verified: a push logged the annotated batch, and redelivering the same webhook logged `duplicate`.

## How to run

```bash
# terminal 1: server
uv run uvicorn app.main:app --reload --port 8000

# terminal 2: forward GitHub webhooks (smee URL from your notes)
npx smee-client -u <smee-url> -t http://localhost:8000/api/webhook

# tests
uv run pytest -q

# manual GitHub auth check
uv run python scripts/try_auth.py
```

To trigger a job, push a commit to the test PR, or redeliver a webhook from the App settings → **Advanced → Recent Deliveries**.

## Gotchas learned

- **`--reload` on Windows can stall.** After "Reloading..." the old process keeps serving old code. If a change seems to have no effect, stop the server (Ctrl+C) and start it again. A webhook that arrives mid-reload can also hit the old code, so redeliver it.
- **Recent Deliveries shows smee's response (`200`), not the server's.** The real status is in the smee client output and the server log.
- **smee.io can return `502` briefly**; just redeliver.
- **VS Code Pylance "import could not be resolved"**: select the interpreter `.venv\Scripts\python.exe` (Ctrl+Shift+P → Python: Select Interpreter).
- **Don't select `.env` lines in the IDE while chatting with Claude Code**: the selection is sent into the conversation.
- **Draft PRs**: the bot ignores them. Keep a PR as a draft while iterating, then click Ready for review for one review. After that, every push to a non-draft PR is reviewed again.

## What Day 2 changes

- `ReviewJob` moves from `app/main.py` to `app/graph/state.py` (done in 2.4; not `review.py` as the plan says, see Day 2 notes).
- `run_job` calls `review_graph.ainvoke({"job": job}, config={"configurable": {"gh": gh}})` instead of logging batches. The GitHub client goes in the graph config, not the state.
- Filtering, annotating, and batching move into the engine's `plan_batches` node; fetching moves into `fetch_files`.
- New: `app/schema.py`, `app/llm.py`, `app/graph/state.py`, `app/graph/engine.py`, `app/graph/review.py`, plus comment rendering and fingerprints in `app/render.py`.

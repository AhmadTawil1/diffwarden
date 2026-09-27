import asyncio
import hashlib
import hmac
import json
import logging

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from app.config import settings
from app.github import get_all, installation_client
from app.graph.state import ReviewJob
from app.render import annotate, filter_files, make_batches

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("diffwarden")
app = FastAPI(title="DiffWarden")
# Commits already accepted. A key is removed only if its job fails, so a
# redelivery of a finished commit is a duplicate but a failed one can be retried.
seen: set[str] = set()
limit = asyncio.Semaphore(2)


def verify_signature(body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/api/webhook", status_code=202)
async def webhook(
    request: Request,
    background: BackgroundTasks,
    x_github_event: str = Header(...),
    x_hub_signature_256: str | None = Header(None),
):
    body = await request.body()  # raw bytes are required for the signature check
    if not verify_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="invalid signature")

    if x_github_event != "pull_request":
        return {"status": "ignored"}
    payload = json.loads(body)
    pr = payload["pull_request"]
    if payload["action"] not in {"opened", "reopened", "synchronize", "ready_for_review"} or pr["draft"]:
        return {"status": "ignored"}

    job = ReviewJob(
        installation_id=payload["installation"]["id"],
        owner=payload["repository"]["owner"]["login"],
        repo=payload["repository"]["name"],
        pull_number=pr["number"],
        head_sha=pr["head"]["sha"],
    )
    key = f'{payload["repository"]["id"]}-{job.pull_number}-{job.head_sha}'
    if key in seen:
        log.info("duplicate: %s", key)
        return {"status": "duplicate"}
    seen.add(key)
    background.add_task(run_job, key, job)  # runs after the 202 is sent
    return {"status": "accepted"}


async def run_job(key: str, job: ReviewJob) -> None:
    try:
        async with limit:
            gh = await installation_client(job.installation_id)
            try:
                files = await get_all(gh, f"/repos/{job.owner}/{job.repo}/pulls/{job.pull_number}/files")
            finally:
                await gh.aclose()
        kept, skipped = filter_files(files)
        batches = make_batches([annotate(f) for f in kept])
        log.info(
            "job %s: %d files kept, %d skipped %s, %d batch(es)",
            key, len(kept), len(skipped), [f["filename"] for f in skipped], len(batches),
        )
        for i, batch in enumerate(batches):
            log.info("batch %d:\n%s", i, batch)
    except Exception:
        log.exception("review failed: %s", key)
        seen.discard(key)

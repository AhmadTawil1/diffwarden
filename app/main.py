import hashlib
import hmac
import json
import logging

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from app.config import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("diffwarden")
app = FastAPI(title="DiffWarden")


# Temporary: moves to app/graph/review.py on Day 2.
class ReviewJob(BaseModel):
    installation_id: int
    owner: str
    repo: str
    pull_number: int
    head_sha: str


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
    log.info("review job: %s", job.model_dump())
    return {"status": "accepted"}

import hashlib
import hmac

from fastapi import FastAPI

from app.config import settings

app = FastAPI(title="DiffWarden")


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

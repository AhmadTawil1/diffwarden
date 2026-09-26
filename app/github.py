import time

import httpx
import jwt

from app.config import settings

API = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def app_jwt() -> str:
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 540, "iss": settings.github_app_id}
    return jwt.encode(payload, settings.private_key_pem, algorithm="RS256")


async def installation_client(installation_id: int) -> httpx.AsyncClient:
    async with httpx.AsyncClient(base_url=API, headers=HEADERS) as c:
        r = await c.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt()}"},
        )
        r.raise_for_status()
    token = r.json()["token"]  # valid for 1 hour
    return httpx.AsyncClient(
        base_url=API, headers={**HEADERS, "Authorization": f"Bearer {token}"}, timeout=30
    )


async def get_all(gh: httpx.AsyncClient, url: str) -> list[dict]:
    """Paginate a GitHub list endpoint (per_page=100)."""
    items, page = [], 1
    while True:
        r = await gh.get(url, params={"per_page": 100, "page": page})
        r.raise_for_status()
        batch = r.json()
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1

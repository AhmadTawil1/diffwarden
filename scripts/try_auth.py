import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `app` imports when run as a script

from app.github import installation_client  # noqa: E402

# From the last webhook log.
INSTALLATION_ID = 165148690
OWNER, REPO, PULL_NUMBER = "AhmadTawil1", "diffwarden-playground", 1


async def main() -> None:
    gh = await installation_client(INSTALLATION_ID)
    try:
        r = await gh.get(f"/repos/{OWNER}/{REPO}/pulls/{PULL_NUMBER}")
        r.raise_for_status()
        print(r.json()["title"])
    finally:
        await gh.aclose()


asyncio.run(main())

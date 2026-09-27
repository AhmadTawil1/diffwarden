"""Run the engine subgraph on local patches (no GitHub needed)."""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `app` imports when run as a script

from app.graph.engine import build_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

# SQL injection on new line 4 (same bug as Task 2.2).
USERS = "\n".join([
    "@@ -3,4 +3,4 @@ import sqlite3",
    " def get_user(conn: sqlite3.Connection, user_id: int) -> tuple | None:",
    '-    cur = conn.execute("SELECT id, name, email FROM users WHERE id = ?", (user_id,))',
    '+    cur = conn.execute(f"SELECT id, name, email FROM users WHERE id = {user_id}")',
    "     return cur.fetchone()",
    " ",
])

# Wrong divisor on new line 4: a 10% discount takes off 100%.
DISCOUNTS = "\n".join([
    "@@ -1,4 +1,4 @@",
    " def apply_percentage(total: float, percent: float) -> float:",
    "     if not 0 <= percent <= 100:",
    '         raise ValueError("percent must be between 0 and 100")',
    "-    return round(total * (1 - percent / 100), 2)",
    "+    return round(total * (1 - percent / 10), 2)",
])

# Inverted filter on new line 20: remove() keeps only the item it should delete.
CART = "\n".join([
    "@@ -17,6 +17,6 @@ class Cart:",
    "         self.items.append(item)",
    " ",
    "     def remove(self, name: str) -> None:",
    "-        self.items = [i for i in self.items if i.name != name]",
    "+        self.items = [i for i in self.items if i.name == name]",
    " ",
    "     def total(self) -> float:",
])


def file(name: str, patch: str) -> dict:
    return {"filename": name, "status": "modified", "patch": patch}


def show(result: dict) -> None:
    print(f"batches={len(result.get('batches', []))} skipped={result.get('skipped', [])}")
    for f in result.get("verified", []):
        print(f"  [{f.severity}/{f.category}] {f.path}:{f.line} {f.title}")


async def main() -> None:
    print("== 1 file, default batch size")
    show(await build_engine(False).ainvoke({"files": [file("shop/users.py", USERS)]}))

    print("\n== 3 files + a lockfile, max_chars=400 (forces 1 batch per file)")
    files = [
        file("shop/users.py", USERS),
        file("shop/discounts.py", DISCOUNTS),
        file("shop/cart.py", CART),
        file("uv.lock", "@@ -1 +1 @@\n-old\n+new"),
    ]
    show(await build_engine(False, max_chars=400).ainvoke({"files": files}))

    print("\n== diagram (paste into https://mermaid.live)")
    print(build_engine(False).get_graph().draw_mermaid())


asyncio.run(main())

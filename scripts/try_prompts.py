"""Run the review prompt on a buggy and a clean patch, 3 times each."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `app` imports when run as a script

from app.llm import review  # noqa: E402
from app.render import annotate  # noqa: E402

RUNS = 3

# SQL injection on new line 4. Lines are joined so blank context lines keep their leading space.
BUGGY = "\n".join([
    "@@ -3,4 +3,4 @@ import sqlite3",
    " def get_user(conn: sqlite3.Connection, user_id: int) -> tuple | None:",
    '-    cur = conn.execute("SELECT id, name, email FROM users WHERE id = ?", (user_id,))',
    '+    cur = conn.execute(f"SELECT id, name, email FROM users WHERE id = {user_id}")',
    "     return cur.fetchone()",
    " ",
])

# Correct refactor: variables renamed, behavior unchanged.
CLEAN = "\n".join([
    "@@ -1,11 +1,11 @@",
    "-def apply_percentage(total: float, percent: float) -> float:",
    "-    if not 0 <= percent <= 100:",
    "+def apply_percentage(amount: float, pct: float) -> float:",
    "+    if not 0 <= pct <= 100:",
    '         raise ValueError("percent must be between 0 and 100")',
    "-    return round(total * (1 - percent / 100), 2)",
    "+    return round(amount * (1 - pct / 100), 2)",
    " ",
    " ",
    "-def apply_coupon(total: float, code: str, coupons: dict[str, float]) -> float:",
    "-    percent = coupons.get(code.upper())",
    "-    if percent is None:",
    "-        return total",
    "-    return apply_percentage(total, percent)",
    "+def apply_coupon(amount: float, code: str, coupons: dict[str, float]) -> float:",
    "+    pct = coupons.get(code.upper())",
    "+    if pct is None:",
    "+        return amount",
    "+    return apply_percentage(amount, pct)",
])

CASES = {
    "buggy": annotate({"filename": "shop/users.py", "status": "modified", "patch": BUGGY}),
    "clean": annotate({"filename": "shop/discounts.py", "status": "modified", "patch": CLEAN}),
}


async def main() -> None:
    jobs = [(name, i) for name in CASES for i in range(RUNS)]
    results = await asyncio.gather(*(review(CASES[name]) for name, _ in jobs))
    for (name, i), findings in zip(jobs, results):
        print(f"{name} run {i + 1}: {len(findings)} finding(s)")
        for f in findings:
            print(f"  [{f.severity}/{f.category}] {f.path}:{f.line} conf={f.confidence} {f.title}")
            print(f"    suggestion: {f.suggestion!r}")


asyncio.run(main())

"""Feed the verifier one real finding and one fake one; it should drop the fake."""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `app` imports when run as a script

from app.graph.engine import verify  # noqa: E402
from app.schema import Finding  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

# Real bug: SQL injection on new line 4.
USERS = "\n".join([
    "@@ -3,4 +3,4 @@ import sqlite3",
    " def get_user(conn: sqlite3.Connection, user_id: int) -> tuple | None:",
    '-    cur = conn.execute("SELECT id, name, email FROM users WHERE id = ?", (user_id,))',
    '+    cur = conn.execute(f"SELECT id, name, email FROM users WHERE id = {user_id}")',
    "     return cur.fetchone()",
    " ",
])

# No bug: email is checked for None on line 5, two lines before it's used on line 7.
PROFILE = "\n".join([
    "@@ -0,0 +1,7 @@",
    "+def email_domain(user: dict | None) -> str:",
    "+    if user is None:",
    '+        return ""',
    '+    email = user.get("email")',
    "+    if email is None:",
    '+        return ""',
    '+    return email.split("@")[-1]',
])


def finding(path: str, line: int, title: str, explanation: str, category: str) -> Finding:
    return Finding(path=path, start_line=None, line=line, severity="major", category=category,
                   confidence=0.8, title=title, explanation=explanation, suggestion=None)


STATE = {
    "files": [
        {"filename": "shop/users.py", "status": "modified", "patch": USERS},
        {"filename": "shop/profile.py", "status": "added", "patch": PROFILE},
    ],
    "raw_findings": [
        finding("shop/users.py", 4, "SQL injection via f-string query",
                "user_id is interpolated into the SQL string instead of passed as a parameter.",
                "security"),
        finding("shop/profile.py", 7, "Missing None check on email",
                "email may be None, so email.split raises AttributeError.", "bug"),
    ],
}


async def main() -> None:
    result = await verify(STATE)
    print("\nkept:", [f"{f.path}:{f.line} {f.title}" for f in result["verified"]])


asyncio.run(main())

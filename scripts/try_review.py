import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `app` imports when run as a script

from app.llm import review  # noqa: E402
from app.render import annotate  # noqa: E402

# The safe parameterized query is replaced by an f-string: SQL injection on the new line 4.
PATCH = """@@ -3,6 +3,6 @@ import sqlite3

 def get_user(conn: sqlite3.Connection, user_id: int) -> tuple | None:
-    cur = conn.execute("SELECT id, name, email FROM users WHERE id = ?", (user_id,))
+    cur = conn.execute(f"SELECT id, name, email FROM users WHERE id = {user_id}")
     return cur.fetchone()

 """


async def main() -> None:
    prompt = annotate({"filename": "shop/users.py", "status": "modified", "patch": PATCH})
    print(prompt, "\n")
    findings = await review(prompt)
    print(f"{len(findings)} finding(s)")
    for f in findings:
        print(f"\n[{f.severity}/{f.category}] {f.path}:{f.line} (confidence {f.confidence})")
        print(f"  {f.title}")
        print(f"  {f.explanation}")
        if f.suggestion:
            print(f"  suggestion: {f.suggestion}")


asyncio.run(main())

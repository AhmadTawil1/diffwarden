import re

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def commentable_lines(patch: str) -> dict[int, int]:
    """Map new-file line number -> hunk index."""
    lines: dict[int, int] = {}
    new_line, hunk = 0, -1
    for raw in patch.split("\n"):
        m = HUNK.match(raw)
        if m:
            new_line, hunk = int(m.group(1)), hunk + 1
            continue
        if hunk < 0:
            continue
        if raw.startswith(("+", " ")):
            lines[new_line] = hunk
            new_line += 1
        # "-" lines and "\ No newline at end of file" don't advance new_line
    return lines


def new_side_lines(patch: str) -> dict[int, str]:
    """Map new-file line number -> code text (same walk as above)."""
    texts: dict[int, str] = {}
    new_line, in_hunk = 0, False
    for raw in patch.split("\n"):
        m = HUNK.match(raw)
        if m:
            new_line, in_hunk = int(m.group(1)), True
            continue
        if in_hunk and raw.startswith(("+", " ")):
            texts[new_line] = raw[1:]
            new_line += 1
    return texts

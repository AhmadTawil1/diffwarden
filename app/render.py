import hashlib
import re
from pathlib import PurePosixPath

import httpx

from app.github import get_all
from app.lines import HUNK, new_side_lines
from app.schema import Finding

LOCKFILES = {"package-lock.json", "uv.lock"}
SEVERITY_ICON = {"critical": "🔴", "major": "🟠", "minor": "🟡"}
MARKER = re.compile(r"<!-- diffwarden:fp=([0-9a-f]{40}) -->")
MENTION = re.compile(r"@(?=\w)")


def is_skipped(f: dict) -> bool:
    path = PurePosixPath(f["filename"])
    return (
        f["status"] == "removed"
        or "patch" not in f
        or path.name in LOCKFILES
        or path.suffix == ".lock"
        or "dist" in path.parts[:-1]
        or path.name.endswith(".min.js")
    )


def filter_files(files: list[dict]) -> tuple[list[dict], list[dict]]:
    kept = [f for f in files if not is_skipped(f)]
    skipped = [f for f in files if is_skipped(f)]
    return kept, skipped


def annotate(f: dict) -> str:
    """Render a patch with an L<n> label on every added/context line (§6.4)."""
    out = [f'<file path="{f["filename"]}">']
    new_line, in_hunk = 0, False
    for raw in f["patch"].split("\n"):
        m = HUNK.match(raw)
        if m:
            if in_hunk:
                out.append("...")  # gap between hunks
            new_line, in_hunk = int(m.group(1)), True
            continue
        if not in_hunk or not raw:
            continue
        if raw[0] in "+ ":
            out.append(f"L{new_line:<5}{raw[0]} {raw[1:]}")
            new_line += 1
        elif raw[0] == "-":
            out.append(f"{'':6}- {raw[1:]}")
        # "\ No newline at end of file" is dropped
    out.append("</file>")
    return "\n".join(out)


def snippet(f: dict, line: int, radius: int = 15) -> str:
    """New-file lines within line ± radius that the patch shows, with >> on `line`."""
    texts = new_side_lines(f["patch"])
    return "\n".join(
        f"{'>>' if n == line else '  '} L{n:<5}{texts[n]}"
        for n in range(line - radius, line + radius + 1)
        if n in texts
    )


def split_in_half(prompt: str) -> list[str]:
    """Split a batch at its middle <file> boundary; a single-file batch comes back as-is."""
    blocks = prompt.split("\n<file ")
    blocks = blocks[:1] + ["<file " + b for b in blocks[1:]]
    if len(blocks) < 2:
        return [prompt]
    mid = len(blocks) // 2
    return ["\n".join(blocks[:mid]), "\n".join(blocks[mid:])]


def make_batches(blocks: list[str], max_chars: int = 60_000) -> list[str]:
    """Greedily pack blocks into batches under max_chars; an oversized block goes alone."""
    batches: list[str] = []
    current: list[str] = []
    size = 0
    for block in blocks:
        extra = len(block) + (1 if current else 0)  # +1 for the joining newline
        if current and size + extra > max_chars:
            batches.append("\n".join(current))
            current, size = [], 0
            extra = len(block)
        current.append(block)
        size += extra
    if current:
        batches.append("\n".join(current))
    return batches


def fingerprint(f: Finding, line_text: str) -> str:
    """SHA-1 of path + category + the commented code (whitespace collapsed).

    Uses the code, not the model's wording or the line number, so the same issue
    keeps the same fingerprint when it is reworded or the code moves down the file.
    """
    code = " ".join(line_text.split())
    return hashlib.sha1(f"{f.path}\n{f.category}\n{code}".encode()).hexdigest()


def neutralize(f: Finding) -> Finding:
    """Stop "@name" in the model's prose from pinging GitHub users.

    The suggestion is left alone: GitHub doesn't turn @ inside code blocks into
    mentions, and changing it would break code such as decorators when applied.
    """
    return f.model_copy(update={
        "title": MENTION.sub("@\u200b", f.title),
        "explanation": MENTION.sub("@\u200b", f.explanation),
    })


def render_comment(f: Finding, fp: str) -> str:
    parts = [
        f"{SEVERITY_ICON[f.severity]} **{f.title}**",
        f"`{f.severity}` · `{f.category}`",
        f.explanation,
    ]
    if f.suggestion:
        fence = "````" if "```" in f.suggestion else "```"
        parts.append(f"{fence}suggestion\n{f.suggestion}\n{fence}")
    parts.append(f"<!-- diffwarden:fp={fp} -->")
    return "\n\n".join(parts)


def render_summary(state: dict) -> str:
    final = state.get("final", [])
    counts = [f"{n} {s}" for s in SEVERITY_ICON if (n := sum(f.severity == s for f in final))]
    lines = [f"**DiffWarden** found {len(final)} issue(s): {', '.join(counts) or 'none'}."]
    if skipped := state.get("skipped"):
        lines.append("\nNot reviewed (deleted, binary, too large, or generated):")
        lines += [f"- `{name}`" for name in skipped]
    return "\n".join(lines)


async def existing_fingerprints(gh: httpx.AsyncClient, url: str) -> set[str]:
    """Fingerprints of comments DiffWarden already posted on this PR."""
    return {fp for c in await get_all(gh, url) for fp in MARKER.findall(c.get("body") or "")}

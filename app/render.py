from pathlib import PurePosixPath

from app.lines import HUNK, new_side_lines

LOCKFILES = {"package-lock.json", "uv.lock"}


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

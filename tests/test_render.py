import re

from app.lines import commentable_lines
from app.render import annotate, filter_files, make_batches, snippet

PATCH = (
    "@@ -1,3 +1,3 @@\n"
    " a = 1\n"
    "-b = 2\n"
    "+b = 3\n"
    " c = 4\n"
    "@@ -40,2 +40,3 @@\n"
    " x = 1\n"
    "+y = 2\n"
    " z = 3\n"
    "\\ No newline at end of file"
)


def file(name: str, status: str = "modified", patch: str | None = PATCH) -> dict:
    f = {"filename": name, "status": status}
    if patch is not None:
        f["patch"] = patch
    return f


def test_filter_skips_lockfiles_and_other_noise():
    files = [
        file("app/main.py"),
        file("uv.lock"),
        file("frontend/package-lock.json"),
        file("poetry.lock"),
        file("dist/bundle.js"),
        file("static/app.min.js"),
        file("old.py", status="removed"),
        file("logo.png", patch=None),
    ]
    kept, skipped = filter_files(files)
    assert [f["filename"] for f in kept] == ["app/main.py"]
    assert len(skipped) == 7


def test_annotation_labels_match_commentable_lines():
    text = annotate(file("app/main.py"))
    labels = {int(n) for n in re.findall(r"^L(\d+)", text, re.MULTILINE)}
    assert labels == set(commentable_lines(PATCH))


def test_deleted_lines_have_no_label():
    text = annotate(file("app/main.py"))
    deleted = [line for line in text.splitlines() if "b = 2" in line]
    assert deleted == ["      - b = 2"]


def test_snippet_marks_the_line_and_stays_within_radius():
    lines = snippet(file("app/main.py"), line=41, radius=1).splitlines()
    assert lines == ["   L40   x = 1", ">> L41   y = 2", "   L42   z = 3"]


def test_three_25k_blocks_make_two_batches():
    blocks = ["x" * 25_000] * 3
    assert [len(b) for b in make_batches(blocks)] == [50_001, 25_000]


def test_oversized_block_gets_its_own_batch():
    blocks = ["a" * 10, "b" * 70_000, "c" * 10]
    assert [len(b) for b in make_batches(blocks)] == [10, 70_000, 10]

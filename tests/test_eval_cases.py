import json
from pathlib import Path

import pytest

from app.lines import commentable_lines

CASES = sorted(p for p in (Path(__file__).parents[1] / "eval" / "cases").iterdir() if p.is_dir())
CATEGORIES = {"bug", "security", "performance", "maintainability"}


def test_there_is_at_least_one_case():
    assert CASES


def check_bug(bug: dict, lines: dict[int, int]) -> None:
    assert set(bug) == {"start", "end", "category"}
    assert bug["category"] in CATEGORIES
    assert 1 <= bug["start"] <= bug["end"]
    missing = [n for n in range(bug["start"], bug["end"] + 1) if n not in lines]
    assert not missing, f"truth lines {missing} are not commentable in the patch"


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_case_is_well_formed(case: Path):
    patch = (case / "case.patch").read_text(encoding="utf-8")
    truth = json.loads((case / "truth.json").read_text(encoding="utf-8"))
    assert patch.startswith("@@"), "patch must start at the first hunk header (GitHub format)"
    lines = commentable_lines(patch)
    assert lines, "patch has no commentable lines"
    assert truth["path"]

    if truth.get("clean"):
        assert set(truth) == {"path", "clean"}
    elif truth.get("decoy"):
        assert set(truth) == {"path", "decoy"}
    elif "bugs" in truth:
        assert set(truth) == {"path", "bugs"} and len(truth["bugs"]) >= 2
        for bug in truth["bugs"]:
            check_bug(bug, lines)
    else:
        assert set(truth) == {"path", "start", "end", "category"}
        check_bug({k: truth[k] for k in ("start", "end", "category")}, lines)

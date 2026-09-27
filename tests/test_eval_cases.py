import json
from pathlib import Path

import pytest

from app.lines import commentable_lines

CASES = sorted(p for p in (Path(__file__).parents[1] / "eval" / "cases").iterdir() if p.is_dir())


def test_there_is_at_least_one_case():
    assert CASES


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
        return
    assert set(truth) == {"path", "start", "end", "category"}
    assert truth["category"] in {"bug", "security", "performance", "maintainability"}
    assert 1 <= truth["start"] <= truth["end"]
    missing = [n for n in range(truth["start"], truth["end"] + 1) if n not in lines]
    assert not missing, f"truth lines {missing} are not commentable in the patch"

from eval.run import keep, load_cases, matches, score
from app.schema import Finding

TRUTH = {"path": "app/items.py", "start": 35, "end": 35, "category": "bug"}


def finding(**changes) -> Finding:
    base = dict(path="app/items.py", start_line=None, line=35, severity="major", category="bug",
                confidence=0.9, title="t", explanation="e", suggestion=None)
    return Finding(**(base | changes))


def test_match_needs_same_file_and_overlap_within_3_lines():
    assert matches(finding(line=35), TRUTH)
    assert matches(finding(line=38), TRUTH)
    assert not matches(finding(line=39), TRUTH)
    assert matches(finding(start_line=20, line=32), TRUTH)  # a range reaching into the window
    assert not matches(finding(path="app/other.py"), TRUTH)
    assert not matches(finding(), {"path": "app/items.py", "clean": True})


def test_keep_drops_non_commentable_and_low_confidence():
    patch = "@@ -1,1 +1,2 @@\n a = 1\n+b = 2"
    kept = keep([finding(line=2), finding(line=9), finding(line=2, confidence=0.4)], patch, 0.7)
    assert [f.line for f in kept] == [2]


def test_score():
    results = [
        {"truth": TRUTH, "found": True, "latency_s": 2.0, "error": None,
         "findings": [{"match": True}, {"match": False}]},
        {"truth": TRUTH, "found": False, "latency_s": 4.0, "error": None, "findings": []},
        {"truth": {"path": "x", "clean": True}, "found": False, "latency_s": 3.0, "error": None,
         "findings": [{"match": False}]},
    ]
    m = score(results)
    assert (m["recall"], m["precision"], m["fp_per_clean"], m["avg_latency_s"]) == (0.5, 1 / 3, 1.0, 3.0)


def test_all_20_cases_load():
    cases = load_cases()
    assert len(cases) == 20
    assert sum(1 for c in cases if c["truth"].get("clean")) == 5

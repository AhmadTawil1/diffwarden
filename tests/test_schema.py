import pytest
from pydantic import ValidationError

from app.schema import FINDINGS_SCHEMA, Finding, Findings

VALID = {
    "path": "shop/users.py",
    "start_line": None,
    "line": 5,
    "severity": "critical",
    "category": "security",
    "confidence": 0.9,
    "title": "SQL injection",
    "explanation": "user_id is formatted into the query.",
    "suggestion": 'conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))',
}


def test_valid_dict_parses():
    findings = Findings.model_validate({"findings": [VALID]})
    assert findings.findings[0].line == 5


def test_confidence_above_1_is_rejected():
    with pytest.raises(ValidationError):
        Finding(**{**VALID, "confidence": 1.5})


def test_unknown_severity_is_rejected():
    with pytest.raises(ValidationError):
        Finding(**{**VALID, "severity": "blocker"})


def test_json_schema_requires_every_model_field():
    item = FINDINGS_SCHEMA["properties"]["findings"]["items"]
    assert set(item["required"]) == set(Finding.model_fields)

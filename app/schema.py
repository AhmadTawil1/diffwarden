from typing import Literal

from pydantic import BaseModel, Field


class Finding(BaseModel):
    path: str
    start_line: int | None
    line: int = Field(ge=1)
    severity: Literal["critical", "major", "minor"]
    category: Literal["bug", "security", "performance", "maintainability"]
    confidence: float = Field(ge=0, le=1)
    title: str
    explanation: str
    suggestion: str | None


class Findings(BaseModel):
    findings: list[Finding]


class Verdict(BaseModel):
    id: int
    keep: bool
    reason: str


class Verdicts(BaseModel):
    verdicts: list[Verdict]


_NULLABLE_INT = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
_NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {"findings": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": _NULLABLE_INT,
            "line": {"type": "integer"},
            "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
            "category": {"type": "string",
                         "enum": ["bug", "security", "performance", "maintainability"]},
            "confidence": {"type": "number"},
            "title": {"type": "string"},
            "explanation": {"type": "string"},
            "suggestion": _NULLABLE_STR,
        },
        "required": ["path", "start_line", "line", "severity", "category",
                     "confidence", "title", "explanation", "suggestion"],
        "additionalProperties": False,
    }}},
    "required": ["findings"],
    "additionalProperties": False,
}

VERDICTS_SCHEMA = {
    "type": "object",
    "properties": {"verdicts": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "keep": {"type": "boolean"},
                       "reason": {"type": "string"}},
        "required": ["id", "keep", "reason"],
        "additionalProperties": False,
    }}},
    "required": ["verdicts"],
    "additionalProperties": False,
}

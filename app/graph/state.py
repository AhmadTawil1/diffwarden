import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel

from app.schema import Finding


# Lives here rather than in review.py: LangGraph resolves the state's type hints,
# so ReviewJob must be importable where ReviewState is defined (a string forward
# reference would fail), and review.py importing state.py avoids a circular import.
class ReviewJob(BaseModel):
    installation_id: int
    owner: str
    repo: str
    pull_number: int
    head_sha: str


class ReviewState(TypedDict, total=False):
    job: ReviewJob
    files: list[dict]                                     # PR files with patch
    batches: list[str]                                    # annotated prompt per batch
    skipped: list[str]                                    # files not reviewed
    raw_findings: Annotated[list[Finding], operator.add]  # merged from parallel reviews
    verified: list[Finding]
    final: list[Finding]
    fingerprints: list[str]                               # one per final finding
    stale: bool                                           # PR moved to a new commit


class BatchInput(TypedDict):
    prompt: str

"""Strict schemas for candidate rules extracted from process documents.

These schemas describe normative requirements, not observed business events or
approved operating policy. Evidence alignment is checked by process_extractor.
"""

from decimal import Decimal
from typing import Annotated, Any, Literal, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


NonBlankText = Annotated[str, AfterValidator(_nonblank)]


class ProcessSchema(BaseModel):
    """Reject unrecognized fields and non-finite numeric values."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Evidence(ProcessSchema):
    clause_id: NonBlankText
    quote: NonBlankText = Field(description="Exact verbatim substring of this clause")


class NumericConstraint(ProcessSchema):
    field: NonBlankText
    lower: Optional[Decimal]
    upper: Optional[Decimal]
    lower_inclusive: bool = Field(strict=True)
    upper_inclusive: bool = Field(strict=True)
    unit: NonBlankText

    @model_validator(mode="after")
    def validate_interval(self):
        if self.lower is None and self.upper is None:
            raise ValueError("numeric constraint needs at least one bound")
        if self.lower is not None and self.upper is not None:
            if self.lower > self.upper:
                raise ValueError("lower bound must not exceed upper bound")
            if self.lower == self.upper and not (
                self.lower_inclusive and self.upper_inclusive
            ):
                raise ValueError("equal bounds require a closed, nonempty interval")
        return self


class Condition(ProcessSchema):
    text: NonBlankText
    numeric: Optional[NumericConstraint]


class ApprovalGroup(ProcessSchema):
    roles: list[NonBlankText] = Field(min_length=1)
    mode: Literal["all", "any"]


class RelativeDeadline(ProcessSchema):
    value: int = Field(gt=0, strict=True)
    unit: Literal["working_day", "calendar_day", "hour", "minute", "month", "year"]
    anchor: NonBlankText
    relation: Literal["after", "before"]
    text: NonBlankText


class ProcessRule(ProcessSchema):
    id: NonBlankText
    source_clause_id: NonBlankText
    activity: NonBlankText
    action: NonBlankText
    modality: Literal["obligation", "permission", "prohibition"]
    actors: list[NonBlankText]
    recipient_roles: list[NonBlankText] = Field(default_factory=list)
    conditions: list[Condition]
    condition_logic: Literal["all", "any"]
    approvals: Optional[ApprovalGroup]
    required_documents: list[NonBlankText]
    deadline: Optional[RelativeDeadline]
    supporting_clause_ids: list[NonBlankText]
    evidence: list[Evidence] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1, strict=True)


class ClauseAssessment(ProcessSchema):
    clause_id: NonBlankText
    disposition: Literal["rule", "non_normative", "unresolved"]
    reason: NonBlankText


class ProcessRulesResponse(ProcessSchema):
    rules: list[ProcessRule]
    clause_assessments: list[ClauseAssessment]


class SourceClause(ProcessSchema):
    id: NonBlankText
    text: NonBlankText
    start_char: int = Field(ge=0, strict=True)
    end_char: int = Field(gt=0, strict=True)


class EvidenceSpan(ProcessSchema):
    rule_id: NonBlankText
    clause_id: NonBlankText
    quote: NonBlankText
    start_char: int = Field(ge=0, strict=True)
    end_char: int = Field(gt=0, strict=True)


class ProcessExtractionResult(ProcessSchema):
    source_id: NonBlankText
    source_sha256: str
    text_length: int = Field(gt=0, strict=True)
    clauses: list[SourceClause]
    rules: list[ProcessRule]
    evidence_spans: list[EvidenceSpan]
    coverage: dict[str, Any]
    fact_status: Literal["candidate"] = "candidate"
    review_status: Literal["unreviewed"] = "unreviewed"

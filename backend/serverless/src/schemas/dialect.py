from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from utils import clean_quote, normalize_text

MatchType = Literal["exact", "partial", "llm_context", "unchanged"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DialectReplacement(StrictModel):
    source_quote: str = Field(min_length=1)
    standard_text: str = Field(min_length=1)
    evidence_dialect: str = ""
    evidence_standard: str = ""
    match_type: MatchType

    @field_validator(
        "source_quote",
        "standard_text",
        "evidence_dialect",
        "evidence_standard",
        mode="before",
    )
    @classmethod
    def clean_text(cls, value):
        return clean_quote(value)


class DialectNormalizationOutput(StrictModel):
    original_text: str = Field(min_length=1)
    standardized_text: str = Field(min_length=1)
    replacements: list[DialectReplacement]
    unmatched_phrases: list[str]

    @field_validator("original_text", "standardized_text", mode="before")
    @classmethod
    def clean_required_text(cls, value):
        text = normalize_text(value)
        if not text:
            raise ValueError("required text is empty")
        return text

    @field_validator("unmatched_phrases", mode="before")
    @classmethod
    def normalize_unmatched(cls, value):
        if not isinstance(value, list):
            return []
        return [clean_quote(item) for item in value if clean_quote(item)]


def validate_dialect_payload(obj: Any, transcript: str):
    """
    사투리 표준어 변환 LLM 결과 검증.
    - original_text는 원문과 같아야 함
    - replacement.source_quote는 원문에 실제로 있어야 함
    - schema에 없는 필드는 거부
    """
    try:
        model = DialectNormalizationOutput.model_validate(obj)
        payload = model.model_dump()
    except ValidationError as exc:
        return None, format_validation_errors(exc)

    original = normalize_text(payload.get("original_text") or "")
    raw = normalize_text(transcript or "")
    errors = []

    if original != raw:
        errors.append(
            {
                "field": "original_text",
                "type": "original_text_mismatch",
                "message": "original_text must equal the raw patient transcript.",
            }
        )

    raw_for_quote = str(transcript or "")
    for idx, item in enumerate(payload.get("replacements") or []):
        quote = clean_quote(item.get("source_quote") or "")
        if quote and quote not in raw_for_quote:
            errors.append(
                {
                    "field": f"replacements.{idx}.source_quote",
                    "type": "quote_not_grounded",
                    "message": "source_quote must be an exact substring of raw patient transcript.",
                }
            )

    if errors:
        return None, errors
    return payload, []


def format_validation_errors(exc: ValidationError) -> list[dict[str, str]]:
    return [
        {
            "field": ".".join(str(part) for part in err.get("loc", [])),
            "type": str(err.get("type")),
            "message": str(err.get("msg")),
        }
        for err in exc.errors()
    ]

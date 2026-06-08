"""Pydantic schema for question-level LLM extraction.

LLM은 fixed JSON schema 안의 값을 채우는 역할만 합니다. 이 파일은 그 결과가
정말로 우리가 허용한 필드, 타입, enum, 원문 quote 조건을 만족하는지 검증합니다.
"""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator

from utils import clean_quote

SpanType = Literal[
    "symptom",
    "new",
    "symptom_absent",
    "progress_improved",
    "progress_worsened",
    "progress_unchanged",
    "medication",
    "medication_denial",
    "adherence_gap",
    "context",
]

SymptomSlotRef = Literal[
    "hemoptysis",
    "cough",
    "throat_irritation",
    "nasal_obstruction",
    "rhinorrhea",
    "fever",
    "sputum",
    "dyspnea",
    "chest_pain",
    "headache",
    "other",
]

Status = Literal["있음", "없음", "확인필요"]
Priority = Literal["일반", "우선"]

ClinicalCategory = Literal["증상맥락", "복약정보", "복약순응도", "재진경과"]
ClinicalLabel = Literal[
    "시작시점",
    "기간",
    "현재양상",
    "악화요인",
    "완화요인",
    "복용중",
    "처방약 없음",
    "건강보조제",
    "누락",
    "악화",
    "호전",
    "새 증상",
]

AgendaCategory = Literal[
    "drug_drug_interaction",
    "supplement_drug_interaction",
    "food_drug_interaction",
    "treatment_duration",
    "followup_visit",
    "test_question",
    "lifestyle",
    "other",
]


def quote_from_context(info: ValidationInfo) -> str:
    """Pydantic validator에서 환자 원문 transcript를 꺼냅니다."""
    context = info.context if isinstance(info.context, dict) else {}
    return str(context.get("transcript") or "")


def grounded_quote(value: Any, transcript: str) -> str:
    """LLM quote가 환자 원문에 실제로 존재하는 연속 문자열인지 확인합니다.

    공백 차이는 정규화해서 허용하고, LLM이 여러 구절을 한 번에 묶은 경우에는
    원문에 존재하는 최소 구절만 살립니다. 그래도 근거가 없으면 validation 실패입니다.
    """
    quote = clean_quote(value)
    text = str(transcript or "")
    if not quote or not text:
        raise ValueError("quote is empty or transcript is unavailable")
    if quote in text:
        return quote

    compact_quote = re.sub(r"\s+", " ", quote)
    compact_text = re.sub(r"\s+", " ", text)
    if compact_quote in compact_text:
        return compact_quote

    for part in re.split(r"[,，/]| 그리고 | 또 | 혹은 | 또는 ", quote):
        part = clean_quote(part)
        if len(part) >= 3 and part in text:
            return part
    raise ValueError("quote must be an exact substring of the patient answer")


def clean_required_text(value: Any) -> str:
    """필수 문자열 필드를 UI/DB에 넣기 전 안전한 한 줄 문자열로 정리합니다."""
    text = clean_quote(value)
    if not text:
        raise ValueError("required text is empty")
    return text


class StrictModel(BaseModel):
    """예상하지 않은 LLM 필드를 허용하지 않는 공통 base model입니다."""

    model_config = ConfigDict(extra="forbid")


class ExtractionSpan(StrictModel):
    """환자 발화에서 뽑힌 하나의 의미 단위입니다."""

    source_quote: str = Field(min_length=1)
    type: SpanType
    slot_ref: SymptomSlotRef
    name: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    status: Status
    alert: bool
    explain: str = Field(min_length=1)

    @field_validator("source_quote", mode="before")
    @classmethod
    def validate_source_quote(cls, value, info: ValidationInfo):
        return grounded_quote(value, quote_from_context(info))

    @field_validator("name", "normalized_text", "explain", mode="before")
    @classmethod
    def validate_required_text(cls, value):
        return clean_required_text(value)


class ClinicalClue(StrictModel):
    """의사가 증상과 함께 보면 좋은 문진 맥락 단서입니다."""

    category: ClinicalCategory
    label: ClinicalLabel
    summary: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    source_question: str = Field(min_length=1)
    priority: Priority
    related_symptoms: list[str]

    @field_validator("source_quote", mode="before")
    @classmethod
    def validate_source_quote(cls, value, info: ValidationInfo):
        return grounded_quote(value, quote_from_context(info))

    @field_validator("summary", "source_question", mode="before")
    @classmethod
    def validate_required_text(cls, value):
        return clean_required_text(value)

    @field_validator("related_symptoms", mode="before")
    @classmethod
    def normalize_related_symptoms(cls, value):
        if not isinstance(value, list):
            return []
        return [clean_quote(item) for item in value if clean_quote(item)]


class PatientQuestion(StrictModel):
    """Q4에서 분리된 환자 질문 agenda 후보입니다."""

    category: AgendaCategory
    summary: str = Field(min_length=1)
    original_quote: str = Field(min_length=1)

    @field_validator("original_quote", mode="before")
    @classmethod
    def validate_original_quote(cls, value, info: ValidationInfo):
        return grounded_quote(value, quote_from_context(info))

    @field_validator("summary", mode="before")
    @classmethod
    def validate_summary(cls, value):
        return clean_required_text(value)


class StructuredExtraction(StrictModel):
    """LLM extraction의 structured 영역입니다."""

    standardized_text: str = Field(min_length=1)
    clinical_clues: list[ClinicalClue]
    questions: list[PatientQuestion]
    unresolved_items: list[dict[str, Any] | str]

    @field_validator("standardized_text", mode="before")
    @classmethod
    def validate_standardized_text(cls, value):
        return clean_required_text(value)


class ExtractionOutput(StrictModel):
    """문항 하나에 대한 LLM extraction 최상위 schema입니다."""

    spans: list[ExtractionSpan]
    structured: StructuredExtraction


def validate_extraction_payload(obj, transcript):
    """LLM raw JSON을 Pydantic 모델로 검증하고 저장 가능한 dict로 반환합니다."""
    try:
        model = ExtractionOutput.model_validate(obj, context={"transcript": transcript})
        return model.model_dump(), []
    except ValidationError as exc:
        return None, format_validation_errors(exc)


def format_validation_errors(exc):
    """LLM repair prompt에 넣을 수 있도록 Pydantic 오류를 짧은 dict 배열로 정리합니다."""
    errors = []
    for err in exc.errors():
        errors.append({
            "field": ".".join(str(part) for part in err.get("loc", [])),
            "type": err.get("type"),
            "message": err.get("msg"),
        })
    return errors

"""Pydantic schema for patient guide LLM output.

환자 안내문은 어르신에게 직접 보이는 문서이므로, Nova Lite 출력도 고정 schema와
필수 필드 검증을 통과한 뒤에만 후속 품질 검사를 진행합니다.
"""

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from utils import clean_quote


def clean_required_text(value):
    """필수 문자열을 안전하게 정리하고 빈 값은 거부합니다."""
    text = clean_quote(value)
    if not text:
        raise ValueError("required text is empty")
    return text


class StrictModel(BaseModel):
    """LLM이 schema에 없는 필드를 만들면 실패시키는 공통 base model입니다."""

    model_config = ConfigDict(extra="forbid")


class PatientGuideItem(StrictModel):
    """환자 질문 하나에 대응하는 의미 보존 안내문 항목입니다."""

    question: str = Field(min_length=1)
    answer_simple: list[str]
    tts_emphasis_words: list[str]

    @field_validator("question", mode="before")
    @classmethod
    def validate_question(cls, value):
        return clean_required_text(value)

    @field_validator("answer_simple", "tts_emphasis_words", mode="before")
    @classmethod
    def validate_string_list(cls, value):
        if not isinstance(value, list):
            raise ValueError("must be a list")
        return [clean_quote(item) for item in value if clean_quote(item)]


class PatientGuideOutput(StrictModel):
    """Nova Lite patient-guide 출력 schema입니다."""

    items: list[PatientGuideItem]
    delivery_options: list[str]

    @field_validator("delivery_options", mode="before")
    @classmethod
    def validate_delivery_options(cls, value):
        if not isinstance(value, list):
            raise ValueError("must be a list")
        cleaned = [clean_quote(item) for item in value if clean_quote(item)]
        return cleaned or ["screen", "tts", "print"]


def validate_guide_payload(obj):
    """LLM guide JSON을 Pydantic으로 검증하고 dict/errors를 반환합니다."""
    try:
        model = PatientGuideOutput.model_validate(obj)
        return model.model_dump(), []
    except ValidationError as exc:
        return None, format_validation_errors(exc)


def format_validation_errors(exc):
    """guide 생성 실패 이유를 로그/메타데이터에 남기기 쉽게 정리합니다."""
    return [
        {
            "field": ".".join(str(part) for part in err.get("loc", [])),
            "type": err.get("type"),
            "message": err.get("msg"),
        }
        for err in exc.errors()
    ]

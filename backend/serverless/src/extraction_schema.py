"""Pydantic-backed validation for LLM extraction output.

이 파일은 extraction.py가 호출하는 얇은 adapter입니다. 실제 fixed schema는
`schemas/extraction.py`에 있고, 여기서는 question_id 같은 런타임 기본값만 보강한
뒤 Pydantic 검증 결과를 기존 파이프라인 형식으로 돌려줍니다.
"""

import re
from copy import deepcopy

from schemas.extraction import SymptomSlotRef, validate_extraction_payload


SYMPTOM_SLOT_REFS = set(SymptomSlotRef.__args__)
SYMPTOM_QUESTION_TYPES = {"chief_complaint", "progress", "new_symptoms"}
NON_SYMPTOM_SPAN_TYPES = {"medication", "medication_denial", "adherence_gap", "context"}
PATIENT_QUESTION_TYPES = {"patient_questions", "unresolved_questions"}
NEGATIVE_SYMPTOM_PATTERNS = [
    r"^(없어요|없습니다|없다|아니요|괜찮아요|괜찮습니다)[.!?\s]*$",
    r"(아픈|불편|증상).{0,12}(없|아니|괜찮)",
    r"(없|아니|괜찮).{0,12}(아픈|불편|증상)",
]
NEGATIVE_PATIENT_QUESTION_PATTERNS = [
    r"^(없어요|없습니다|없다|아니요|괜찮아요|괜찮습니다)[.!?\s]*$",
    r"(따로|별로|딱히).{0,8}(없|아니)",
    r"(묻고\s*싶|물어\s*볼|궁금|질문).{0,16}(없|아니)",
    r"(없|아니).{0,10}(묻고\s*싶|물어\s*볼|궁금|질문)",
]


def normalize_extraction_output(obj, transcript, question_id, question_type=""):
    """LLM 출력이 fixed schema와 quote grounding을 통과하는지 검증합니다.

    반환 형식은 기존 retry loop와 맞추기 위해 `(normalized, errors)`입니다.
    errors가 비어 있지 않으면 extraction.py가 repair prompt를 만들어 LLM에 다시
    요청합니다.
    """
    prepared = prepare_extraction_payload(obj, question_id, question_type)
    normalized, errors = validate_extraction_payload(prepared, transcript)
    if not errors:
        errors.extend(validate_question_level_requirements(normalized, transcript, question_type))
    if errors:
        return {"spans": [], "structured": empty_structured(transcript)}, errors
    return normalized, []


def prepare_extraction_payload(obj, question_id, question_type=""):
    """LLM 출력에 런타임 기본값을 채워 Pydantic 검증 대상으로 만듭니다.

    이 단계는 의미 값을 창작하지 않습니다. source_quote, category, slot_ref,
    spans/structured 같은 핵심 필드가 없으면 그대로 검증 실패하게 둡니다.
    단, clinical clue의 source_question은 현재 문항 ID라는 런타임 문맥이므로
    누락된 경우에만 보강합니다.
    """
    payload = deepcopy(obj) if isinstance(obj, dict) else {}
    normalize_non_symptom_span_slots(payload, question_type)
    remove_negative_patient_questions(payload, question_type)
    structured = payload.get("structured")
    if isinstance(structured, dict) and isinstance(structured.get("clinical_clues"), list):
        for clue in structured["clinical_clues"]:
            if isinstance(clue, dict):
                clue.setdefault("source_question", question_id)
    return payload


def normalize_non_symptom_span_slots(payload, question_type=""):
    """증상 IR 대상이 아닌 span의 slot_ref를 schema-safe 값으로 정리합니다.

    slot_ref는 Hybrid IR에서 증상 후보를 표준 증상명으로 맞추기 위한 필드입니다.
    Q3 초기 문항의 복약/무복약 답변이나 Q2 복약순응도 답변은 증상 검색 대상이
    아니므로 Nova가 `medication`, `none`, `supplement`처럼 자유롭게 쓴 값을
    그대로 두면 Pydantic enum에서 불필요하게 실패합니다.

    이 함수는 LLM이 추출한 source_quote, type, summary를 바꾸지 않고, 비증상
    span의 무관한 slot_ref만 `other`로 정규화합니다. 증상 문항의 symptom/new/
    progress span은 여전히 엄격한 enum 검증을 그대로 받습니다.
    """
    spans = payload.get("spans")
    if not isinstance(spans, list):
        return

    is_medication_question = question_type in {"current_medications", "adherence"}
    for span in spans:
        if not isinstance(span, dict):
            continue
        span_type = span.get("type")
        slot_ref = span.get("slot_ref")
        if span_type in NON_SYMPTOM_SPAN_TYPES or is_medication_question:
            span["slot_ref"] = "other"
        elif slot_ref not in SYMPTOM_SLOT_REFS:
            # 증상 span의 잘못된 slot_ref는 고치지 않습니다.
            # 그대로 실패해야 LLM repair loop가 다시 작동합니다.
            continue


def remove_negative_patient_questions(payload, question_type=""):
    """Q4의 '질문 없음' 답변이 agenda로 저장되지 않도록 제거합니다.

    이 함수는 환자 질문을 새로 만들지 않습니다. LLM이 이미 `questions` 안에 넣은
    항목 중 원문과 요약이 명백히 "물어볼 것이 없음"을 뜻하는 경우만 제거합니다.
    따라서 "없다는 사실"은 standardized_text와 원문 transcript에는 남고, 의사가
    답변해야 하는 agenda/체크리스트로는 올라가지 않습니다.
    """
    if question_type not in PATIENT_QUESTION_TYPES:
        return

    structured = payload.get("structured")
    if not isinstance(structured, dict):
        return
    questions = structured.get("questions")
    if not isinstance(questions, list):
        return

    structured["questions"] = [
        item for item in questions
        if not is_negative_patient_question_item(item)
    ]


def is_negative_patient_question_item(item):
    """agenda 후보가 실제 질문인지, '질문 없음' 표현인지 판별합니다."""
    if not isinstance(item, dict):
        return False
    text = " ".join([
        str(item.get("summary") or ""),
        str(item.get("original_quote") or ""),
    ]).strip()
    return bool(text and any(re.search(pattern, text) for pattern in NEGATIVE_PATIENT_QUESTION_PATTERNS))


def validate_question_level_requirements(normalized, transcript, question_type=""):
    """문항 단위에서만 판단 가능한 최소 요구사항을 검사합니다.

    Pydantic은 "형식이 맞는가"를 잘 보지만, Q1/Q2/Q3 재진처럼 증상 문항에서
    spans를 빈 배열로 내놓는 의미 누락까지는 알 수 없습니다. 이 함수는 값을
    새로 만들지 않고, 명백히 비어 있으면 retry loop가 LLM에게 다시 추출을
    요청하도록 오류만 추가합니다.
    """
    if question_type not in SYMPTOM_QUESTION_TYPES:
        return []
    if is_negative_symptom_answer(transcript):
        return []
    if normalized.get("spans"):
        return []
    return [
        {
            "loc": ["spans"],
            "msg": "Symptom question answers must include at least one grounded span unless the patient clearly denies symptoms.",
        }
    ]


def is_negative_symptom_answer(transcript):
    """'증상 없음'처럼 span이 없어도 되는 답변인지 최소 패턴으로 확인합니다."""
    text = str(transcript or "").strip()
    return bool(text and any(re.search(pattern, text) for pattern in NEGATIVE_SYMPTOM_PATTERNS))


def empty_structured(transcript):
    """검증 실패 시 DynamoDB에 잘못된 LLM 값을 저장하지 않기 위한 빈 구조입니다."""
    return {
        "standardized_text": transcript or "",
        "clinical_clues": [],
        "questions": [],
        "unresolved_items": [],
    }

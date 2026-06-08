"""증상 상태 분류 정책.

LLM은 환자 발화를 의미 단위(span)로 나누지만, 원페이퍼에 표시할 때는
"현재 불편함"과 "맥락 단서"를 엄격히 구분해야 합니다.

예를 들어 "열은 내렸어요", "지금 열은 없어요"는 의사에게 중요한 정보이지만
오늘의 active symptom 카드로 올라가면 안 됩니다. 이 파일은 그런 상태 판단을
retrieval, onepager, validation에서 공통으로 쓰기 위해 분리한 정책 모듈입니다.
"""

PRESENT_STATUS = "있음"
ABSENT_STATUS = "없음"
UNKNOWN_STATUS = "확인필요"

# 현재 증상 카드와 IR 매칭 대상으로 볼 수 있는 span type입니다.
ACTIVE_SYMPTOM_SPAN_TYPES = {
    "symptom",
    "new",
    "progress_worsened",
    "progress_unchanged",
}

# 환자 문진 맥락으로는 보존하지만, 현재 증상 카드로 올리면 안 되는 span type입니다.
# progress_improved의 status "없음"은 "현재 불편함 카드 대상이 아님"이라는
# 파이프라인 상태값입니다. 원문이 완전 소실을 말하지 않았다면 "완전 해소"라고
# 새 사실을 만들지 않고, clinical_clues에서 호전 맥락으로만 보여줍니다.
NON_ACTIVE_SYMPTOM_SPAN_TYPES = {
    "progress_improved",
    "symptom_absent",
}


def span_type_of(span):
    """span에서 type 문자열을 안전하게 꺼냅니다."""
    return str((span or {}).get("type") or "")


def span_status_of(span):
    """span에서 status 문자열을 안전하게 꺼냅니다."""
    return str((span or {}).get("status") or "")


def is_non_active_symptom_state(span):
    """현재 증상 카드/IR에서 제외해야 하는 증상 상태인지 확인합니다."""
    span_type = span_type_of(span)
    status = span_status_of(span)
    return span_type in NON_ACTIVE_SYMPTOM_SPAN_TYPES or status == ABSENT_STATUS


def is_active_symptom_state(span):
    """현재 불편함으로 표시할 수 있는 증상 상태인지 확인합니다."""
    span_type = span_type_of(span)
    status = span_status_of(span)
    return span_type in ACTIVE_SYMPTOM_SPAN_TYPES and status != ABSENT_STATUS


def is_progress_improved_state(span):
    """이전보다 호전/해소된 증상인지 확인합니다."""
    return span_type_of(span) == "progress_improved"


def is_absent_symptom_state(span):
    """현재 부재가 명시된 증상인지 확인합니다."""
    return span_type_of(span) == "symptom_absent" or span_status_of(span) == ABSENT_STATUS

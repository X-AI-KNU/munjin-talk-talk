"""Onepaper section builders.

S3에 저장된 문항 결과를 의사 화면에서 읽기 쉬운 카드 구조로 바꿉니다.
화면용 onepaper에는 내부 IR 숫자 점수와 후보 목록을 남기지 않습니다. 매칭
근거가 필요할 때는 별도 `llm_trace.redacted.json`의 최소 설명 trace를 봅니다.
"""

import re

from clinical_state import (
    is_absent_symptom_state,
    is_non_active_symptom_state,
    is_progress_improved_state,
    span_type_of,
)
from agenda_categories import infer_agenda_category
from clinical_terms import (
    IR_RED_FLAG_NAMES,
    find_safety_flag,
    find_symptom_quote,
    is_symptom_like_span,
    slot_to_name,
)
from utils import clean_quote, unique, visit_label


def original_source_quote(candidate, transcript, slot_id, hints=None):
    """원페이퍼에는 표준화 문장이 아니라 실제 환자 발화 원문만 인용한다."""
    candidate = clean_quote(candidate or "")
    transcript = clean_quote(transcript or "")
    hints = [clean_quote(hint or "") for hint in (hints or []) if clean_quote(hint or "")]

    if candidate and (not transcript or candidate in transcript):
        return candidate

    if transcript and slot_id:
        restored = find_symptom_quote(transcript, slot_id, hints)
        if restored:
            return restored

    return "" if transcript else candidate


def slot_to_symptom_slot(slot, qid, transcript=""):
    """IR matched_slot을 원페이퍼 증상 카드 schema로 변환합니다."""
    slot_id = slot.get("slot_id") or slot.get("slot_ref")
    span_type = slot.get("span_type") or slot.get("type") or "symptom"
    if not is_symptom_like_span(span_type, slot_id):
        return None

    source_quote = original_source_quote(
        slot.get("source_quote", ""),
        transcript,
        slot_id,
        [slot.get("name", ""), slot.get("normalized_text", "")],
    )

    return {
        "slot_id": slot_id,
        "name": slot.get("name") or slot_to_name(slot_id),
        "source_question": qid,
        "source_quote": source_quote,
        "normalized_text": slot.get("normalized_text") or slot.get("name") or "",
        "status": slot.get("status") or "있음",
        "alert": bool(slot.get("alert")),
        "explain": slot.get("explain") or "환자 발화에서 증상 표현이 확인되었습니다.",
        "ir_method": slot.get("ir_method"),
    }


def dedupe_symptom_slots(slots):
    """같은 표준 증상이 여러 문항에서 나오면 더 중요한 카드만 남깁니다."""
    by_key = {}
    for slot in slots:
        key = slot.get("slot_id") or slot.get("name")
        if not key:
            continue
        old = by_key.get(key)
        if not old or (slot.get("alert") and not old.get("alert")):
            by_key[key] = slot
    return list(by_key.values())


def build_clinical_clues(q1, q2, q3, visit_type):
    """LLM schema 검증을 통과한 clinical_clues만 원페이퍼 단서로 사용합니다."""
    structured_clues = []
    for qid, q in (("Q1", q1), ("Q2", q2), ("Q3", q3)):
        for item in ((q.get("structured") or {}).get("clinical_clues") or []):
            normalized = normalize_clinical_clue(item, qid)
            if normalized:
                structured_clues.append(normalized)
        structured_clues.extend(span_progress_clues(q.get("spans") or [], qid, visit_type))
    return unique_clues(structured_clues)


def span_progress_clues(spans, qid, visit_type):
    """호전/부재 span을 현재 증상 카드 대신 문진 맥락 단서로 보존합니다.

    이 함수는 새로운 증상을 rule-base로 추출하지 않습니다. 이미 LLM과 Pydantic
    검증을 통과한 span 중 `progress_improved`, `symptom_absent`처럼 현재 불편함이
    아닌 상태로 표시된 항목만 원페이퍼 단서로 재배치합니다.
    """
    clues = []
    for span in spans:
        if not isinstance(span, dict):
            continue
        span_type = span_type_of(span)
        slot_ref = span.get("slot_ref")
        if not is_non_active_symptom_state(span):
            continue
        if not is_symptom_like_span(span_type, slot_ref):
            continue
        source_quote = clean_quote(span.get("source_quote") or "")
        if not source_quote:
            continue
        name = clean_quote(span.get("name") or slot_to_name(span.get("slot_ref")) or "증상")
        if is_progress_improved_state(span):
            label = "호전"
            summary = f"{name} 호전됨"
        elif is_absent_symptom_state(span):
            label = "현재양상"
            summary = f"{name} 없음"
        else:
            continue
        category = "재진경과" if visit_type == "followup" or is_progress_improved_state(span) else "증상맥락"
        clues.append({
            "id": f"{qid}-{label}-{source_quote}",
            "category": category,
            "label": label,
            "summary": summary,
            "source_question": qid,
            "source_quote": source_quote,
            "priority": "일반",
            "related_symptoms": [name] if name else [],
            "action_hint": f"{summary} 확인",
            "explain": "LLM이 현재 호소가 아닌 호전/부재 맥락으로 태깅한 항목입니다.",
        })
    return clues


def normalize_clinical_clue(item, default_qid):
    """LLM clinical clue 항목을 UI가 읽는 필드명으로 정리합니다."""
    if not isinstance(item, dict):
        return None
    summary = clean_quote(item.get("summary") or item.get("source_quote") or "")
    source_quote = clean_quote(item.get("source_quote") or summary)
    if not summary and not source_quote:
        return None
    label = clean_quote(item.get("label") or "문진 단서")
    return {
        "id": item.get("id") or f"{default_qid}-{label}-{source_quote}",
        "category": clean_quote(item.get("category") or "증상맥락"),
        "label": label,
        "summary": summary or source_quote,
        "source_question": item.get("source_question") or default_qid,
        "source_quote": source_quote,
        "priority": normalize_clue_priority(item, source_quote),
        "related_symptoms": item.get("related_symptoms") if isinstance(item.get("related_symptoms"), list) else [],
        "action_hint": item.get("action_hint") or f"{label} 확인",
        "explain": item.get("explain") or "Bedrock LLM이 문진 원문에서 추출한 진료 맥락입니다.",
    }


def normalize_clue_priority(item, source_quote):
    if item.get("priority") != "우선":
        return "일반"
    if find_safety_flag(source_quote):
        return "우선"
    related = item.get("related_symptoms") if isinstance(item.get("related_symptoms"), list) else []
    if any(str(name) in IR_RED_FLAG_NAMES for name in related):
        return "우선"
    return "일반"


def unique_clues(clues):
    """동일한 clinical clue가 중복 표시되지 않도록 정리합니다."""
    out = []
    seen = set()
    for item in clues:
        key = (item.get("category"), item.get("label"), item.get("summary"), item.get("source_quote"))
        if key in seen:
            continue
        seen.add(key)
        item = dict(item)
        item["id"] = f"c{len(out) + 1}"
        out.append(item)
    return out


AGENDA_SPLIT_STARTERS = (
    "그리고",
    "또",
    "혹시",
    "머리",
    "두통",
    "진통제",
    "해열제",
    "약",
    "처방",
    "검사",
    "엑스레이",
    "CT",
    "씨티",
    "홍삼",
    "한약",
    "영양제",
    "술",
    "커피",
    "운동",
    "샤워",
    "일",
    "생활",
    "언제",
    "얼마나",
    "며칠",
    "다시",
)

AGENDA_QUESTION_TOKENS = (
    "?",
    "궁금",
    "알고 싶",
    "괜찮",
    "되나",
    "되냐",
    "되나요",
    "될까",
    "먹어도",
    "복용해도",
    "피해야",
    "언제",
    "얼마나",
    "며칠",
    "검사",
    "수 있",
    "줄 수",
    "받을 수",
    "가야",
    "해야",
    "가능",
)


def normalize_agenda(q4):
    """Q4 patient questions를 원페이퍼 우측 질문 카드 목록으로 변환합니다."""
    structured = q4.get("structured", {})
    questions = structured.get("questions") or q4.get("questions") or []
    out = []
    seen = set()
    for item in questions:
        for agenda_item in expand_agenda_item(item):
            key = (
                agenda_item.get("category"),
                agenda_item.get("summary"),
                agenda_item.get("original_quote"),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(agenda_item)
    return out


def expand_agenda_item(item):
    """LLM이 한 카드로 묶은 복수 질문을 원문 근거 단위로 다시 나눕니다."""
    summary = clean_quote(item.get("summary", ""))
    original_quote = clean_quote(item.get("original_quote", ""))
    base_text = original_quote or summary
    pieces = split_agenda_question_text(base_text)

    if len(pieces) <= 1:
        category = infer_agenda_category(
            " ".join([summary, original_quote]),
            item.get("category", "other"),
        )
        return [agenda_payload(category, summary, original_quote)]

    expanded = []
    for piece in pieces:
        category = infer_agenda_category(piece, "other")
        expanded.append(agenda_payload(category, summarize_agenda_piece(piece), piece))
    return expanded


def split_agenda_question_text(text):
    """환자가 한 번에 이어 말한 여러 질문을 보수적으로 분리합니다."""
    normalized = clean_quote(text)
    if not normalized:
        return []

    sentences = [
        clean_quote(part)
        for part in re.split(r"\s*[.?!。！？]\s*", normalized)
        if clean_quote(part)
    ]

    parts = []
    for sentence in sentences:
        parts.extend(split_agenda_connector_piece(sentence))

    question_parts = [part for part in parts if is_agenda_question_like(part)]
    return question_parts if len(question_parts) > 1 else [normalized]


def split_agenda_connector_piece(text):
    starters = "|".join(re.escape(starter) for starter in AGENDA_SPLIT_STARTERS)
    marker = re.compile(
        rf"((?:알고\s*싶고|궁금하고|싶고|괜찮은\s*건지|괜찮을지))\s+(?=(?:{starters}))"
    )
    marked = marker.sub(r"\1 ||| ", clean_quote(text))
    return [clean_quote(part) for part in marked.split("|||") if clean_quote(part)]


def is_agenda_question_like(text):
    normalized = clean_quote(text)
    return any(token in normalized for token in AGENDA_QUESTION_TOKENS)


def summarize_agenda_piece(text):
    normalized = clean_quote(text)
    if "홍삼" in normalized and any(token in normalized for token in ("약", "처방", "복용", "먹")):
        return "홍삼과 약을 함께 복용해도 되는지 문의"
    if any(token in normalized for token in ("영양제", "한약")) and any(
        token in normalized for token in ("약", "처방", "복용", "먹")
    ):
        return "영양제/한약을 약과 함께 복용해도 되는지 문의"
    if "진통제" in normalized:
        if any(token in normalized for token in ("머리", "두통", "아파")):
            return "머리 통증 때문에 진통제를 사용할 수 있는지 문의"
        return "진통제를 사용할 수 있는지 문의"
    if "해열제" in normalized:
        return "해열제를 사용할 수 있는지 문의"
    return normalized


def agenda_payload(category, summary, original_quote):
    category = clean_quote(category or "other") or "other"
    return {
        "type": category,
        "category": category,
        "type_label": agenda_label(category),
        "summary": clean_quote(summary),
        "original_quote": clean_quote(original_quote),
        "source_question": "Q4",
    }


def agenda_label(category):
    """agenda category enum을 의사용 표시명으로 바꿉니다."""
    return {
        "drug_drug_interaction": "복약 상호작용",
        "supplement_drug_interaction": "영양제 병용",
        "food_drug_interaction": "음식-약 상호작용",
        "treatment_duration": "복약 기간",
        "followup_visit": "재내원 기준",
        "test_question": "검사 질문",
        "lifestyle": "생활관리 질문",
    }.get(category, "환자 질문")


def build_transfer_text(patient, slots, clinical, agenda, visit_type):
    """EMR 복사용 초안 문장을 onepaper JSON 근거만으로 만듭니다.

    LLM review가 실패하더라도 의사가 복사할 수 있는 최소 차팅 초안이 필요합니다.
    진찰 전 문진 자료이므로 객관소견/진단/처방을 만들지 않고, S 중심의 간단한
    SOAP-like 문장으로 제한합니다.
    """
    demographics = f"{patient.get('age') or '-'}세 {patient.get('gender') or ''} {visit_label(visit_type)}".strip()
    symptoms = ", ".join(unique([slot.get("name") for slot in slots if slot.get("name")]))
    contexts = unique([
        clean_quote(c.get("summary") or "")
        for c in clinical
        if c.get("summary") and c.get("category") in {"증상맥락", "재진경과", "복약정보", "복약순응도", "약물반응"}
    ])
    med_contexts = [text for text in contexts if any(token in text for token in ("약", "복용", "병용", "처방"))]
    pi_contexts = [text for text in contexts if text not in med_contexts]
    agenda_texts = unique([clean_quote(item.get("summary") or "") for item in agenda if item.get("summary")])

    parts = [f"S) {demographics}"]
    if symptoms:
        parts.append(f"CC: {symptoms}")
    if pi_contexts:
        parts.append(f"PI: {'; '.join(pi_contexts[:2])}")
    if med_contexts:
        parts.append(f"Med: {'; '.join(med_contexts[:2])}")
    if agenda_texts:
        parts.append(f"Q: {'; '.join(agenda_texts[:2])}")

    check_items = []
    if symptoms:
        check_items.append("증상 지속시간/중증도")
    if med_contexts or agenda_texts:
        check_items.append("복약/병용 가능 여부")
    if not check_items:
        check_items.append("문진 내용")
    parts.append(f"확인: {', '.join(unique(check_items))}")

    return " / ".join(part for part in parts if part)

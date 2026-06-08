"""Onepaper section builders.

S3에 저장된 문항 결과를 의사 화면에서 읽기 쉬운 카드 구조로 바꿉니다.
화면용 onepaper에는 내부 IR 숫자 점수와 후보 목록을 남기지 않습니다. 매칭
근거가 필요할 때는 별도 `llm_trace.redacted.json`의 최소 설명 trace를 봅니다.
"""

from clinical_state import (
    is_absent_symptom_state,
    is_non_active_symptom_state,
    is_progress_improved_state,
    span_type_of,
)
from clinical_terms import find_symptom_quote, is_symptom_like_span, slot_to_name
from utils import clean_quote, unique, visit_label


def slot_to_symptom_slot(slot, qid, transcript=""):
    """IR matched_slot을 원페이퍼 증상 카드 schema로 변환합니다."""
    slot_id = slot.get("slot_id") or slot.get("slot_ref")
    span_type = slot.get("span_type") or slot.get("type") or "symptom"
    if not is_symptom_like_span(span_type, slot_id):
        return None

    source_quote = clean_quote(slot.get("source_quote", ""))
    if not source_quote and transcript and slot_id:
        source_quote = find_symptom_quote(transcript, slot_id, [slot.get("name", "")]) or source_quote

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
        "priority": item.get("priority") if item.get("priority") in ("일반", "우선") else "일반",
        "related_symptoms": item.get("related_symptoms") if isinstance(item.get("related_symptoms"), list) else [],
        "action_hint": item.get("action_hint") or f"{label} 확인",
        "explain": item.get("explain") or "Bedrock LLM이 문진 원문에서 추출한 진료 맥락입니다.",
    }


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


def normalize_agenda(q4):
    """Q4 patient questions를 원페이퍼 우측 질문 카드 목록으로 변환합니다."""
    structured = q4.get("structured", {})
    questions = structured.get("questions") or q4.get("questions") or []
    return [{
        "type": item.get("category", "other"),
        "category": item.get("category", "other"),
        "type_label": agenda_label(item.get("category")),
        "summary": item.get("summary", ""),
        "original_quote": item.get("original_quote", ""),
        "source_question": "Q4",
    } for item in questions]


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
    """EMR 복사용 초안 문장을 onepaper JSON 근거만으로 만듭니다."""
    symptoms = ", ".join(unique([slot.get("name") for slot in slots if slot.get("name")]))
    text = f"{patient.get('age') or '-'}세 {patient.get('gender') or ''} {visit_label(visit_type)} 환자."
    if symptoms:
        text += f" {symptoms} 호소."
    med = next((c.get("summary") for c in clinical if c.get("category") == "복약정보"), "")
    if med:
        text += f" {med}."
    if agenda:
        text += f" 환자 질문: {agenda[0].get('summary')}."
    return text

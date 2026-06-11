"""Clinical vocabulary constants and lightweight symptom helpers.

LLM/IR이 공유하는 증상 slot, alias, 안전 플래그 후보를 모아둡니다.
실제 검색 점수 계산은 retrieval.py에서 수행합니다.
"""

import re

from domain_config import alert_slot_ids, get_domain_pack
from utils import clean_quote, find_keyword_quote

_DOMAIN_PACK = get_domain_pack()


# 아래 상수들은 도메인팩 JSON을 기존 코드가 기대하는 tuple/dict 형태로 조립한 값입니다.
# 환자 발화에서 증상을 뽑는 rule-base가 아니라, LLM schema/IR/safety guardrail이
# 참조할 허용 목록과 alias bridge를 데이터화한 것입니다.
SYMPTOM_RULES = [
    (
        str(item.get("name")),
        str(item.get("slot_id")),
        [str(keyword) for keyword in item.get("keywords", [])],
        bool(item.get("alert")),
    )
    for item in _DOMAIN_PACK.get("symptom_rules", [])
    if isinstance(item, dict)
]
VALID_SYMPTOM_SLOT_IDS = {slot_id for _, slot_id, _, _ in SYMPTOM_RULES}
SYMPTOM_SPAN_TYPES = {
    "symptom",
    "new",
    "symptom_absent",
    "worsening",
    "progress_improved",
    "progress_worsened",
    "progress_unchanged",
}

SYMPTOM_QUOTE_PATTERNS = {
    str(slot_id): [str(pattern) for pattern in patterns]
    for slot_id, patterns in (_DOMAIN_PACK.get("symptom_quote_patterns") or {}).items()
    if isinstance(patterns, list)
}

IR_STABLE_SLOT_IDS = dict(_DOMAIN_PACK.get("ir_stable_slot_ids") or {})
IR_SLOT_TO_CANONICAL_NAME = dict(_DOMAIN_PACK.get("ir_slot_to_canonical_name") or {})
IR_TEXT_ALIASES = [
    (str(item.get("pattern")), str(item.get("canonical_name")))
    for item in _DOMAIN_PACK.get("ir_text_aliases", [])
    if isinstance(item, dict) and item.get("pattern") and item.get("canonical_name")
]
IR_RED_FLAG_NAMES = {str(item) for item in _DOMAIN_PACK.get("ir_red_flag_names", [])}
ALERT_SLOT_IDS = alert_slot_ids()

# 안전 플래그는 의도적으로 deterministic 규칙으로 둡니다.
# 진단 목적이 아니라 문진을 잠시 멈추고 직원/의료진 확인으로 넘기기 위한 장치입니다.
SAFETY_FLAG_RULES = [
    (
        str(item.get("category")),
        str(item.get("label")),
        str(item.get("severity") or "medium"),
        str(item.get("pattern")),
    )
    for item in _DOMAIN_PACK.get("safety_flags", [])
    if isinstance(item, dict) and item.get("category") and item.get("pattern")
]


def find_safety_flag(text, matched_slots=None):
    """Return the first deterministic safety flag found in text or IR slots."""
    text = str(text or "")
    for slot in matched_slots or []:
        slot_id = slot.get("slot_id") or slot.get("slot_ref")
        if slot_id in ALERT_SLOT_IDS:
            return {
                "category": slot_id,
                "label": slot.get("name") or slot_id,
                "severity": "high",
                "matched_pattern": slot.get("source_quote") or slot.get("name") or slot_id,
                "message": "우선 확인이 필요한 위험 표현이 있어 의료진 평가가 필요합니다.",
            }
    for category, label, severity, pattern in SAFETY_FLAG_RULES:
        match = re.search(pattern, text)
        if match:
            return {
                "category": category,
                "label": label,
                "severity": severity,
                "matched_pattern": match.group(0),
                "message": "문진 중 우선 확인이 필요한 표현이 감지되었습니다.",
            }
    return None


def find_symptom_quote(text, slot_id, keywords):
    for pattern in SYMPTOM_QUOTE_PATTERNS.get(slot_id, []):
        m = re.search(pattern, text)
        if m:
            return clean_quote(m.group(0))
    return find_keyword_quote(text, keywords)


def is_symptom_like_span(span_type, slot_id):
    if str(span_type or "") not in SYMPTOM_SPAN_TYPES:
        return False
    slot_id = str(slot_id or "")
    if not slot_id or slot_id == "other":
        return True
    if slot_id in VALID_SYMPTOM_SLOT_IDS:
        return True
    return slot_id in IR_SLOT_TO_CANONICAL_NAME

def slot_to_name(slot_id):
    slot_id = str(slot_id or "")
    if slot_id in IR_SLOT_TO_CANONICAL_NAME:
        return IR_SLOT_TO_CANONICAL_NAME[slot_id]
    mapping = {slot_id: name for name, slot_id, _, _ in SYMPTOM_RULES}
    return mapping.get(slot_id, slot_id or "-")

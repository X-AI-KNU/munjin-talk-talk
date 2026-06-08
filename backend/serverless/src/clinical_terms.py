"""Clinical vocabulary constants and lightweight symptom helpers.

LLM/IR이 공유하는 증상 slot, alias, 안전 플래그 후보를 모아둡니다.
실제 검색 점수 계산은 retrieval.py에서 수행합니다.
"""

import re

from utils import clean_quote, find_keyword_quote

SYMPTOM_RULES = [
    ("객혈", "hemoptysis", ["피", "피가", "객혈", "피섞", "피 섞", "묻어"], True),
    ("기침", "cough", ["기침", "콜록"], False),
    ("목 불편감", "throat_irritation", ["목", "칼칼", "따끔", "인후"], False),
    ("코막힘", "nasal_obstruction", ["코가 막", "코막", "맥혀", "막혀"], False),
    ("콧물", "rhinorrhea", ["콧물", "코물"], False),
    ("발열", "fever", ["열", "뜨거", "발열"], False),
    ("가래", "sputum", ["가래", "痰"], False),
    ("호흡곤란", "dyspnea", ["숨", "호흡", "답답"], True),
    ("흉통", "chest_pain", ["가슴", "흉통"], True),
    ("두통", "headache", ["머리", "두통"], False),
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
    "throat_irritation": [
        r"목(?:이|은|도)?\s*(?:좀\s*)?(?:칼칼(?:하고|해요|합니다)?|따끔(?:해요|하고|합니다)?|아파요?|불편해요?|간질간질해요?)",
    ],
    "nasal_obstruction": [
        r"코\S{0,4}\s*(?:막혀요|막혀|막힙니다|맥혀요|맥혀|답답해요)",
    ],
    "rhinorrhea": [
        r"콧물(?:이|은|도)?\s*(?:줄줄\s*)?(?:흐르네요|흘러요|나와요|나요)",
        r"코물(?:이|은|도)?\s*(?:줄줄\s*)?(?:흐르네요|흘러요|나와요|나요)",
    ],
    "cough": [
        r"기침(?:이|은|도)?\s*(?:조금\s*)?(?:나요|나와요|심해요|심해졌어요|해요)",
        r"콜록(?:거려요|거립니다|해요)",
    ],
    "fever": [
        r"(?:열|발열)(?:이|은|도)?\s*(?:나요|있어요|나는 것 같아요)",
    ],
    "sputum": [
        r"가래(?:가|는|도)?\s*(?:나요|나와요|있어요|껴요)",
    ],
}

IR_STABLE_SLOT_IDS = {
    "객혈": "hemoptysis",
    "기침": "cough",
    "목의 통증": "sore_throat",
    "목 자극": "throat_irritation",
    "가래": "sputum",
    "호흡곤란": "dyspnea",
    "숨참": "dyspnea",
    "흉통": "chest_pain",
    "가슴 답답": "chest_discomfort",
    "콧물": "rhinorrhea",
    "코막힘": "nasal_obstruction",
    "발열": "fever",
    "열": "fever",
    "두통": "headache",
    "천명음": "wheezing",
    "목소리 변화": "voice_change",
    "삼키기 곤란": "dysphagia",
}
IR_SLOT_TO_CANONICAL_NAME = {
    "hemoptysis": "객혈",
    "cough": "기침",
    "throat_irritation": "목의 통증",
    "sore_throat": "목의 통증",
    "nasal_obstruction": "코막힘",
    "rhinorrhea": "콧물",
    "sputum": "가래",
    "fever": "열",
    "dyspnea": "호흡곤란",
    "chest_pain": "흉통",
    "wheezing": "천명음",
    "headache": "두통",
    "voice_change": "목소리 변화",
}
IR_TEXT_ALIASES = [
    (r"목|인후|칼칼|따끔", "목의 통증"),
    (r"코.{0,3}(막|맥)|비폐색", "코막힘"),
    (r"콧물|코물", "콧물"),
    (r"가래|객담", "가래"),
    (r"기침|콜록", "기침"),
    (r"피.{0,4}(가래|섞|묻)|객혈", "객혈"),
    (r"숨|호흡곤란|숨참", "호흡곤란"),
    (r"가슴.{0,4}(아프|통증)|흉통", "흉통"),
    (r"쌕쌕|천명", "천명음"),
    (r"열|발열|고열", "열"),
]
IR_RED_FLAG_NAMES = {"객혈", "호흡곤란", "흉통", "청색증", "의식 변화"}

# Quick safety flag rules are intentionally deterministic. They are not used for
# diagnosis; they only pause intake and ask staff/clinicians to review urgently.
SAFETY_FLAG_RULES = [
    ("hemoptysis", "객혈 의심", "high", r"객혈|피(?:가)?\s*(섞인|섞여|나온|나와)|피가래|가래.*피|피.*가래|피를\s*토|피\s*토"),
    ("dyspnea", "호흡곤란", "high", r"숨이\s*(안|너무|많이)\s*(차|막|막혀)|숨\s*못\s*쉬|호흡\s*곤란|말을\s*못\s*할"),
    ("chest_pain", "흉통", "high", r"가슴(?:이)?\s*(통증|아프|아파|아픈|쥐어|답답)|흉통|쥐어짜"),
    ("cyanosis", "청색증", "high", r"입술.*(파래|푸르)|손끝.*(파래|푸르)|청색증"),
    ("consciousness", "의식 변화", "high", r"의식|기절|쓰러졌|정신.*(없|잃)|깨워도"),
    ("high_fever", "고열", "medium", r"고열|열이\s*너무|40도|39도"),
]


def find_safety_flag(text, matched_slots=None):
    """Return the first deterministic safety flag found in text or IR slots."""
    text = str(text or "")
    for slot in matched_slots or []:
        slot_id = slot.get("slot_id") or slot.get("slot_ref")
        if slot_id in ("hemoptysis", "dyspnea", "chest_pain"):
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

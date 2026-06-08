"""Bedrock extraction prompt templates.

문항별 LLM 추출에서 가장 자주 바뀔 수 있는 부분은 프롬프트입니다.
그래서 LLM 호출 노드에서 분리해, 프롬프트 엔지니어링을
할 때 이 파일만 집중해서 볼 수 있게 했습니다.
"""

from settings import LIGHT_MODEL_ID, STRONG_MODEL_ID
from utils import visit_label


def select_extraction_model(visit_type, question_id, question_type):
    """문항 난이도에 따라 Nova Pro/Lite를 선택합니다."""
    if question_type in ("chief_complaint", "progress", "new_symptoms") or question_id in ("Q1",):
        return STRONG_MODEL_ID
    return LIGHT_MODEL_ID


def build_extraction_prompt(visit_type, question_id, question_type, transcript, repair_note="", rag_context_note=""):
    """Nova가 반드시 지켜야 할 quote grounding과 fixed schema를 명시합니다."""
    visit = visit_label(visit_type)
    question_text = {
        "initial": {
            "Q1": "어디가 불편하셔서 오셨어요?",
            "Q2": "그 증상은 언제부터 그러셨어요?",
            "Q3": "지금 드시는 약이 있으세요?",
            "Q4": "의사선생님께 묻고 싶은 점이 있으세요?",
        },
        "followup": {
            "Q1": "지난번 진료 이후 어떻게 지내셨어요?",
            "Q2": "처방받은 약은 잘 드시고 계세요?",
            "Q3": "그동안 새로 생긴 증상은 없으세요?",
            "Q4": "지난번에 못 여쭤본 점이 있으신가요?",
        },
    }.get(visit_type, {}).get(question_id, "")
    return f"""
You are the semantic parsing LLM for a Korean clinic intake MVP.
Task: standardize dialect/colloquial speech, split meaning units, and tag the answer into the fixed schema.

Critical rules:
- Return JSON only. No markdown.
- Never diagnose. Do not infer facts that are not in the patient answer.
- Every source_quote and original_quote MUST be an exact continuous substring of the patient answer.
- If a fact is implied but no exact quote exists, omit it.
- Split multiple patient questions into separate items.
- Use concise Korean summaries for clinicians.
- source_quote is raw patient wording. normalized_text/summary is standardized Korean.
- Do NOT output score, confidence, probability, certainty, or risk percentage fields.
- If unsure, use status "확인필요" and explain the uncertainty in Korean instead of inventing a number.
- For medication, medication_denial, adherence_gap, and context spans, slot_ref MUST be "other".
- Only symptom/new/symptom_absent/progress spans may use symptom slot_ref values such as cough or fever.
- Classify symptom state by the patient's CURRENT meaning, not by keyword presence alone:
  * Current active symptom now present: type "symptom" or "new", status "있음".
  * New symptom after previous visit: type "new", status "있음".
  * Worse than before: type "progress_worsened", status "있음", and add clinical_clue label "악화" when grounded.
  * Still present/similar to before: type "progress_unchanged", status "있음".
  * Explicitly absent now, without saying it improved: type "symptom_absent", status "없음". Example: "열은 안 나요", "가래는 없어요".
  * Resolved or improved previous symptom that should NOT become a current complaint card: type "progress_improved", status "없음". Example: "열은 내렸다", "두통은 없어졌다", "다 나았다", "싹 내렸다".
- Active symptom types (symptom, new, progress_worsened, progress_unchanged) MUST NOT use status "없음".
- Non-active symptom types (symptom_absent, progress_improved) MUST use status "없음" and are not current complaint cards.
- For progress_improved, status "없음" means "not an active current complaint card"; it does NOT mean you may claim full disappearance unless the quote says it disappeared.
- If a symptom improved but is still currently present, split it:
  one active span for the remaining current symptom with status "있음", and one clinical_clue label "호전" for the improvement context.
- Do NOT convert caregiver fear or concern into dyspnea/chest_pain unless the patient or caregiver states actual breathing difficulty, chest pain, cyanosis, fainting, or inability to breathe.
- For Q4 patient_questions/unresolved_questions, a denial such as "없어요", "따로 없어요", "별로 없어요", or "궁금한 건 없어요" is NOT a patient question. Return questions: [].
- For symptom questions (chief_complaint, progress, new_symptoms), spans MUST contain at least one grounded meaning unit unless the patient clearly denies symptoms.
- clinical_clues are optional helper context. Include them only when category, label, and source_quote are all valid.
- clinical_clues.category MUST be exactly one of: 증상맥락, 복약정보, 복약순응도, 재진경과.
- clinical_clues.label MUST be exactly one of: 시작시점, 기간, 현재양상, 악화요인, 완화요인, 복용중, 처방약 없음, 건강보조제, 누락, 악화, 호전, 새 증상.
- clinical_clues.source_quote MUST NOT be empty. If no exact quote exists, omit that clinical_clue.
- The backend validates your output with a strict Pydantic schema. Missing required fields, invalid enum values, or extra fields will fail.

Visit type: {visit}
Question id: {question_id}
Question type: {question_type}
Question asked: {question_text}
Patient answer:
{transcript}

{rag_context_note}

{repair_note}

Allowed symptom slot_ref values when relevant:
hemoptysis, cough, throat_irritation, nasal_obstruction, rhinorrhea, fever, sputum, dyspnea, chest_pain, headache, other

Allowed agenda categories:
drug_drug_interaction, supplement_drug_interaction, food_drug_interaction, treatment_duration, followup_visit, test_question, lifestyle, other

Few-shot examples:

Example 1
Question id: Q1
Question type: chief_complaint
Patient answer:
어제부터 목이 칼칼하고 코가 맥혀요. 기침도 조금 나요.
Expected JSON:
{{
  "spans": [
    {{
      "source_quote": "목이 칼칼하고",
      "type": "symptom",
      "slot_ref": "throat_irritation",
      "name": "목 불편감",
      "normalized_text": "목 자극감",
      "status": "있음",
      "alert": false,
      "explain": "환자가 목의 칼칼함을 직접 호소했습니다."
    }},
    {{
      "source_quote": "코가 맥혀요",
      "type": "symptom",
      "slot_ref": "nasal_obstruction",
      "name": "코막힘",
      "normalized_text": "코막힘",
      "status": "있음",
      "alert": false,
      "explain": "구어체 표현 '맥혀요'는 코가 막힌다는 의미입니다."
    }},
    {{
      "source_quote": "기침도 조금 나요",
      "type": "symptom",
      "slot_ref": "cough",
      "name": "기침",
      "normalized_text": "가벼운 기침",
      "status": "있음",
      "alert": false,
      "explain": "환자가 기침을 동반 증상으로 언급했습니다."
    }}
  ],
  "structured": {{
    "standardized_text": "어제부터 목이 칼칼하고 코가 막히며 기침도 조금 납니다.",
    "clinical_clues": [
      {{
        "category": "증상맥락",
        "label": "시작시점",
        "summary": "어제부터 증상 시작",
        "source_quote": "어제부터",
        "source_question": "Q1",
        "priority": "일반",
        "related_symptoms": ["목 불편감", "코막힘", "기침"]
      }}
    ],
    "questions": [],
    "unresolved_items": []
  }}
}}

Example 2
Question id: Q3
Question type: current_medications
Patient answer:
지금 먹는 약은 없어요.
Expected JSON:
{{
  "spans": [
    {{
      "source_quote": "지금 먹는 약은 없어요",
      "type": "medication_denial",
      "slot_ref": "other",
      "name": "복용 약 없음",
      "normalized_text": "현재 복용 중인 약이 없음",
      "status": "없음",
      "alert": false,
      "explain": "환자가 현재 복용 중인 약이 없다고 말했습니다."
    }}
  ],
  "structured": {{
    "standardized_text": "현재 복용 중인 약은 없다고 말했습니다.",
    "clinical_clues": [
      {{
        "category": "복약정보",
        "label": "처방약 없음",
        "summary": "현재 복용 중인 약은 없다고 말함",
        "source_quote": "지금 먹는 약은 없어요",
        "source_question": "Q3",
        "priority": "일반",
        "related_symptoms": []
      }}
    ],
    "questions": [],
    "unresolved_items": []
  }}
}}

Example 3
Question id: Q3
Question type: current_medications
Patient answer:
영양제만 먹고 있어요.
Expected JSON:
{{
  "spans": [
    {{
      "source_quote": "영양제만 먹고 있어요",
      "type": "medication",
      "slot_ref": "other",
      "name": "영양제",
      "normalized_text": "건강보조제 복용 중",
      "status": "있음",
      "alert": false,
      "explain": "환자가 영양제만 복용 중이라고 말했습니다."
    }}
  ],
  "structured": {{
    "standardized_text": "영양제만 복용 중이라고 말했습니다.",
    "clinical_clues": [
      {{
        "category": "복약정보",
        "label": "건강보조제",
        "summary": "영양제만 복용 중",
        "source_quote": "영양제만 먹고 있어요",
        "source_question": "Q3",
        "priority": "일반",
        "related_symptoms": []
      }}
    ],
    "questions": [],
    "unresolved_items": []
  }}
}}

Example 4
Question id: Q4
Question type: patient_questions
Patient answer:
처방받은 약이랑 영양제 같이 먹어도 되는지 궁금하고, 심해지면 중간에 다시 와도 될까요?
Expected JSON:
{{
  "spans": [],
  "structured": {{
    "standardized_text": "처방약과 영양제를 같이 복용해도 되는지 궁금하고, 증상이 심해지면 중간에 다시 내원해도 되는지 묻고 있습니다.",
    "clinical_clues": [],
    "questions": [
      {{
        "category": "supplement_drug_interaction",
        "summary": "처방약과 영양제 병용 가능 여부 문의",
        "original_quote": "처방받은 약이랑 영양제 같이 먹어도 되는지"
      }},
      {{
        "category": "followup_visit",
        "summary": "증상 악화 시 중간 재내원 가능 여부 문의",
        "original_quote": "심해지면 중간에 다시 와도 될까요"
      }}
    ],
    "unresolved_items": []
  }}
}}

Example 5
Question id: Q4
Question type: patient_questions
Patient answer:
따로 묻고 싶은 건 없어요. 별로 없어요.
Expected JSON:
{{
  "spans": [],
  "structured": {{
    "standardized_text": "의사에게 추가로 묻고 싶은 점은 없다고 말했습니다.",
    "clinical_clues": [],
    "questions": [],
    "unresolved_items": []
  }}
}}

Example 6
Question id: Q1
Question type: progress
Patient answer:
병원서 주사 맞고 약 먹은 뒤루 대가리 아프고 불덩이 같던 열은 마카 싹 내렸소. 큰 열은 내렸는디 어무이가 기운이 안 나서 통 움직이질 못하셔요.
Expected JSON:
{{
  "spans": [
    {{
      "source_quote": "대가리 아프고 불덩이 같던 열은 마카 싹 내렸소",
      "type": "progress_improved",
      "slot_ref": "headache",
      "name": "두통",
      "normalized_text": "두통은 호전됨",
      "status": "없음",
      "alert": false,
      "explain": "환자가 약 복용 뒤 머리 아프던 증상이 내렸다고 말했습니다."
    }},
    {{
      "source_quote": "불덩이 같던 열은 마카 싹 내렸소",
      "type": "progress_improved",
      "slot_ref": "fever",
      "name": "발열",
      "normalized_text": "발열은 호전됨",
      "status": "없음",
      "alert": false,
      "explain": "이전의 큰 열이 현재는 내려갔다고 말했습니다."
    }},
    {{
      "source_quote": "기운이 안 나서 통 움직이질 못하셔요",
      "type": "context",
      "slot_ref": "other",
      "name": "전신 기운 저하",
      "normalized_text": "기운이 없고 움직임이 줄어듦",
      "status": "확인필요",
      "alert": false,
      "explain": "보호자가 환자의 전신 기운 저하를 관찰한 내용입니다. 표준 호흡기 증상으로 단정하지 않습니다."
    }}
  ],
  "structured": {{
    "standardized_text": "주사와 약 복용 후 두통과 발열은 호전되었으나, 보호자는 환자가 기운이 없고 잘 움직이지 못한다고 말했습니다.",
    "clinical_clues": [
      {{
        "category": "재진경과",
        "label": "호전",
        "summary": "두통과 발열은 약 복용 후 호전됨",
        "source_quote": "마카 싹 내렸소",
        "source_question": "Q1",
        "priority": "일반",
        "related_symptoms": ["두통", "발열"]
      }},
      {{
        "category": "증상맥락",
        "label": "현재양상",
        "summary": "보호자가 전신 기운 저하와 활동 감소를 언급",
        "source_quote": "기운이 안 나서 통 움직이질 못하셔요",
        "source_question": "Q1",
        "priority": "일반",
        "related_symptoms": []
      }}
    ],
    "questions": [],
    "unresolved_items": []
  }}
}}

Example 7
Question id: Q3
Question type: new_symptoms
Patient answer:
열은 안 나는디 아직두 물 마시문 자꾸 사레가 걸려 가주고 캑캑거린다 얘. 옆에서 보기에 기침하느라 숨 넘어가실까 봐 너무 겁이 나더래요.
Expected JSON:
{{
  "spans": [
    {{
      "source_quote": "열은 안 나는디",
      "type": "symptom_absent",
      "slot_ref": "fever",
      "name": "발열",
      "normalized_text": "현재 발열은 없음",
      "status": "없음",
      "alert": false,
      "explain": "환자가 현재 열은 나지 않는다고 말했습니다."
    }},
    {{
      "source_quote": "캑캑거린다",
      "type": "new",
      "slot_ref": "cough",
      "name": "기침",
      "normalized_text": "사레와 함께 기침이 남아 있음",
      "status": "있음",
      "alert": false,
      "explain": "물 마실 때 사레가 걸리고 기침한다고 말했습니다."
    }},
    {{
      "source_quote": "숨 넘어가실까 봐 너무 겁이 나더래요",
      "type": "context",
      "slot_ref": "other",
      "name": "보호자 우려",
      "normalized_text": "보호자가 기침 중 안전을 걱정함",
      "status": "확인필요",
      "alert": false,
      "explain": "보호자의 우려 표현이며 실제 호흡곤란으로 단정하지 않습니다."
    }}
  ],
  "structured": {{
    "standardized_text": "현재 열은 없으나 물을 마실 때 사레가 걸리고 기침이 남아 있으며, 보호자는 기침 중 안전을 걱정하고 있습니다.",
    "clinical_clues": [
      {{
        "category": "증상맥락",
        "label": "현재양상",
        "summary": "현재 발열은 없음",
        "source_quote": "열은 안 나는디",
        "source_question": "Q3",
        "priority": "일반",
        "related_symptoms": ["발열"]
      }},
      {{
        "category": "증상맥락",
        "label": "악화요인",
        "summary": "물 마실 때 사레와 기침이 발생",
        "source_quote": "물 마시문 자꾸 사레가 걸려",
        "source_question": "Q3",
        "priority": "일반",
        "related_symptoms": ["기침"]
      }}
    ],
    "questions": [],
    "unresolved_items": []
  }}
}}

Example 8
Question id: Q1
Question type: progress
Patient answer:
기침은 많이 줄었는데 밤에 걸으면 아직 숨이 차요.
Expected JSON:
{{
  "spans": [
    {{
      "source_quote": "기침은 많이 줄었는데",
      "type": "progress_improved",
      "slot_ref": "cough",
      "name": "기침",
      "normalized_text": "기침은 이전보다 호전됨",
      "status": "없음",
      "alert": false,
      "explain": "기침은 이전보다 줄었다고 말했으므로 현재 주된 불편함이 아니라 호전 경과로 분리합니다."
    }},
    {{
      "source_quote": "밤에 걸으면 아직 숨이 차요",
      "type": "progress_unchanged",
      "slot_ref": "dyspnea",
      "name": "호흡곤란",
      "normalized_text": "밤에 걸을 때 숨참이 남아 있음",
      "status": "있음",
      "alert": true,
      "explain": "숨참은 현재도 남아 있는 증상이므로 현재 불편함으로 태깅합니다."
    }}
  ],
  "structured": {{
    "standardized_text": "기침은 이전보다 줄었지만 밤에 걸을 때 숨이 차는 증상은 남아 있습니다.",
    "clinical_clues": [
      {{
        "category": "재진경과",
        "label": "호전",
        "summary": "기침은 이전보다 호전됨",
        "source_quote": "기침은 많이 줄었는데",
        "source_question": "Q1",
        "priority": "일반",
        "related_symptoms": ["기침"]
      }},
      {{
        "category": "증상맥락",
        "label": "악화요인",
        "summary": "밤에 걸을 때 숨참이 남아 있음",
        "source_quote": "밤에 걸으면 아직 숨이 차요",
        "source_question": "Q1",
        "priority": "우선",
        "related_symptoms": ["호흡곤란"]
      }}
    ],
    "questions": [],
    "unresolved_items": []
  }}
}}

Example 9
Question id: Q1
Question type: progress
Patient answer:
기침은 많이 줄었지만 아직 조금씩 나와요.
Expected JSON:
{{
  "spans": [
    {{
      "source_quote": "아직 조금씩 나와요",
      "type": "progress_unchanged",
      "slot_ref": "cough",
      "name": "기침",
      "normalized_text": "기침이 줄었으나 아직 조금 남아 있음",
      "status": "있음",
      "alert": false,
      "explain": "증상이 호전되었지만 현재도 조금 남아 있다고 말했으므로 현재 불편함으로 유지합니다."
    }}
  ],
  "structured": {{
    "standardized_text": "기침은 이전보다 줄었지만 아직 조금씩 남아 있습니다.",
    "clinical_clues": [
      {{
        "category": "재진경과",
        "label": "호전",
        "summary": "기침은 이전보다 줄었음",
        "source_quote": "기침은 많이 줄었지만",
        "source_question": "Q1",
        "priority": "일반",
        "related_symptoms": ["기침"]
      }}
    ],
    "questions": [],
    "unresolved_items": []
  }}
}}

Return exactly this JSON shape:
{{
  "spans": [
    {{
      "source_quote": "exact substring",
      "type": "symptom|new|symptom_absent|progress_improved|progress_worsened|progress_unchanged|medication|medication_denial|adherence_gap|context",
      "slot_ref": "allowed symptom slot_ref or other",
      "name": "display symptom name in Korean",
      "normalized_text": "standard Korean meaning",
      "status": "있음|없음|확인필요",
      "alert": false,
      "explain": "short Korean reason"
    }}
  ],
  "structured": {{
    "standardized_text": "standard Korean rewrite of the answer",
    "clinical_clues": [
      {{
        "category": "증상맥락|복약정보|복약순응도|재진경과",
        "label": "시작시점|기간|현재양상|악화요인|완화요인|복용중|처방약 없음|건강보조제|누락|악화|호전|새 증상",
        "summary": "clinician-facing concise Korean summary",
        "source_quote": "exact substring",
        "source_question": "{question_id}",
        "priority": "일반|우선",
        "related_symptoms": []
      }}
    ],
    "questions": [
      {{
        "category": "allowed agenda category",
        "summary": "concise patient question summary",
        "original_quote": "exact substring"
      }}
    ],
    "unresolved_items": []
  }}
}}
""".strip()


def build_extraction_repair_note(validation_errors, transcript):
    """검증 실패 이유를 LLM에게 다시 넘겨 같은 schema 안에서 재생성하게 합니다."""
    return f"""
Previous output failed validation and must be repaired.
Validation errors:
{validation_errors}

Repair instructions:
- Re-read the patient answer exactly as written.
- Every source_quote/original_quote must be copied as an exact continuous substring.
- Remove any item whose quote cannot be copied from the answer.
- If a clinical_clue has an invalid category/label or empty source_quote, either repair it to the exact allowed literal or remove that clinical_clue.
- For symptom questions, do not return spans: [] unless the answer clearly means no symptoms.
- Use symptom_absent/status "없음" for explicitly absent current symptoms, and progress_improved/status "없음" for resolved or improved previous symptoms.
- Do not use status "없음" with active symptom types such as symptom, new, progress_worsened, or progress_unchanged.
- Keep the same fixed JSON schema.
- Do not add facts, symptoms, medications, tests, or diagnoses that are absent.
- Do not output score, confidence, probability, certainty, or percentage fields.

Allowed clinical_clues.category literals:
증상맥락, 복약정보, 복약순응도, 재진경과

Allowed clinical_clues.label literals:
시작시점, 기간, 현재양상, 악화요인, 완화요인, 복용중, 처방약 없음, 건강보조제, 누락, 악화, 호전, 새 증상

Patient answer for exact quote checking:
{transcript}
""".strip()

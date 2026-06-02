"""Bedrock extraction prompt templates.

문항별 LLM 추출에서 가장 자주 바뀔 수 있는 부분은 프롬프트입니다.
그래서 extraction.py 본문에서 분리해, 프롬프트 엔지니어링을 할 때 이 파일만
집중해서 볼 수 있게 했습니다.
"""

from settings import LIGHT_MODEL_ID, STRONG_MODEL_ID
from utils import visit_label


def select_extraction_model(visit_type, question_id, question_type):
    """문항 난이도에 따라 Nova Pro/Lite를 선택합니다."""
    if question_type in ("chief_complaint", "progress", "new_symptoms") or question_id in ("Q1",):
        return STRONG_MODEL_ID
    return LIGHT_MODEL_ID


def build_extraction_prompt(visit_type, question_id, question_type, transcript, repair_note=""):
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
- Only symptom/new/progress spans may use symptom slot_ref values such as cough or fever.
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

Return exactly this JSON shape:
{{
  "spans": [
    {{
      "source_quote": "exact substring",
      "type": "symptom|new|progress_improved|progress_worsened|progress_unchanged|medication|medication_denial|adherence_gap|context",
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

"""Bedrock extraction prompt templates.

문항별 LLM 추출에서 가장 자주 바뀔 수 있는 부분은 프롬프트입니다.
그래서 LLM 호출 노드에서 분리해, 프롬프트 엔지니어링을
할 때 이 파일만 집중해서 볼 수 있게 했습니다.
"""

from domain_config import llm_symptom_slot_ids
from question_sets import prompt_question_text
from settings import LIGHT_MODEL_ID, STRONG_MODEL_ID
from utils import visit_label


def select_extraction_model(visit_type, question_id, question_type):
    """문항 난이도에 따라 Nova Pro/Lite를 선택합니다."""
    if question_type in ("chief_complaint", "progress", "new_symptoms") or question_id in ("Q1",):
        return STRONG_MODEL_ID
    return LIGHT_MODEL_ID


def build_extraction_prompt(
    visit_type,
    question_id,
    question_type,
    transcript,
    repair_note="",
    rag_context_note="",
    question_text_override="",
    question_set_id="",
    dialect_standardized_text="",
    dialect_replacements=None,
):
    """Nova가 반드시 지켜야 할 quote grounding과 fixed schema를 명시합니다."""
    visit = visit_label(visit_type)
    server_text = prompt_question_text(visit_type, question_id, question_set_id or None)
    # 알려진 기본 문항은 서버 정의가 항상 우선입니다.
    # 클라이언트 override는 서버에 정의되지 않은 커스텀 문항 전용 fallback입니다.
    question_text = str(server_text or question_text_override or "").strip()
    allowed_slots = ", ".join(llm_symptom_slot_ids() + ["other"])
    dialect_note = build_dialect_helper_note(dialect_standardized_text, dialect_replacements or [])
    if dialect_note:
        patient_answer_block = f"""Patient original answer:
{transcript}

{dialect_note}"""
    else:
        patient_answer_block = f"""Patient answer:
{transcript}"""
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
- The span `name` field is an IR search hint, not a final standard symptom label.
- For active symptom spans, keep the patient's core symptom expression and clinically meaningful modifiers.
- Do not force `name` to a closed-set answer. The backend IR/linker is responsible for mapping hints to standard symptom slots.
- Do not collapse a detailed complaint into an overly broad word. Preserve body location, color/character, radiation direction, swelling, sputum character, severity/progression, and timing when stated.
- Do NOT output score, confidence, probability, certainty, or risk percentage fields.
- If unsure, use status "확인필요" and explain the uncertainty in Korean instead of inventing a number.
- For medication, medication_denial, adherence_gap, and context spans, slot_ref MUST be "other".
- Only symptom/new/symptom_absent/progress spans may use symptom slot_ref values such as cough or fever.
- Classify symptom state by the patient's CURRENT meaning, not by keyword presence alone.
- Apply this decision order before choosing type/status:
  1. If the quote means the symptom is absent now, use type "symptom_absent", status "없음".
     Example: "열은 안 나요", "가래는 없어요", "기침은 이제 없어요".
  2. If the quote means a previous symptom improved or resolved and is not the current complaint,
     use type "progress_improved", status "없음".
     Example: "열은 내렸다", "두통은 없어졌다", "다 나았다", "싹 내렸다".
  3. If the quote says a symptom improved but another current symptom remains, split them:
     - put the improved part in clinical_clues label "호전" or a separate progress_improved span only when the quote is separate;
     - create an active span only for the remaining current symptom.
  4. Only if the symptom is currently present, new, worse, or unchanged:
     use type "symptom", "new", "progress_worsened", or "progress_unchanged" with status "있음".
  5. If the answer is ambiguous between resolved and currently present, use status "확인필요" and explain why.
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
{patient_answer_block}

{rag_context_note}

{repair_note}

Allowed symptom slot_ref values when relevant:
{allowed_slots}

Allowed agenda categories:
drug_drug_interaction, supplement_drug_interaction, food_drug_interaction, treatment_duration, followup_visit, test_question, lifestyle, other

Return exactly this JSON shape:
{{
  "spans": [
    {{
      "source_quote": "exact substring",
      "type": "symptom|new|symptom_absent|progress_improved|progress_worsened|progress_unchanged|medication|medication_denial|adherence_gap|context",
      "slot_ref": "allowed symptom slot_ref or other",
      "name": "IR search hint in Korean, preserving the patient's symptom wording and key modifiers",
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


def select_semantic_model(visit_type, question_id, question_type):
    """의미 분할처럼 난도가 높은 단계에 사용할 모델을 선택합니다.

    표준화/태깅/검색 힌트 생성은 비교적 구조적인 작업이라 Lite를 기본으로
    쓰고, Q1 주호소와 재진 경과/새 증상처럼 의료 의미가 복잡한 분할 단계만
    Pro를 사용합니다.
    """
    return select_extraction_model(visit_type, question_id, question_type)


def _prompt_question(visit_type, question_id, question_text_override="", question_set_id=""):
    """프롬프트에 들어갈 서버 확정 질문 문구를 가져옵니다."""
    server_text = prompt_question_text(visit_type, question_id, question_set_id or None)
    return str(server_text or question_text_override or "").strip()


def build_standardization_prompt(
    visit_type,
    question_id,
    question_type,
    transcript,
    dialect_context_note="",
    repair_note="",
    question_text_override="",
    question_set_id="",
):
    """방언/구어체를 표준어 문장으로만 정리하는 첫 단계 prompt입니다."""
    visit = visit_label(visit_type)
    question_text = _prompt_question(visit_type, question_id, question_text_override, question_set_id)
    return f"""
You are the Korean standardization LLM in a clinic intake pipeline.
Your only job is to rewrite the patient answer into standard Korean while preserving meaning.

Hard rules:
- Return JSON only. No markdown.
- Do not diagnose. Do not add, remove, or reinterpret clinical facts.
- Preserve negation, uncertainty, time course, severity, medication names, speaker labels, and caregiver statements.
- Keep the order of meanings close to the original answer.
- Do not split into symptoms yet. Do not tag. Do not produce scores.
- If dialect reference context is provided, use it only for wording normalization.
- If the answer is already standard Korean, keep it almost unchanged.

Generic examples:
Input: "마카 괜찮아졌는데 아직 코가 멕혀요."
Output: {{"standardized_text":"전부 괜찮아졌는데 아직 코가 막혀요.","normalization_notes":["마카를 전부로 표준화"]}}

Input: "기침은 안 나고 목만 좀 칼칼해요."
Output: {{"standardized_text":"기침은 나지 않고 목만 조금 칼칼해요.","normalization_notes":["부정 의미를 유지"]}}

Visit type: {visit}
Question id: {question_id}
Question type: {question_type}
Question asked: {question_text}
Patient answer:
{transcript}

{dialect_context_note}

{repair_note}

Return exactly:
{{
  "standardized_text": "standard Korean rewrite of the full answer",
  "normalization_notes": []
}}
""".strip()


def build_semantic_unit_prompt(
    visit_type,
    question_id,
    question_type,
    transcript,
    standardized_text,
    repair_note="",
    question_text_override="",
    question_set_id="",
):
    """표준화된 의미를 원문 quote 기준의 의미 단위로 나누는 prompt입니다."""
    visit = visit_label(visit_type)
    question_text = _prompt_question(visit_type, question_id, question_text_override, question_set_id)
    return f"""
You are the semantic segmentation LLM in a clinic intake pipeline.
Your job is to split one patient answer into grounded meaning units.

Hard rules:
- Return JSON only. No markdown.
- Every source_quote MUST be an exact continuous substring of the original patient answer.
- Use the standardized answer only to understand meaning; never copy source_quote from standardized_text.
- Split separate symptoms, medication facts, improvement/absence facts, and patient questions into separate units.
- If one sentence contains both improved/resolved symptoms and a remaining current symptom, split them into narrower units with separate exact source_quote values.
- If a medication/adherence sentence also contains a current symptom, split the medication fact and the symptom fact only when the symptom is actually stated as present.
- Do not turn a patient question into an active symptom unless the question itself also states a current complaint.
- Do not assign symptom labels yet. Do not map to standard symptom IDs.
- Do not produce scores or confidence.
- A denial such as "없어요" in Q4 is not a patient question.
- Caregiver fear is context unless actual symptoms such as dyspnea, cyanosis, fainting, or chest pain are stated.

Generic examples:
Original: "열은 내렸는데 아직 목이 칼칼하고 기침이 나요."
Standardized: "열은 내렸는데 아직 목이 칼칼하고 기침이 나요."
Units:
- source_quote "열은 내렸는데", normalized_text "열은 내렸습니다.", role "clinical_meaning"
- source_quote "아직 목이 칼칼하고", normalized_text "아직 목이 칼칼합니다.", role "clinical_meaning"
- source_quote "기침이 나요", normalized_text "기침이 납니다.", role "clinical_meaning"

Original: "혈압약은 매일 먹고 감기약이랑 같이 먹어도 되는지 궁금해요."
Standardized: "혈압약은 매일 먹고 감기약과 같이 먹어도 되는지 궁금합니다."
Units:
- source_quote "혈압약은 매일 먹고", normalized_text "혈압약을 매일 복용합니다.", role "medication"
- source_quote "감기약이랑 같이 먹어도 되는지 궁금해요", normalized_text "감기약과 함께 복용해도 되는지 궁금합니다.", role "patient_question"

Original: "약은 잘 먹고 있는데 물 마시면 계속 사레가 걸려요."
Standardized: "약은 잘 복용하고 있는데 물을 마시면 계속 사레가 걸립니다."
Units:
- source_quote "약은 잘 먹고 있는데", normalized_text "약은 잘 복용하고 있습니다.", role "medication"
- source_quote "물 마시면 계속 사레가 걸려요", normalized_text "물을 마시면 계속 사레가 걸립니다.", role "clinical_meaning"

Original: "따로 궁금한 건 없고 기침은 아직 조금 남았어요."
Standardized: "따로 궁금한 것은 없고 기침은 아직 조금 남았습니다."
Units:
- source_quote "따로 궁금한 건 없고", normalized_text "추가 질문은 없습니다.", role "context"
- source_quote "기침은 아직 조금 남았어요", normalized_text "기침은 아직 조금 남았습니다.", role "clinical_meaning"

Visit type: {visit}
Question id: {question_id}
Question type: {question_type}
Question asked: {question_text}
Original patient answer:
{transcript}

Standardized answer:
{standardized_text}

{repair_note}

Return exactly:
{{
  "meaning_units": [
    {{
      "source_quote": "exact substring from original patient answer",
      "normalized_text": "standard Korean meaning",
      "role": "clinical_meaning|medication|patient_question|context"
    }}
  ],
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
      "category": "drug_drug_interaction|supplement_drug_interaction|food_drug_interaction|treatment_duration|followup_visit|test_question|lifestyle|other",
      "summary": "concise patient question summary",
      "original_quote": "exact substring"
    }}
  ],
  "unresolved_items": []
}}
""".strip()


def build_span_tagging_prompt(
    visit_type,
    question_id,
    question_type,
    transcript,
    standardized_text,
    meaning_units,
    repair_note="",
):
    """의미 단위에 type/status를 붙이는 prompt입니다."""
    visit = visit_label(visit_type)
    return f"""
You are the clinical state tagging LLM in a clinic intake pipeline.
Your job is to classify grounded meaning units into span type and current status.

Hard rules:
- Return JSON only. No markdown.
- Use only the supplied meaning_units. Do not create new source_quote values.
- Do not choose a standard symptom ID yet. Use slot_ref "other" for now.
- Do not produce scores or confidence.
- Classify by current meaning, not keyword presence.
- Current symptoms use type symptom/new/progress_worsened/progress_unchanged with status "있음".
- Explicitly absent symptoms use type symptom_absent with status "없음".
- Improved or resolved previous symptoms use type progress_improved with status "없음".
- Medication facts use medication, medication_denial, or adherence_gap with status "있음" or "없음" as appropriate.
- Patient questions or general context use context with slot_ref "other".
- If the unit is ambiguous, use status "확인필요" and explain why.
- If a unit says a symptom improved/resolved and another symptom remains, the active symptom must come only from the remaining symptom unit.
- Do not mark medication, adherence, patient question, or general context as an active symptom even when symptom words appear in the sentence.
- Active symptom `name` must be concrete enough for search. Avoid standalone "불편함", "증상", "통증", or "아픔" when the unit contains location or quality.

Generic examples:
- "아직 목이 칼칼합니다." -> type symptom, status 있음
- "기침은 나지 않습니다." -> type symptom_absent, status 없음
- "열은 내렸습니다." -> type progress_improved, status 없음
- "항생제를 잘 먹고 있습니다." -> type medication, status 있음
- "약을 자주 빼먹었습니다." -> type adherence_gap, status 있음
- "열은 내렸고 기침만 남았습니다." -> do not make "열" active; if not split, use progress_improved or repair by splitting before tagging.
- "어디가 불편한지는 잘 모르겠습니다." -> type context, status 확인필요, slot_ref other

Visit type: {visit}
Question id: {question_id}
Question type: {question_type}
Original patient answer:
{transcript}

Standardized answer:
{standardized_text}

Meaning units JSON:
{meaning_units}

{repair_note}

Return exactly:
{{
  "spans": [
    {{
      "source_quote": "same exact source_quote from meaning_units",
      "type": "symptom|new|symptom_absent|progress_improved|progress_worsened|progress_unchanged|medication|medication_denial|adherence_gap|context",
      "slot_ref": "other",
      "name": "short grounded search hint, not a UI label",
      "normalized_text": "standard Korean meaning",
      "status": "있음|없음|확인필요",
      "alert": false,
      "explain": "short Korean reason"
    }}
  ]
}}
""".strip()


def build_symptom_hint_prompt(
    visit_type,
    question_id,
    question_type,
    transcript,
    standardized_text,
    tagged_spans,
    rag_context_note="",
    repair_note="",
):
    """IR 검색에 들어갈 symptom name 힌트와 slot_ref를 보강하는 prompt입니다."""
    visit = visit_label(visit_type)
    allowed_slots = ", ".join(llm_symptom_slot_ids() + ["other"])
    return f"""
You are the symptom search-hint LLM in a clinic intake pipeline.
Your job is to make each span easier for deterministic Hybrid IR to search.

Hard rules:
- Return JSON only. No markdown.
- Keep the same number of spans and the same source_quote/type/status values unless a span is clearly non-clinical duplicate.
- Do not output scores or confidence.
- The `name` field is a search hint, not the final UI symptom label.
- For active symptom spans, preserve the patient's wording plus key modifiers: body location, color, sputum character, swelling, radiation, timing, severity, and progression.
- Do not overfit to a closed-set label. Do not invent a diagnosis.
- If an active symptom name is too generic, rewrite it using the most concrete phrase from source_quote/normalized_text.
- Keep the hint short. Prefer "location + symptom/quality" over a full sentence.
- For non-active symptom_absent/progress_improved spans, do not convert them into active symptoms and keep slot_ref "other" unless there is a separate active symptom span.
- For non-symptom spans, keep slot_ref "other".
- For symptom spans, slot_ref may be one of the allowed values only when it is explicit and obvious; otherwise use "other".
- The backend IR/linker will decide the final standard symptom name from source JSON.

Generic examples:
- source_quote "누런 가래가 나와요" -> name "누런 가래 또는 객담", slot_ref "sputum" if available, status "있음"
- source_quote "목이 칼칼해요" -> name "목 칼칼함 또는 인후 자극", slot_ref "sore_throat" if available, status "있음"
- source_quote "다리가 부었어요" -> name "다리 부기", slot_ref "other" unless a matching allowed slot is obvious, status "있음"
- source_quote "어깨에서 팔로 찌르르 뻗쳐요" -> name "팔로 뻗치는 통증", slot_ref "other" unless a matching allowed slot is obvious, status "있음"
- source_quote "열은 내렸어요" -> name "열 호전", slot_ref "other", type "progress_improved", status "없음"
- source_quote "궁금한 건 없어요" -> omit patient question agenda; do not create active symptom span.

Visit type: {visit}
Question id: {question_id}
Question type: {question_type}
Original patient answer:
{transcript}

Standardized answer:
{standardized_text}

Tagged spans JSON:
{tagged_spans}

{rag_context_note}

{repair_note}

Allowed slot_ref values:
{allowed_slots}

Return exactly:
{{
  "spans": [
    {{
      "source_quote": "same exact source_quote",
      "type": "same or corrected span type",
      "slot_ref": "allowed symptom slot_ref or other",
      "name": "IR search hint in Korean",
      "normalized_text": "standard Korean meaning",
      "status": "있음|없음|확인필요",
      "alert": false,
      "explain": "short Korean reason"
    }}
  ]
}}
""".strip()

def build_dialect_helper_note(standardized_text, replacements):
    """extraction LLM이 사투리 의미를 이해하도록 주는 참고 문단입니다."""
    standardized_text = str(standardized_text or "").strip()
    replacements = replacements if isinstance(replacements, list) else []

    if not standardized_text and not replacements:
        return ""

    lines = [
        "Dialect-standardized helper text:",
        standardized_text or "(none)",
        "",
        "Important rules for using dialect helper:",
        "- This helper text is only for understanding dialect/colloquial meaning.",
        "- source_quote and original_quote MUST still be copied from the original patient answer.",
        "- Do not add symptoms, medications, dates, diagnoses, tests, or severity that are absent from the original patient answer.",
    ]

    if replacements:
        lines.append("Dialect replacements:")
        for item in replacements[:8]:
            if not isinstance(item, dict):
                continue
            source = item.get("source_quote") or ""
            target = item.get("standard_text") or ""
            evidence = item.get("evidence_dialect") or ""
            if source or target:
                lines.append(f"- '{source}' → '{target}' (evidence: {evidence})")

    return "\n".join(lines)


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
- If an active symptom span uses a quote that only says the symptom improved, disappeared, or is absent, change it to progress_improved or symptom_absent.
- If a quote contains both improvement and a remaining current symptom, narrow the active span's source_quote to the remaining symptom phrase only.
- For active symptom spans, repair overly generic `name` values into grounded IR search hints.
- Preserve high-signal details from source_quote in name/normalized_text: body location, color/character, radiation direction, swelling, sputum character, severity/progression, and timing.
- Do not add a standard symptom label just because it appears plausible. Keep the hint grounded in the source_quote.
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

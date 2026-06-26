"""의사 답변 저장과 환자 안내문 생성.

의사가 입력한 답변과 환자 안내문은 건강정보가 포함될 수 있으므로
DynamoDB에 직접 저장하지 않습니다. S3 artifact로 저장하고, DynamoDB에는
검토 완료 상태와 artifact key만 남깁니다.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from artifact_store import DOCTOR_REVIEW_FILE, GUIDE_FILE, ONEPAPER_FILE, get_json, put_json
from artifact_policy import prepare_artifact_payload
from llm import call_bedrock_json_with_meta
from schemas.guide import validate_guide_payload
from sessions import get_session, update_session
from settings import GUIDE_MAX_TOKENS, GUIDE_MODEL_ID
from utils import clean_quote, json_default, mask_name, now_iso, response


def save_doctor_response(body: dict[str, Any]):
    """의사 답변을 S3에 저장하고 환자 안내문 생성을 시도합니다."""
    session_id = body.get("session_id") or body.get("sessionId")
    session = get_session(session_id)
    if not session:
        return None, response(404, {"error": "session_not_found"})

    answers = body.get("answers") or []
    if not isinstance(answers, list):
        answers = []
    patient_instruction = (
        body.get("patient_instruction")
        or body.get("patientInstruction")
        or body.get("additional_notes")
        or body.get("additionalNotes")
        or ""
    )
    patient_instruction = clean_quote(patient_instruction)
    onepager = get_json(session, ONEPAPER_FILE, default={}) or {}
    guide = generate_patient_guide(session, onepager, answers, patient_instruction)
    validator_passed = not answers or bool(guide.get("items"))
    guide_ready = bool(guide.get("items") or patient_instruction)
    no_patient_guide_needed = not answers and not patient_instruction

    doctor_review = {
        "answers": answers,
        "patient_instruction": patient_instruction,
        "additional_notes": patient_instruction,
        "reviewed_at": now_iso(),
    }
    put_json(session, DOCTOR_REVIEW_FILE, doctor_review)
    put_json(session, GUIDE_FILE, guide)
    response_guide = prepare_artifact_payload(GUIDE_FILE, guide)

    update_session(session_id, {
        "guide_ready": guide_ready,
        "reviewed_at": doctor_review["reviewed_at"],
        "status": "reviewed",
    })
    return {
        "doctor_review_saved": True,
        "patient_guide_generated": bool(guide.get("items")),
        "no_patient_guide_needed": no_patient_guide_needed,
        "guide_generation_valid": validator_passed,
        "guide_validator_passed": validator_passed,
        # 이전 프론트와의 호환성을 위해 남기지만, 신규 UI에서는 환자 문진 validator와 혼동하지 않습니다.
        "validator_passed": validator_passed,
        "patient_guide": response_guide,
    }, None


def generate_patient_guide(
    session: dict[str, Any],
    onepager: dict[str, Any],
    answers: list[dict[str, Any]],
    patient_instruction: str,
) -> dict[str, Any]:
    """Nova Lite 안내문을 만들고, 실패하면 빈 안내문과 실패 이유만 반환합니다."""
    if not answers:
        return {
            "generated_at": now_iso(),
            "items": [],
            "delivery_options": ["screen", "tts", "print"],
            "generation_method": "no_patient_question_answers",
        }
    try:
        guide = generate_patient_guide_bedrock(session, onepager, answers, patient_instruction)
        if is_patient_guide_usable(guide, answers):
            guide["generation_method"] = "bedrock_nova_lite_grounded"
            return guide
        guide_error = "bedrock_output_failed_quality_validation"
    except Exception as exc:
        guide_error = f"bedrock_exception:{exc.__class__.__name__}"

    return {
        "generated_at": now_iso(),
        "items": [],
        "delivery_options": ["screen", "tts", "print"],
        "generation_method": "bedrock_nova_lite_failed",
        "guide_warning": guide_error,
    }


def generate_patient_guide_bedrock(
    session: dict[str, Any],
    onepager: dict[str, Any],
    answers: list[dict[str, Any]],
    patient_instruction: str,
) -> dict[str, Any]:
    """의사 답변의 의미를 보존한 채 어르신 대상 존댓말 안내문으로 변환합니다."""
    payload = {
        "patient": session.get("patient", {}),
        "onepager": onepager,
        "doctor_answers": answers,
        "doctor_patient_instruction_displayed_separately": patient_instruction,
    }
    prompt = f"""
You are a Korean patient instruction writer for older adults after a clinic visit.
Convert the doctor's answers only into polite Korean honorific guide items for an older patient.
Your job is style conversion, not medical simplification.

Core rules:
- Treat doctor_answers as the authoritative source for answer content.
- Preserve the doctor's exact medical meaning, clinical strength, uncertainty, permissions, warnings, medication names, dosages, timing, follow-up conditions, and exceptions.
- Do NOT simplify, summarize, paraphrase loosely, add explanations, replace medical terms, or change clinical intent.
- If the doctor's answer is already patient-facing Korean, keep it nearly identical and adjust only spacing, punctuation, and polite endings when needed.
- You may split a long doctor answer into short sentences only when every split preserves the same meaning.
- Convert telegraphic clinician style into polite 존댓말 for an older patient.
  Example: "복용 가능" -> "드셔도 됩니다."
  Example: "추가 약 생기면 재확인" -> "다른 약이 추가되면 다시 확인해 주세요."
- Use only information present in doctor_answers, onepager, or the separate doctor instruction.
- Do not invent diagnosis, prescription, dosage, duration, test results, or follow-up dates.
- The field doctor_patient_instruction_displayed_separately is displayed as a separate blue card.
  Do not duplicate it inside question answer items.
- The JSON field name answer_simple is legacy. It must contain meaning-preserving polite Korean sentences, not simplified rewrites.
- Return JSON only. The backend validates the output with a strict schema.

Few-shot examples:

Example 1
Doctor answer: "혈압약은 계속 복용해도 되고, 감기약은 오늘 처방받은 약만 복용하도록 설명."
JSON item:
{{
  "question": "혈압약과 감기약을 같이 먹어도 되는지 궁금함",
  "answer_simple": [
    "혈압약은 계속 드셔도 됩니다.",
    "감기약은 오늘 처방받은 약만 드셔야 합니다."
  ],
  "tts_emphasis_words": ["혈압약", "오늘 처방받은 약"]
}}

Example 2
Doctor answer: "영양제는 이번 처방약과 큰 상호작용은 없어 보이나, 추가 약이 생기면 재확인."
JSON item:
{{
  "question": "영양제를 처방약과 같이 먹어도 되는지 궁금함",
  "answer_simple": [
    "영양제는 이번 처방약과 큰 상호작용은 없어 보입니다.",
    "다른 약이 추가되면 다시 확인해 주세요."
  ],
  "tts_emphasis_words": ["다른 약", "다시 확인"]
}}

Required JSON schema:
{{
  "items": [
    {{
      "question": "patient question summary",
      "answer_simple": ["meaning-preserving polite Korean sentence"],
      "tts_emphasis_words": ["important word"]
    }}
  ],
  "delivery_options": ["screen", "tts", "print"]
}}

Data:
{json.dumps(payload, ensure_ascii=False, default=json_default)}
""".strip()
    obj, raw_text, chain_meta = call_bedrock_json_with_meta(prompt, GUIDE_MODEL_ID, GUIDE_MAX_TOKENS)
    validated_obj, schema_errors = validate_guide_payload(obj)
    if schema_errors:
        raise ValueError(f"guide_pydantic_schema_failed: {schema_errors}")

    items = []
    for item in validated_obj.get("items", []):
        answer_simple = [clean_quote(x) for x in item.get("answer_simple", []) if clean_quote(x)]
        if not answer_simple:
            continue
        items.append({
            "question": clean_quote(item.get("question") or "진료 안내"),
            "answer_simple": answer_simple,
            "tts_emphasis_words": [clean_quote(x) for x in item.get("tts_emphasis_words", []) if clean_quote(x)],
        })
    return {
        "generated_at": now_iso(),
        "items": items,
        "delivery_options": validated_obj.get("delivery_options") or ["screen", "tts", "print"],
        "llm_meta": {
            "model_id": GUIDE_MODEL_ID,
            "raw_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
            "langchain": chain_meta,
        },
    }


def is_patient_guide_usable(guide: dict[str, Any], answers: list[dict[str, Any]]) -> bool:
    """빈 안내문과 근거 없는 일반론을 거부합니다."""
    items = guide.get("items") if isinstance(guide, dict) else []
    if not isinstance(items, list) or not items:
        return False
    generic_patterns = [
        "진료실에서 안내받은 내용을 따라 주세요",
        "오늘 진료에서 안내받은 내용을 확인해 주세요",
        "의사 선생님의 안내를 따라 주세요",
    ]
    usable_count = 0
    for item in items:
        answer_simple = item.get("answer_simple") if isinstance(item, dict) else []
        if not isinstance(answer_simple, list):
            continue
        cleaned = [clean_quote(x) for x in answer_simple if clean_quote(x)]
        if not cleaned:
            continue
        joined = " ".join(cleaned)
        if any(pattern in joined for pattern in generic_patterns):
            continue
        usable_count += 1
    return usable_count > 0


def get_guide(session_id: str) -> dict[str, Any] | None:
    """안내문 화면에서 사용할 환자 안내문과 의사 강조사항을 반환합니다."""
    session = get_session(session_id)
    if not session:
        return None
    guide = get_json(session, GUIDE_FILE, default=None) or {
        "generated_at": now_iso(),
        "items": [],
        "delivery_options": ["screen", "tts", "print"],
        "generation_method": "not_generated",
    }
    doctor_review = get_json(session, DOCTOR_REVIEW_FILE, default={}) or {}
    patient = session.get("patient") or {}
    repair_legacy_name = patient.get("name_mask_version") != "v2"
    return {
        "session_id": session_id,
        "patient_name_masked": mask_name(
            patient.get("name") or patient.get("full_name"),
            repair_legacy_mask=repair_legacy_name,
        ),
        "patient_guide": guide,
        "doctor_additional_notes": (
            doctor_review.get("patient_instruction")
            or doctor_review.get("additional_notes", "")
        ),
    }

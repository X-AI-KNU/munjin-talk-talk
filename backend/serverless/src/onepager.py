"""의사용 원페이퍼 조립과 문항 결과 저장.

문항 처리 결과는 건강정보가 포함된 큰 JSON이므로 DynamoDB에 직접 저장하지
않습니다. 검증된 문항 결과와 원페이퍼는 S3 artifact로 저장하고,
DynamoDB에는 대기열/상태/요약 pointer만 남깁니다.
"""

from __future__ import annotations

from typing import Any

from artifact_store import (
    ONEPAPER_FILE,
    artifact_meta,
    get_json,
    load_answers,
    put_json,
    save_answers,
    save_trace,
)
from artifact_policy import prepare_artifact_payload
from clinical_terms import find_safety_flag
from onepager_review import apply_bedrock_onepager_review
from onepager_sections import (
    build_clinical_clues,
    build_transfer_text,
    dedupe_symptom_slots,
    normalize_agenda,
    slot_to_symptom_slot,
)
from privacy import safety_summary
from sessions import create_session, get_session, update_session
from utils import format_hhmm, mask_name, normalize_visit_type, now_iso, response


def validate_and_save(body: dict[str, Any]):
    """검증된 문항 결과를 S3에 저장하고 DynamoDB 상태만 갱신합니다."""
    session_id = body.get("session_id") or body.get("sessionId")
    question_id = body.get("question_id") or body.get("questionId")
    if not session_id or not question_id:
        return None, response(400, {"error": "missing_session_or_question"})

    session = get_session(session_id)
    if not session:
        session = create_session({"session_id": session_id, "visit_type": body.get("visit_type")})

    transcript = body.get("transcript") or ""
    structured = body.get("structured") or {}
    spans = body.get("spans") or []
    matched_slots = body.get("matched_slots") or []
    orchestration = body.get("orchestration") or {}
    pipeline_trace = body.get("pipeline_trace") or orchestration.get("trace") or []
    safety_flag = scan_safety(transcript, matched_slots)

    answers = load_answers(session)
    answers[question_id] = {
        "text": transcript,
        "dialect_normalization": body.get("dialect_normalization") or {},
        "spans": spans,
        "matched_slots": matched_slots,
        "structured": structured,
        "extract_method": body.get("method") or body.get("extract_method"),
        "confirmed": True,
    }

    risk = "high" if safety_flag or session.get("risk") == "high" else session.get("risk", "none")
    status = next_session_status(session, question_id, safety_flag)
    updated_base = {**session, "responses": answers, "question_results": answers, "risk": risk}
    onepager = build_onepager(updated_base)

    save_answers(session, answers)
    put_json(session, ONEPAPER_FILE, onepager)
    save_trace(
        session,
        question_id,
        {
            "orchestration": orchestration,
            "pipeline_trace": pipeline_trace,
            "matched_count": len(matched_slots),
            "span_count": len(spans),
        },
    )

    question_status = dict(session.get("question_status") or {})
    question_status[question_id] = {
        "answered": True,
        "span_count": len(spans),
        "matched_count": len(matched_slots),
        "method": body.get("method") or body.get("extract_method"),
        "has_safety_flag": bool(safety_flag),
    }

    updates = {
        "artifact": session.get("artifact") or artifact_meta(session_id, session.get("created_at")),
        "question_status": question_status,
        "risk": risk,
        "status": status,
        "onepager_ready": bool(onepager.get("symptom_slots") or onepager.get("agenda") or question_id == "Q4"),
        "safety_flag_summary": safety_summary(safety_flag) or session.get("safety_flag_summary"),
    }
    update_session(session_id, updates)
    return {
        "validator_passed": True,
        "safety_flag": safety_flag,
        "errors": [],
        "onepager_ready": question_id == "Q4",
    }, None


def next_session_status(session: dict[str, Any], question_id: str, safety_flag: dict[str, Any] | None) -> str:
    """문항 저장 이후 DynamoDB session status를 결정합니다."""
    if safety_flag or session.get("risk") == "high" or session.get("status") == "needs_priority":
        return "needs_priority"
    if session.get("analysis_status") in {"pending", "running"}:
        return session.get("status") or "analysis_pending"
    return "waiting_doctor" if question_id == "Q4" else "in_progress"


def scan_safety(transcript: str, matched_slots: list[dict[str, Any]]):
    """위험 표현은 LLM이 아니라 deterministic rule로 재확인합니다."""
    return find_safety_flag(transcript, matched_slots)


def get_onepager_payload(session: dict[str, Any]) -> dict[str, Any]:
    """API 응답용 원페이퍼 payload를 반환합니다.

    이미 S3에 저장된 onepaper artifact가 있으면 재사용하고, 과거 세션처럼
    artifact가 없을 때만 재조립합니다.
    """
    responses = load_answers(session)
    analysis = {
        "status": session.get("analysis_status") or ("ready" if session.get("onepager_ready") else "not_started"),
        "error": session.get("analysis_error") or "",
        "requested_at": session.get("analysis_requested_at") or "",
        "started_at": session.get("analysis_started_at") or "",
        "completed_at": session.get("analysis_completed_at") or "",
    }

    onepager = get_json(session, ONEPAPER_FILE, default=None)
    if not isinstance(onepager, dict) or not onepager:
        # 분석이 백그라운드에서 돌고 있는 세션은 임시 onepaper를 만들지 않습니다.
        # 의사 화면에는 “분석 중/재분석 필요” 상태만 보여 주어 환자 흐름과 분석 흐름을 분리합니다.
        if analysis["status"] in {"pending", "running", "enqueue_failed", "failed", "partial_failed"} or session.get("status") in {"analysis_pending", "analysis_failed"}:
            onepager = build_pending_onepager(session, responses, analysis)
        else:
            onepager = build_onepager(session)
            put_json(session, ONEPAPER_FILE, onepager)
            update_session(session.get("session_id"), {
                "onepager_ready": True,
            })
    onepager["analysis"] = analysis
    onepager = prepare_artifact_payload(ONEPAPER_FILE, onepager)
    return {
        "session": {
            "session_id": session.get("session_id"),
            "case_id": session.get("session_id"),
            "status": session.get("status"),
            "analysis": analysis,
            "visit_type": session.get("visit_type", "initial"),
            "responses": responses,
            "onepager": onepager,
        }
    }


def build_pending_onepager(session: dict[str, Any], responses: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    """분석 대기/실패 상태에서 의사 화면이 깨지지 않도록 최소 onepaper 구조를 만듭니다."""
    patient = session.get("patient", {})
    visit_type = normalize_visit_type(session.get("visit_type"))
    failed = analysis.get("status") in {"failed", "enqueue_failed"}
    return {
        "patient_summary": build_patient_summary(patient, session, visit_type),
        "agenda": [],
        "symptom_slots": [],
        "clinical_clues": [],
        "doctor_brief": {
            "headline": "문진 분석을 다시 실행해 주세요" if failed else "문진 분석 중입니다",
            "priority": "일반",
            "sections": [],
        },
        "review_items": ["문진 분석 결과가 준비되면 다시 확인해 주세요."],
        "transfer_text": "",
        "safety_flags": [],
        "unresolved_items": [],
        "analysis": analysis,
        "raw_answer_count": len(responses or {}),
    }


def rerun_onepager_review(session_id: str):
    """저장된 onepaper를 기준으로 최종 AI 검토만 다시 실행합니다.

    환자 답변 자체를 다시 추출하거나 IR을 다시 돌리지는 않습니다.
    의사가 화면에서 "AI 재검토"를 누를 때 checklist, EMR 초안, doctor brief만
    다시 생성해 보고, 검증을 통과한 결과만 S3 onepaper artifact에 반영합니다.
    """
    session = get_session(session_id)
    if not session:
        return None, response(404, {"error": "session_not_found"})

    onepager = get_json(session, ONEPAPER_FILE, default=None)
    if not isinstance(onepager, dict) or not onepager:
        onepager = build_onepager(session)

    responses = load_answers(session)
    session_for_review = {**session, "responses": responses, "question_results": responses}
    reviewed = apply_bedrock_onepager_review(session_for_review, onepager)
    put_json(session, ONEPAPER_FILE, reviewed)
    updated_session = update_session(session_id, {
        "onepager_ready": True,
        "onepager_reviewed_at": now_iso(),
    }) or session
    return get_onepager_payload(updated_session), None


def build_onepager(session: dict[str, Any]) -> dict[str, Any]:
    """저장된 문항 artifact를 의사용 onepaper JSON으로 조립합니다."""
    patient = session.get("patient", {})
    responses = session.get("responses") or load_answers(session)
    visit_type = normalize_visit_type(session.get("visit_type"))
    q1 = responses.get("Q1", {})
    q2 = responses.get("Q2", {})
    q3 = responses.get("Q3", {})
    q4 = responses.get("Q4", {})

    slots = collect_symptom_slots(q1, q3)
    clinical = build_clinical_clues(q1, q2, q3, visit_type)
    agenda = normalize_agenda(q4)
    safety = scan_safety(
        " ".join([r.get("text", "") for r in responses.values() if isinstance(r, dict)]),
        q1.get("matched_slots", []) + q3.get("matched_slots", []),
    )

    onepager = {
        "patient_summary": build_patient_summary(patient, session, visit_type),
        "agenda": agenda,
        "symptom_slots": slots,
        "clinical_clues": clinical,
        "doctor_brief": {"headline": "", "sections": []},
        "review_items": [],
        "transfer_text": build_transfer_text(patient, slots, clinical, agenda, visit_type),
        "safety_flags": [safety] if safety else [],
        "unresolved_items": [],
    }

    should_run_final_review = bool(q4) or bool(safety)
    if responses and should_run_final_review:
        session_for_review = {**session, "responses": responses, "question_results": responses}
        onepager = apply_bedrock_onepager_review(session_for_review, onepager)
    return onepager


def collect_symptom_slots(q1: dict[str, Any], q3: dict[str, Any]) -> list[dict[str, Any]]:
    """Q1과 재진 Q3의 IR 결과를 원페이퍼 증상 카드로 모읍니다."""
    slots: list[dict[str, Any]] = []
    for slot in q1.get("matched_slots", []):
        normalized_slot = slot_to_symptom_slot(slot, "Q1", q1.get("text", ""))
        if normalized_slot:
            slots.append(normalized_slot)
    for slot in q3.get("matched_slots", []):
        normalized_slot = slot_to_symptom_slot(slot, "Q3", q3.get("text", ""))
        if normalized_slot:
            slots.append(normalized_slot)
    return dedupe_symptom_slots(slots)


def build_patient_summary(patient: dict[str, Any], session: dict[str, Any], visit_type: str) -> dict[str, Any]:
    """원페이퍼 상단 환자 요약 카드를 만듭니다."""
    return {
        "display_name": patient.get("name") or mask_name(patient.get("full_name")),
        "age_text": f"{patient.get('age') or '-'}세",
        "sex": patient.get("gender") or "-",
        "department": patient.get("department") or "이비인후과",
        "received_at": format_hhmm(session.get("created_at")),
        "audio_duration_text": "확인중",
        "visit_type": visit_type,
    }

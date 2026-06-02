"""LangGraph 문진 파이프라인의 실제 처리 노드.

각 함수는 환자 답변 1개를 처리하는 단계 하나입니다. 노드는 가능한 한
작게 유지하고, 라우팅/그래프 조립은 `pipeline_graph.py`에 맡깁니다.
"""

from typing import Any

from clinical_terms import find_safety_flag
from extraction import extract_question
from onepager import validate_and_save
from pipeline_state import AnswerPipelineState, SYMPTOM_QUESTION_TYPES
from pipeline_trace import (
    next_trace_entry,
    orchestration_snapshot,
    persist_final_trace,
    response_errors,
    trace_update,
)
from retrieval import match_slots
from utils import normalize_visit_type, response


def input_transcript_node(state: AnswerPipelineState) -> dict[str, Any]:
    """요청 payload를 표준 필드로 정리하고 필수값을 검증합니다."""
    body = state.get("body") or {}
    session_id = body.get("session_id") or body.get("sessionId")
    question_id = body.get("question_id") or body.get("questionId")
    question_type = body.get("question_type") or body.get("questionType")
    visit_type = normalize_visit_type(body.get("visit_type") or body.get("visitType"))
    transcript = (body.get("transcript") or "").strip()

    update: dict[str, Any] = {
        "session_id": session_id,
        "question_id": question_id,
        "question_type": question_type,
        "visit_type": visit_type,
        "transcript": transcript,
    }
    if not session_id or not question_id or not question_type:
        update["error_response"] = response(400, {"error": "missing_required_fields"})
        update.update(trace_update(state, "input_transcript", "failed", {"reason": "missing_required_fields"}))
        return update
    if not transcript:
        update["error_response"] = response(400, {"error": "empty_transcript"})
        update.update(trace_update(state, "input_transcript", "failed", {"reason": "empty_transcript"}))
        return update

    update.update(
        trace_update(
            state,
            "input_transcript",
            "passed",
            {
                "question_id": question_id,
                "question_type": question_type,
                "visit_type": visit_type,
                "transcript_chars": len(transcript),
            },
        )
    )
    return update


def quick_safety_flag_node(state: AnswerPipelineState) -> dict[str, Any]:
    """LLM 호출 전 즉시 위험 표현을 먼저 감지합니다."""
    safety_flag = find_safety_flag(state.get("transcript") or "", [])
    update = {"preliminary_safety_flag": safety_flag}
    update.update(
        trace_update(
            state,
            "quick_safety_flag",
            "flagged" if safety_flag else "clear",
            {
                "has_flag": bool(safety_flag),
                "flag_type": (safety_flag or {}).get("type"),
                "matched_pattern": (safety_flag or {}).get("matched_pattern"),
            },
        )
    )
    return update


def semantic_extraction_node(state: AnswerPipelineState) -> dict[str, Any]:
    """Bedrock LLM으로 의미 단위 분할, 표준화, 고정 스키마 출력을 수행합니다."""
    body = {
        **(state.get("body") or {}),
        "session_id": state.get("session_id"),
        "question_id": state.get("question_id"),
        "question_type": state.get("question_type"),
        "visit_type": state.get("visit_type"),
        "transcript": state.get("transcript"),
    }
    extracted = extract_question(body)
    llm_meta = extracted.get("llm_meta") or {}
    semantic_failed = extracted.get("validator_passed") is False or extracted.get("method") in {
        "bedrock_error",
        "bedrock_disabled",
    }
    update = {"extracted": extracted, "semantic_failed": semantic_failed}
    update.update(
        trace_update(
            state,
            "semantic_extraction",
            "failed" if semantic_failed else "passed",
            {
                "method": extracted.get("method"),
                "model_id": llm_meta.get("model_id"),
                "attempts": llm_meta.get("attempts"),
                "validation_error_count": len(llm_meta.get("validation_errors") or []),
                "span_count": len(extracted.get("spans") or []),
                "structured_keys": sorted((extracted.get("structured") or {}).keys()),
            },
        )
    )
    return update


def schema_quote_validation_node(state: AnswerPipelineState) -> dict[str, Any]:
    """LLM 출력이 스키마와 원문 quote 검증을 통과했는지 분기합니다."""
    extracted = state.get("extracted") or {}
    if state.get("semantic_failed"):
        safety_flag = state.get("preliminary_safety_flag")
        if safety_flag:
            update = {"safety_only": True}
            update.update(
                trace_update(
                    state,
                    "schema_quote_validation",
                    "safety_branch",
                    {
                        "reason": "semantic_extraction_failed_but_safety_flag_exists",
                        "llm_error": extracted.get("error"),
                    },
                )
            )
            return update
        update = {
            "error_response": response(
                422,
                {
                    "error": "semantic_extraction_failed",
                    "message": extracted.get("error") or "LLM schema/quote validation failed after retries.",
                    "llm_meta": extracted.get("llm_meta") or {},
                },
            )
        }
        update.update(
            trace_update(
                state,
                "schema_quote_validation",
                "failed",
                {
                    "reason": "validator_failed_without_safety_flag",
                    "llm_error": extracted.get("error"),
                },
            )
        )
        return update

    update = {"safety_only": False}
    update.update(
        trace_update(
            state,
            "schema_quote_validation",
            "passed",
            {
                "validator_passed": bool(extracted.get("validator_passed")),
                "retry_loop": (extracted.get("llm_meta") or {}).get("retry_loop"),
            },
        )
    )
    return update


def hybrid_ir_match_node(state: AnswerPipelineState) -> dict[str, Any]:
    """증상 문항이면 BM25 + Titan Vector IR로 표준 증상명에 매칭합니다."""
    question_type = state.get("question_type")
    if question_type not in SYMPTOM_QUESTION_TYPES:
        matched = {"matched_slots": [], "unmatched_spans": []}
        update = {"matched": matched}
        update.update(trace_update(state, "hybrid_ir_match", "skipped", {"question_type": question_type}))
        return update

    extracted = state.get("extracted") or {}
    matched = match_slots(
        {
            "session_id": state.get("session_id"),
            "question_id": state.get("question_id"),
            "visit_type": state.get("visit_type"),
            "spans": extracted.get("spans", []),
        }
    )
    update = {"matched": matched}
    update.update(
        trace_update(
            state,
            "hybrid_ir_match",
            "matched",
            {
                "matched_count": len(matched.get("matched_slots") or []),
                "unmatched_count": len(matched.get("unmatched_spans") or []),
                "method": "bm25_titan_hybrid",
            },
        )
    )
    return update


def session_validation_save_node(state: AnswerPipelineState) -> dict[str, Any]:
    """검증된 문항 결과를 DynamoDB에 저장하고 onepaper를 갱신합니다."""
    extracted = state.get("extracted") or {}
    matched = state.get("matched") or {"matched_slots": [], "unmatched_spans": []}
    save_trace = next_trace_entry(
        state,
        "session_validation_save",
        "saving",
        {"matched_count": len(matched.get("matched_slots") or [])},
    )
    validated, err = validate_and_save(
        {
            "session_id": state.get("session_id"),
            "question_id": state.get("question_id"),
            "question_type": state.get("question_type"),
            "visit_type": state.get("visit_type"),
            "transcript": state.get("transcript"),
            "spans": extracted.get("spans", []),
            "matched_slots": matched.get("matched_slots", []),
            "structured": extracted.get("structured", {}),
            "method": extracted.get("method"),
            "llm_meta": extracted.get("llm_meta") or {},
            "orchestration": orchestration_snapshot(state, save_trace),
            "pipeline_trace": save_trace,
        }
    )
    if err:
        update = {"error_response": err}
        update.update(trace_update(state, "session_validation_save", "failed", {"reason": "validate_and_save_error"}))
        return update

    update = {"validated": validated}
    update.update(
        trace_update(
            state,
            "session_validation_save",
            "saved",
            {
                "validator_passed": bool(validated.get("validator_passed")),
                "onepager_ready": bool(validated.get("onepager_ready")),
                "has_safety_flag": bool(validated.get("safety_flag")),
            },
        )
    )
    return update


def safety_guardrail_save_node(state: AnswerPipelineState) -> dict[str, Any]:
    """LLM 검증 실패 중에도 안전 플래그는 누락되지 않도록 별도 저장합니다."""
    extracted = state.get("extracted") or {}
    safety_flag = state.get("preliminary_safety_flag") or {}
    transcript = state.get("transcript") or ""
    structured = {
        "standardized_text": transcript,
        "clinical_clues": [],
        "questions": [],
        "unresolved_items": [
            {
                "source_quote": safety_flag.get("matched_pattern") or transcript,
                "summary": "안전 플래그 감지 후 LLM 의미 추출 검증에 실패했습니다.",
            }
        ],
    }
    save_trace = next_trace_entry(
        state,
        "safety_guardrail_save",
        "saving",
        {"matched_pattern": safety_flag.get("matched_pattern")},
    )
    validated, err = validate_and_save(
        {
            **(state.get("body") or {}),
            "session_id": state.get("session_id"),
            "question_id": state.get("question_id"),
            "question_type": state.get("question_type"),
            "visit_type": state.get("visit_type"),
            "transcript": transcript,
            "spans": [],
            "matched_slots": [],
            "structured": structured,
            "method": extracted.get("method") or "safety_guardrail_only",
            "llm_meta": {
                **(extracted.get("llm_meta") or {}),
                "semantic_extraction_failed": True,
                "safety_saved_without_extraction": True,
            },
            "orchestration": orchestration_snapshot(state, save_trace),
            "pipeline_trace": save_trace,
        }
    )
    if err:
        update = {"error_response": err}
        update.update(trace_update(state, "safety_guardrail_save", "failed", {"reason": "validate_and_save_error"}))
        return update

    update = {"validated": validated, "matched": {"matched_slots": [], "unmatched_spans": []}}
    update.update(
        trace_update(
            state,
            "safety_guardrail_save",
            "saved",
            {
                "validator_passed": True,
                "has_safety_flag": bool(validated.get("safety_flag") or safety_flag),
            },
        )
    )
    return update


def onepaper_refresh_node(state: AnswerPipelineState) -> dict[str, Any]:
    """저장 단계에서 갱신된 onepaper 상태를 trace에 명시합니다."""
    validated = state.get("validated") or {}
    update: dict[str, Any] = {}
    update.update(
        trace_update(
            state,
            "onepaper_refresh",
            "refreshed",
            {
                "onepager_ready": bool(validated.get("onepager_ready")),
                "refresh_source": "validate_and_save",
            },
        )
    )
    return update


def response_payload_node(state: AnswerPipelineState) -> dict[str, Any]:
    """프론트엔드가 받는 최종 응답 payload를 조립합니다."""
    extracted = state.get("extracted") or {}
    matched = state.get("matched") or {"matched_slots": [], "unmatched_spans": []}
    validated = state.get("validated") or {}
    final_trace = next_trace_entry(
        state,
        "response_payload",
        "completed",
        {"question_id": state.get("question_id")},
    )
    persist_final_trace(state, final_trace)
    payload = {
        "spans": extracted.get("spans", []),
        "structured": extracted.get("structured", {}),
        "matched_slots": matched.get("matched_slots", []),
        "unmatched_spans": matched.get("unmatched_spans", []),
        "validator_passed": bool(validated.get("validator_passed")),
        "safety_flag": validated.get("safety_flag") or state.get("preliminary_safety_flag"),
        "errors": response_errors(state),
        "onepager_ready": validated.get("onepager_ready", False),
        "orchestration": orchestration_snapshot(state, final_trace),
    }
    update = {"result_payload": payload}
    update["trace"] = final_trace
    update["active_path"] = [*state.get("active_path", []), "response_payload"]
    return update

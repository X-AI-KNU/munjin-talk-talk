"""LangGraph 문진 파이프라인의 실제 처리 노드.

각 함수는 환자 답변 1개를 처리하는 단계 하나입니다. 노드는 가능한 한
작게 유지하고, 라우팅/그래프 조립은 `pipeline_graph.py`에 맡깁니다.
"""

import hashlib
from typing import Any

from artifact_policy import sanitize_dialect_normalization, sanitize_matched_slot, sanitize_span
from dialect_normalization import normalize_dialect_text
from clinical_terms import find_safety_flag
from extraction_prompts import build_extraction_prompt, build_extraction_repair_note, select_extraction_model
from extraction_schema import empty_structured, normalize_extraction_output
from llm import call_bedrock_json_with_meta
from onepager import validate_and_save
from pipeline_state import AnswerPipelineState, SYMPTOM_QUESTION_TYPES
from pipeline_trace import (
    next_trace_entry,
    orchestration_snapshot,
    persist_final_trace,
    response_errors,
    trace_update,
)
from question_sets import prompt_question_text
from rag_context import retrieve_intake_rag_context
from retrieval import match_slots
from settings import EXTRACTION_RETRY_ATTEMPTS, MAX_LLM_TOKENS
from utils import normalize_visit_type, response


def input_transcript_node(state: AnswerPipelineState) -> dict[str, Any]:
    """요청 payload를 표준 필드로 정리하고 필수값을 검증합니다."""
    body = state.get("body") or {}
    session_id = body.get("session_id") or body.get("sessionId")
    question_id = body.get("question_id") or body.get("questionId")
    question_type = body.get("question_type") or body.get("questionType")
    question_set_id = (body.get("question_set_id") or body.get("questionSetId") or "").strip()
    visit_type = normalize_visit_type(body.get("visit_type") or body.get("visitType"))
    server_question_text = prompt_question_text(visit_type, question_id, question_set_id or None)
    client_question_text = (body.get("question_text") or body.get("questionText") or "").strip()
    question_text = server_question_text or client_question_text
    transcript = (body.get("transcript") or "").strip()

    update: dict[str, Any] = {
        "session_id": session_id,
        "question_id": question_id,
        "question_type": question_type,
        "question_set_id": question_set_id or "default",
        "question_text": question_text[:300],
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
                "question_set_id": question_set_id or "default",
                "question_text_chars": len(question_text),
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

def dialect_normalization_node(state: AnswerPipelineState) -> dict[str, Any]:
    """
    환자 사투리 원문을 RAG + LLM으로 표준어 문장으로 변환합니다.

    중요:
    - state["transcript"]는 절대 바꾸지 않습니다.
    - 변환 결과는 state["dialect_normalization"]에 별도로 저장합니다.
    """
    transcript = state.get("transcript") or ""
    result = normalize_dialect_text(transcript)

    update = {
        "dialect_normalization": result,
    }

    update.update(
        trace_update(
            state,
            "dialect_normalization",
            "passed" if result.get("validator_passed") else "failed",
            {
                "standardized_chars": len(result.get("standardized_text") or ""),
                "replacement_count": len(result.get("replacements") or []),
                "hint_count": len((result.get("dialect_context") or {}).get("hints") or []),
                "model_id": (result.get("llm_meta") or {}).get("model_id"),
            },
        )
    )

    return update


def rag_context_retrieval_node(state: AnswerPipelineState) -> dict[str, Any]:
    """LLM extraction 전에 원천 JSON 기반 RAG 참고 문맥을 검색합니다."""
    raw_text = state.get("transcript") or ""
    dialect_normalization = state.get("dialect_normalization") or {}
    dialect_standardized_text = dialect_normalization.get("standardized_text") or ""

    rag_query = " ".join(
        text
        for text in [raw_text, dialect_standardized_text]
        if text
    )

    rag_context = retrieve_intake_rag_context(rag_query, question_type=state.get("question_type"))
    update = {"rag_context": rag_context}
    update.update(
        trace_update(
            state,
            "rag_context_retrieval",
            "retrieved",
            {
                "retriever": rag_context.get("retriever"),
                "alias_hint_count": len(rag_context.get("alias_hints") or []),
                "symptom_reference_count": len(rag_context.get("symptom_references") or []),
                "source_files": rag_context.get("source_files") or [],
            },
        )
    )
    return update


def semantic_extraction_node(state: AnswerPipelineState) -> dict[str, Any]:
    """LangChain Runnable chain으로 Bedrock extraction JSON을 생성합니다."""
    question_id = state.get("question_id") or ""
    question_type = state.get("question_type") or ""
    visit_type = state.get("visit_type") or ""
    transcript = state.get("transcript") or ""
    attempt = int(state.get("extraction_attempt") or 0) + 1
    model_id = select_extraction_model(visit_type, question_id, question_type)
    rag_context = state.get("rag_context") or {}
    try:
        prompt = build_extraction_prompt(
            visit_type,
            question_id,
            question_type,
            transcript,
            repair_note=state.get("repair_note") or "",
            rag_context_note=rag_context.get("prompt_note") or "",
            question_text_override=state.get("question_text") or "",
            question_set_id=state.get("question_set_id") or "",
            dialect_standardized_text=dialect_normalization.get("standardized_text") or "",
            dialect_replacements=dialect_normalization.get("replacements") or [],
        )
        obj, raw_text, chain_meta = call_bedrock_json_with_meta(prompt, model_id, MAX_LLM_TOKENS)
    except Exception as exc:
        extracted = {
            "spans": [],
            "structured": empty_structured(transcript),
            "transcript": transcript,
            "method": "bedrock_error",
            "validator_passed": False,
            "error": "Bedrock extraction failed before schema validation.",
            "llm_meta": {
                "model_id": model_id,
                "attempts": attempt,
                "retry_loop": "langgraph_schema_quote_repair",
                "langchain": {
                    "chain": "langchain_core_prompt_bedrock_json",
                    "error_type": exc.__class__.__name__,
                },
            },
        }
        update = {
            "extraction_attempt": attempt,
            "extraction_raw": {},
            "extraction_raw_text": "",
            "extraction_chain_meta": extracted["llm_meta"]["langchain"],
            "retry_extraction": False,
            "extracted": extracted,
            "semantic_failed": True,
        }
        update.update(trace_update(state, "semantic_extraction", "failed", extracted["llm_meta"]))
        return update

    update = {
        "extraction_attempt": attempt,
        "extraction_raw": obj,
        "extraction_raw_text": raw_text,
        "extraction_chain_meta": chain_meta,
        "retry_extraction": False,
        "semantic_failed": False,
    }
    update.update(
        trace_update(
            state,
            "semantic_extraction",
            "generated",
            {
                "attempt": attempt,
                "model_id": model_id,
                "langchain_chain": chain_meta.get("chain"),
                "prompt_adapter": chain_meta.get("prompt_adapter"),
                "bedrock_runnable": chain_meta.get("bedrock_runnable"),
                "output_parser": chain_meta.get("output_parser"),
                "rag_alias_hint_count": len(rag_context.get("alias_hints") or []),
                "rag_symptom_reference_count": len(rag_context.get("symptom_references") or []),
                "raw_sha256": chain_meta.get("raw_sha256"),
            },
        )
    )
    return update


def schema_quote_validation_node(state: AnswerPipelineState) -> dict[str, Any]:
    """LLM 출력 JSON을 Pydantic schema와 source_quote 규칙으로 검증합니다."""
    transcript = state.get("transcript") or ""
    question_id = state.get("question_id") or ""
    question_type = state.get("question_type") or ""
    attempt = int(state.get("extraction_attempt") or 1)
    max_attempts = max(1, EXTRACTION_RETRY_ATTEMPTS)
    chain_meta = state.get("extraction_chain_meta") or {}

    if state.get("semantic_failed") and not state.get("extraction_raw"):
        extracted = state.get("extracted") or {}
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
        preserved = preserve_non_symptom_context(
            state,
            reason="bedrock_or_schema_failed_before_payload",
            extracted_error=extracted.get("error"),
        )
        if preserved:
            return preserved
        update = {
            "error_response": response(
                422,
                {
                    "error": "semantic_extraction_failed",
                    "message": extracted.get("error") or "LLM schema/quote validation failed after retries.",
                    "details": {
                        "attempts": attempt,
                        "retry_loop": "langgraph_schema_quote_repair",
                    },
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

    normalized, validation_errors = normalize_extraction_output(
        state.get("extraction_raw") or {},
        transcript,
        question_id,
        question_type,
    )
    if not validation_errors:
        extracted = normalized or {"spans": [], "structured": empty_structured(transcript)}
        raw_text = state.get("extraction_raw_text") or ""
        extracted.update(
            {
                "transcript": transcript,
                "method": "bedrock_nova",
                "validator_passed": True,
                "llm_meta": {
                    "model_id": chain_meta.get("model_id"),
                    "raw_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                    "langchain": chain_meta,
                    "rag_context": summarize_rag_context(state.get("rag_context") or {}),
                    "validation_errors": [],
                    "attempts": attempt,
                    "retry_loop": "langgraph_schema_quote_repair",
                },
            }
        )
        update = {
            "extracted": extracted,
            "semantic_failed": False,
            "safety_only": False,
            "retry_extraction": False,
            "extraction_validation_errors": [],
            "repair_note": "",
        }
        update.update(
            trace_update(
                state,
                "schema_quote_validation",
                "passed",
                {
                    "validator": "pydantic_extraction_schema",
                    "source_quote_grounding": "passed",
                    "attempt": attempt,
                    "span_count": len(extracted.get("spans") or []),
                    "structured_keys": sorted((extracted.get("structured") or {}).keys()),
                    "langchain_output_parser": chain_meta.get("output_parser"),
                },
            )
        )
        return update

    if attempt < max_attempts:
        repair_note = build_extraction_repair_note(validation_errors, transcript)
        update = {
            "retry_extraction": True,
            "semantic_failed": False,
            "extraction_validation_errors": validation_errors,
            "repair_note": repair_note,
        }
        update.update(
            trace_update(
                state,
                "schema_quote_validation",
                "retry",
                {
                    "validator": "pydantic_extraction_schema",
                    "source_quote_grounding": "failed",
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "validation_error_count": len(validation_errors),
                    "validation_errors": validation_errors[:5],
                    "next_node": "semantic_extraction",
                },
            )
        )
        return update

    extracted = {
        "spans": [],
        "structured": empty_structured(transcript),
        "transcript": transcript,
        "method": "bedrock_nova",
        "validator_passed": False,
        "error": "LLM schema/quote validation failed after retries.",
        "llm_meta": {
            "model_id": chain_meta.get("model_id"),
            "raw_sha256": hashlib.sha256((state.get("extraction_raw_text") or "").encode("utf-8")).hexdigest(),
            "langchain": chain_meta,
            "rag_context": summarize_rag_context(state.get("rag_context") or {}),
            "validation_errors": validation_errors,
            "attempts": attempt,
            "retry_loop": "langgraph_schema_quote_repair",
        },
    }
    safety_flag = state.get("preliminary_safety_flag")
    if safety_flag:
        update = {
            "extracted": extracted,
            "semantic_failed": True,
            "safety_only": True,
            "retry_extraction": False,
            "extraction_validation_errors": validation_errors,
        }
        update.update(
            trace_update(
                state,
                "schema_quote_validation",
                "safety_branch",
                {
                    "reason": "validator_failed_after_retries_but_safety_flag_exists",
                    "validation_error_count": len(validation_errors),
                    "attempt": attempt,
                },
            )
        )
        return update

    preserved = preserve_non_symptom_context(
        state,
        reason="schema_quote_failed_after_retries",
        validation_errors=validation_errors,
        extracted_error=extracted.get("error"),
    )
    if preserved:
        return preserved

    update = {
        "extracted": extracted,
        "semantic_failed": True,
        "retry_extraction": False,
        "error_response": response(
            422,
            {
                "error": "semantic_extraction_failed",
                "message": extracted.get("error"),
                "details": {
                    "attempts": attempt,
                    "retry_loop": "langgraph_schema_quote_repair",
                    "validation_error_count": len(validation_errors),
                },
            },
        ),
    }
    update.update(
        trace_update(
            state,
            "schema_quote_validation",
            "failed",
            {
                "reason": "validator_failed_without_safety_flag",
                "validation_error_count": len(validation_errors),
                "validation_errors": validation_errors[:5],
                "attempt": attempt,
            },
        )
    )
    return update


NON_SYMPTOM_FALLBACK_CONFIG = {
    "onset": {
        "category": "증상맥락",
        "label": "시작시점",
    },
    "current_medications": {
        "category": "복약정보",
        "label": "복용중",
    },
    "adherence": {
        "category": "복약순응도",
        "label": "복용중",
    },
}


def preserve_non_symptom_context(
    state: AnswerPipelineState,
    reason: str,
    validation_errors: list[dict[str, Any]] | None = None,
    extracted_error: str | None = None,
) -> dict[str, Any] | None:
    """비증상 문항의 LLM 구조화 실패 시 원문 답변을 임상 맥락으로 보존합니다.

    Q2 시작 시점, Q3 복약 정보처럼 증상 IR 대상이 아닌 문항은 실패하더라도
    환자 흐름을 멈출 이유가 적습니다. 여기서는 새로운 의학적 사실을 만들지 않고
    환자가 확인한 원문 전체를 source_quote/summary로 남겨 의사가 볼 수 있게 합니다.
    증상 문항은 이 우회 경로를 타지 않으므로, 증상 매칭 품질 검증은 그대로 엄격하게
    유지됩니다.
    """
    question_type = state.get("question_type") or ""
    transcript = (state.get("transcript") or "").strip()
    if not transcript or question_type in SYMPTOM_QUESTION_TYPES:
        return None

    question_id = state.get("question_id") or ""
    chain_meta = state.get("extraction_chain_meta") or {}
    attempt = int(state.get("extraction_attempt") or 1)
    structured = fallback_structured(question_type, question_id, transcript)
    if structured is None:
        return None

    extracted = {
        "spans": [],
        "structured": structured,
        "transcript": transcript,
        "method": "bedrock_nova_context_preserve",
        "validator_passed": True,
        "llm_meta": {
            "model_id": chain_meta.get("model_id"),
            "raw_sha256": hashlib.sha256((state.get("extraction_raw_text") or "").encode("utf-8")).hexdigest(),
            "langchain": chain_meta,
            "rag_context": summarize_rag_context(state.get("rag_context") or {}),
            "validation_errors": validation_errors or [],
            "attempts": attempt,
            "retry_loop": "langgraph_schema_quote_repair",
            "fallback": {
                "type": "non_symptom_context_preserve",
                "reason": reason,
                "error": extracted_error,
            },
        },
    }
    update = {
        "extracted": extracted,
        "semantic_failed": False,
        "safety_only": False,
        "retry_extraction": False,
        "extraction_validation_errors": validation_errors or [],
        "repair_note": "",
    }
    update.update(
        trace_update(
            state,
            "schema_quote_validation",
            "preserved_context",
            {
                "reason": reason,
                "question_type": question_type,
                "fallback": "non_symptom_context_preserve",
                "validation_error_count": len(validation_errors or []),
                "attempt": attempt,
            },
        )
    )
    return update


def fallback_structured(question_type: str, question_id: str, transcript: str) -> dict[str, Any] | None:
    """검증 실패한 비증상 문항을 onepaper가 읽을 수 있는 최소 구조로 바꿉니다."""
    if question_type in {"patient_questions", "unresolved_questions"}:
        return {
            "standardized_text": transcript,
            "clinical_clues": [],
            "questions": [
                {
                    "category": "other",
                    "summary": transcript,
                    "original_quote": transcript,
                }
            ],
            "unresolved_items": [],
        }

    config = NON_SYMPTOM_FALLBACK_CONFIG.get(question_type)
    if not config:
        return None
    return {
        "standardized_text": transcript,
        "clinical_clues": [
            {
                "category": config["category"],
                "label": config["label"],
                "summary": transcript,
                "source_quote": transcript,
                "source_question": question_id,
                "priority": "일반",
                "related_symptoms": [],
            }
        ],
        "questions": [],
        "unresolved_items": [],
    }


def summarize_rag_context(rag_context: dict[str, Any]) -> dict[str, Any]:
    """LLM meta에 저장할 RAG 요약입니다. 긴 prompt 문단은 저장하지 않습니다."""
    return {
        "retriever": rag_context.get("retriever"),
        "source_files": rag_context.get("source_files") or [],
        "alias_hints": [
            {
                "matched_text": item.get("matched_text"),
                "canonical_hint": item.get("canonical_hint"),
            }
            for item in (rag_context.get("alias_hints") or [])[:5]
        ],
        "symptom_references": [
            {
                "symptom_id": item.get("symptom_id"),
                "display_name": item.get("display_name"),
                "bm25_score": item.get("bm25_score"),
            }
            for item in (rag_context.get("symptom_references") or [])[:5]
        ],
    }


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
                "accepted_matches": summarize_ir_matches(matched.get("matched_slots") or []),
            },
        )
    )
    return update


def summarize_ir_matches(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """감사용 trace에 남길 IR 확정 근거를 후보 목록 없이 요약합니다."""
    summary = []
    for slot in slots:
        trace = slot.get("ir_trace") if isinstance(slot.get("ir_trace"), dict) else {}
        summary.append({
            "slot_id": slot.get("slot_id"),
            "name": slot.get("name"),
            "source_quote": slot.get("source_quote"),
            "ir_method": slot.get("ir_method"),
            "accept_reason": trace.get("accept_reason"),
            "bm25_score": trace.get("bm25_score"),
            "vector_score": trace.get("vector_score"),
            "label_score": trace.get("label_score"),
            "rank_score": trace.get("rank_score"),
        })
    return summary[:8]


def session_validation_save_node(state: AnswerPipelineState) -> dict[str, Any]:
    """검증된 문항 결과를 S3 artifact에 저장하고 DynamoDB 상태를 갱신합니다."""
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
            "dialect_normalization": state.get("dialect_normalization") or {},
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
            "dialect_normalization": state.get("dialect_normalization") or {},
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
        "dialect_normalization": sanitize_dialect_normalization(
            state.get("dialect_normalization") or {}
        ),
        "spans": [sanitize_span(span) for span in extracted.get("spans", []) if isinstance(span, dict)],
        "structured": extracted.get("structured", {}),
        "matched_slots": [
            sanitize_matched_slot(slot)
            for slot in matched.get("matched_slots", [])
            if isinstance(slot, dict)
        ],
        "unmatched_spans": [
            sanitize_span(span)
            for span in matched.get("unmatched_spans", [])
            if isinstance(span, dict)
        ],
        "validator_passed": bool(validated.get("validator_passed")),
        "safety_flag": validated.get("safety_flag") or state.get("preliminary_safety_flag"),
        "errors": response_errors(state),
        "onepager_ready": validated.get("onepager_ready", False),
        "pipeline": {
            "graph": "munjin_langgraph_answer_pipeline",
            "status": "completed",
            "active_path": [entry["node"] for entry in final_trace if entry.get("node")],
        },
    }
    update = {"result_payload": payload}
    update["trace"] = final_trace
    update["active_path"] = [*state.get("active_path", []), "response_payload"]
    return update

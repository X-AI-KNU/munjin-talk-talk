"""운영 저장용 artifact 정리 정책.

Lambda 내부 파이프라인은 LLM 호출, schema 검증, IR 계산, LangGraph 실행 경로처럼
많은 중간값을 만듭니다. 하지만 운영 저장소에는 화면 표시와 사후 설명에 필요한
최소값만 남겨야 합니다. 이 모듈은 S3에 쓰기 직전 파일 종류별로 payload를 정리합니다.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from utils import clean_quote


ANSWER_FILE = "answers.redacted.json"
CONSENT_FILE = "consent.json"
DOCTOR_REVIEW_FILE = "doctor_review.redacted.json"
GUIDE_FILE = "patient_guide.redacted.json"
ONEPAPER_FILE = "onepaper.redacted.json"
TRACE_FILE = "llm_trace.redacted.json"


def prepare_artifact_payload(filename: str, payload: Any) -> Any:
    """파일 역할에 맞춰 운영 저장 payload를 최소화합니다."""
    if filename == ANSWER_FILE:
        return sanitize_answers(payload)
    if filename == ONEPAPER_FILE:
        return sanitize_onepaper(payload)
    if filename == GUIDE_FILE:
        return sanitize_patient_guide(payload)
    if filename == TRACE_FILE:
        return sanitize_explainability_trace(payload)
    if filename == CONSENT_FILE:
        return sanitize_consent(payload)
    if filename == DOCTOR_REVIEW_FILE:
        return sanitize_doctor_review(payload)
    return deepcopy(payload)


def sanitize_answers(payload: Any) -> dict[str, Any]:
    """문항별 답변 artifact에서 화면·원페이퍼 조립에 필요한 값만 남깁니다."""
    if not isinstance(payload, dict):
        return {}
    out: dict[str, Any] = {}
    for question_id, record in payload.items():
        if not isinstance(record, dict):
            continue
        item = {
            "text": clean_quote(record.get("text") or record.get("transcript") or ""),
            "dialect_normalization": sanitize_dialect_normalization(
                record.get("dialect_normalization") or {}
            ),
            "spans": [sanitize_span(span) for span in record.get("spans", []) if isinstance(span, dict)],
            "matched_slots": [
                sanitize_matched_slot(slot)
                for slot in record.get("matched_slots", [])
                if isinstance(slot, dict)
            ],
            "structured": sanitize_structured(record.get("structured") or {}),
            "extract_method": record.get("extract_method") or record.get("method") or "bedrock_nova",
            "confirmed": bool(record.get("confirmed", True)),
        }
        out[str(question_id)] = item
    return out


def sanitize_span(span: dict[str, Any]) -> dict[str, Any]:
    """LLM이 schema 검증을 통과한 의미 단위만 보관합니다."""
    return keep_keys(
        span,
        [
            "source_quote",
            "type",
            "slot_ref",
            "name",
            "normalized_text",
            "status",
            "alert",
            "explain",
        ],
    )


def sanitize_matched_slot(slot: dict[str, Any]) -> dict[str, Any]:
    """운영용 증상 매칭 결과에서 숫자 점수와 후보 목록을 제거합니다."""
    return keep_keys(
        slot,
        [
            "slot_id",
            "name",
            "source_quote",
            "span_type",
            "alert",
            "normalized_text",
            "status",
            "explain",
            "ir_method",
        ],
    )


def sanitize_structured(structured: Any) -> dict[str, Any]:
    """원페이퍼 구성에 쓰이는 structured extraction 값만 남깁니다."""
    if not isinstance(structured, dict):
        return {}
    return {
        "standardized_text": clean_quote(structured.get("standardized_text") or ""),
        "clinical_clues": [
            keep_keys(
                clue,
                [
                    "category",
                    "label",
                    "summary",
                    "source_quote",
                    "source_question",
                    "priority",
                    "related_symptoms",
                ],
            )
            for clue in structured.get("clinical_clues", [])
            if isinstance(clue, dict)
        ],
        "questions": [
            keep_keys(question, ["category", "summary", "original_quote"])
            for question in structured.get("questions", [])
            if isinstance(question, dict)
        ],
        "unresolved_items": deepcopy(structured.get("unresolved_items") or []),
    }



def sanitize_dialect_normalization(payload: Any) -> dict[str, Any]:
    """사투리 표준어 변환 결과에서 운영 저장에 필요한 값만 남깁니다."""
    if not isinstance(payload, dict):
        return {}

    return {
        "original_text": clean_quote(payload.get("original_text") or ""),
        "standardized_text": clean_quote(payload.get("standardized_text") or ""),
        "replacements": [
            keep_keys(
                item,
                [
                    "source_quote",
                    "standard_text",
                    "evidence_dialect",
                    "evidence_standard",
                    "match_type",
                ],
            )
            for item in payload.get("replacements", [])
            if isinstance(item, dict)
        ],
        "unmatched_phrases": [
            clean_quote(item)
            for item in payload.get("unmatched_phrases", [])
            if clean_quote(item)
        ],
        "validator_passed": bool(payload.get("validator_passed", True)),
    }


def sanitize_onepaper(payload: Any) -> dict[str, Any]:
    """의사용 원페이퍼 화면에 직접 필요한 값만 남깁니다."""
    if not isinstance(payload, dict):
        return {}
    out = keep_keys(
        payload,
        [
            "patient_summary",
            "agenda",
            "symptom_slots",
            "clinical_clues",
            "doctor_brief",
            "review_items",
            "transfer_text",
            "safety_flags",
            "unresolved_items",
        ],
    )
    out["symptom_slots"] = [
        sanitize_symptom_slot(slot)
        for slot in out.get("symptom_slots", [])
        if isinstance(slot, dict)
    ]
    return out


def sanitize_symptom_slot(slot: dict[str, Any]) -> dict[str, Any]:
    """원페이퍼 증상 카드에서 표시할 필드만 남깁니다."""
    return keep_keys(
        slot,
        [
            "slot_id",
            "name",
            "source_question",
            "source_quote",
            "normalized_text",
            "status",
            "alert",
            "explain",
            "ir_method",
        ],
    )


def sanitize_patient_guide(payload: Any) -> dict[str, Any]:
    """환자 안내문에는 실제 안내 문장만 남기고 LLM 메타데이터를 제거합니다."""
    if not isinstance(payload, dict):
        return {}
    return keep_keys(payload, ["generated_at", "items", "delivery_options", "generation_method", "guide_warning"])


def sanitize_doctor_review(payload: Any) -> dict[str, Any]:
    """의사 입력 artifact는 안내문 재조회에 필요한 원문을 보존합니다."""
    if not isinstance(payload, dict):
        return {}
    return keep_keys(payload, ["answers", "patient_instruction", "additional_notes", "reviewed_at"])


def sanitize_consent(payload: Any) -> dict[str, Any]:
    """동의 이력은 법적 확인에 필요한 체크 항목과 시각만 남깁니다."""
    if not isinstance(payload, dict):
        return {}
    return keep_keys(
        payload,
        [
            "accepted",
            "version",
            "method",
            "recorded_at",
            "accepted_at",
            "rejected_at",
            "privacy_items",
            "sensitive_items",
            "retention_notice",
        ],
    )


def sanitize_explainability_trace(payload: Any) -> dict[str, Any]:
    """LLM black-box 해소용 최소 trace만 저장합니다.

    프롬프트 전문, raw response, 전체 graph topology, top candidate 목록은 운영 저장에서
    제외합니다. 대신 어떤 노드가 실행됐는지, 어떤 모델/validator/IR gate가 쓰였는지만
    보존합니다.
    """
    if not isinstance(payload, dict):
        return {}
    out: dict[str, Any] = {}
    for question_id, record in payload.items():
        if not isinstance(record, dict):
            continue
        if "events" in record or "active_path" in record:
            out[str(question_id)] = {
                "graph": record.get("graph") or "munjin_langgraph_answer_pipeline",
                "version": record.get("version") or "v2",
                "question_type": record.get("question_type"),
                "active_path": [str(item) for item in (record.get("active_path") or [])],
                "events": compact_trace_events(record.get("events") or []),
                "matched_count": record.get("matched_count"),
                "span_count": record.get("span_count"),
            }
            continue
        orchestration = record.get("orchestration") if isinstance(record.get("orchestration"), dict) else {}
        trace = record.get("pipeline_trace") or record.get("trace") or orchestration.get("trace") or []
        out[str(question_id)] = {
            "graph": orchestration.get("graph") or "munjin_langgraph_answer_pipeline",
            "version": orchestration.get("version") or "v2",
            "question_type": orchestration.get("question_type") or record.get("question_type"),
            "active_path": compact_active_path(orchestration, trace),
            "events": compact_trace_events(trace),
            "matched_count": record.get("matched_count"),
            "span_count": record.get("span_count"),
        }
    return out


def compact_active_path(orchestration: dict[str, Any], trace: Any) -> list[str]:
    """실행 경로는 노드 이름 배열만 남깁니다."""
    path = orchestration.get("active_path")
    if isinstance(path, list) and path:
        return [str(item) for item in path]
    if isinstance(trace, list):
        return [str(item.get("node")) for item in trace if isinstance(item, dict) and item.get("node")]
    return []


def compact_trace_events(trace: Any) -> list[dict[str, Any]]:
    """각 trace event에서 감사에 필요한 핵심 세부값만 추립니다."""
    events: list[dict[str, Any]] = []
    if not isinstance(trace, list):
        return events
    for item in trace:
        if not isinstance(item, dict):
            continue
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        events.append({
            "node": item.get("node"),
            "status": item.get("status"),
            "at": item.get("at"),
            "details": compact_trace_details(details),
        })
    return events


def compact_trace_details(details: dict[str, Any]) -> dict[str, Any]:
    """node details에서 숫자·오류·모델 식별자 중심의 최소값만 남깁니다."""
    allowed = [
        "question_id",
        "question_type",
        "question_text_chars",
        "visit_type",
        "transcript_chars",
        "has_flag",
        "flag_type",
        "matched_pattern",
        "retriever",
        "alias_hint_count",
        "symptom_reference_count",
        "source_files",
        "attempt",
        "model_id",
        "langchain_chain",
        "prompt_adapter",
        "bedrock_runnable",
        "output_parser",
        "raw_sha256",
        "validator",
        "source_quote_grounding",
        "span_count",
        "structured_keys",
        "validation_error_count",
        "max_attempts",
        "next_node",
        "matched_count",
        "unmatched_count",
        "method",
        "accepted_matches",
        "validator_passed",
        "onepager_ready",
        "has_safety_flag",
        "refresh_source",
        "reason",
        "standardized_chars",
        "replacement_count",
        "hint_count",
    ]
    return {key: normalize_scalar(details.get(key)) for key in allowed if key in details}


def keep_keys(source: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """허용 목록에 있는 key만 깊은 복사해서 반환합니다."""
    return {key: deepcopy(source[key]) for key in keys if key in source}


def normalize_scalar(value: Any) -> Any:
    """JSON 직렬화와 사람이 읽는 trace에 적합한 값으로 정리합니다."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return deepcopy(value[:10])
    if isinstance(value, dict):
        return deepcopy({k: value[k] for k in list(value)[:10]})
    return str(value)

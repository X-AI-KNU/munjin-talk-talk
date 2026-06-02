"""파이프라인 trace와 orchestration 메타데이터 helper.

문진 결과가 왜 그렇게 나왔는지 사람이 추적할 수 있도록 각 노드의 상태를
누적합니다. 이 모듈은 노드의 비즈니스 로직을 모르고, trace 기록과 최종
DynamoDB 반영만 담당합니다.
"""

from datetime import datetime, timezone
from typing import Any

from pipeline_state import AnswerPipelineState, PIPELINE_GRAPH


def trace_update(
    state: AnswerPipelineState,
    node: str,
    status: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """LangGraph 노드가 반환할 trace/active_path update를 만듭니다."""
    return {
        "trace": next_trace_entry(state, node, status, details or {}),
        "active_path": [*state.get("active_path", []), node],
    }


def next_trace_entry(
    state: AnswerPipelineState,
    node: str,
    status: str,
    details: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """현재 trace 뒤에 새 노드 실행 기록을 하나 붙입니다."""
    trace = list(state.get("trace") or [])
    trace.append(
        {
            "node": node,
            "status": status,
            "at": datetime.now(timezone.utc).isoformat(),
            "details": details or {},
        }
    )
    return trace


def orchestration_snapshot(state: AnswerPipelineState, trace: list[dict[str, Any]]) -> dict[str, Any]:
    """응답과 DynamoDB에 저장할 LangGraph 실행 요약입니다."""
    return {
        "graph": PIPELINE_GRAPH["name"],
        "version": PIPELINE_GRAPH["version"],
        "nodes": PIPELINE_GRAPH["nodes"],
        "edges": PIPELINE_GRAPH["edges"],
        "active_path": [entry["node"] for entry in trace],
        "question_type": state.get("question_type"),
        "trace": trace,
    }


def response_errors(state: AnswerPipelineState) -> list[str]:
    """프론트에 넘길 파이프라인 오류 표시를 정리합니다."""
    if state.get("safety_only"):
        return ["semantic_extraction_failed_but_safety_saved"]
    validated = state.get("validated") or {}
    return validated.get("errors", [])


def persist_final_trace(state: AnswerPipelineState, final_trace: list[dict[str, Any]]) -> None:
    """DynamoDB 문항 기록에 최종 LangGraph trace를 best-effort로 반영합니다.

    `validate_and_save`는 저장 노드 내부에서 호출되므로, 그 시점에는 아직
    `onepaper_refresh`와 `response_payload` 노드가 실행되지 않았습니다. 최종 trace는
    환자 문진 결과 자체가 아니라 설명 가능성 메타데이터이므로, 저장 실패가 문진 처리
    성공 여부를 바꾸지 않도록 조용히 무시합니다.
    """
    try:
        # sessions는 저장 계층이므로 여기에서 지연 import해 순환 import를 피합니다.
        from sessions import get_session, update_session

        session_id = state.get("session_id")
        question_id = state.get("question_id")
        if not session_id or not question_id:
            return
        session = get_session(session_id)
        if not session:
            return

        orchestration = orchestration_snapshot(state, final_trace)
        responses = dict(session.get("responses") or {})
        question_results = dict(session.get("question_results") or {})
        for collection in (responses, question_results):
            record = dict(collection.get(question_id) or {})
            if record:
                record["orchestration"] = orchestration
                record["pipeline_trace"] = final_trace
                collection[question_id] = record
        update_session(session_id, {"responses": responses, "question_results": question_results})
    except Exception:
        return

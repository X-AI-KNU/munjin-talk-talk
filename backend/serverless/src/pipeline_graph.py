"""LangGraph answer-processing pipeline 조립부.

상태 정의는 `pipeline_state.py`, 실제 처리 노드는 `pipeline_nodes.py`,
trace helper는 `pipeline_trace.py`에 분리되어 있습니다. 이 파일은
"어떤 노드를 어떤 순서로 연결하는가"만 담당합니다.
"""

from typing import Any

from langgraph.graph import END, START, StateGraph
from langchain_core.runnables import RunnableLambda

from pipeline_nodes import (
    dialect_normalization_node,
    hybrid_ir_match_node,
    input_transcript_node,
    onepaper_refresh_node,
    quick_safety_flag_node,
    rag_context_retrieval_node,
    response_payload_node,
    safety_guardrail_save_node,
    schema_quote_validation_node,
    semantic_extraction_node,
    session_validation_save_node,
)
from pipeline_state import AnswerPipelineState, PIPELINE_GRAPH


def run_answer_pipeline(body: dict[str, Any]):
    """LangGraph를 실행하고 기존 handler 계약에 맞게 (payload, error)를 반환합니다."""
    final_state = _compiled_graph().invoke({"body": body or {}, "trace": [], "active_path": []})
    if final_state.get("error_response"):
        return None, final_state["error_response"]
    return final_state.get("result_payload") or {}, None


def route_after_required_input(state: AnswerPipelineState) -> str:
    """필수 입력이 없으면 즉시 종료하고, 정상 입력이면 안전 감지로 진행합니다."""
    return "stop" if state.get("error_response") else "continue"


def route_after_schema_validation(state: AnswerPipelineState) -> str:
    """LLM 검증 결과에 따라 IR 진행, 안전 저장, 오류 종료 중 하나를 선택합니다."""
    if state.get("retry_extraction"):
        return "retry"
    if state.get("error_response"):
        return "stop"
    if state.get("safety_only"):
        return "safety"
    return "continue"


def route_after_save(state: AnswerPipelineState) -> str:
    """저장 실패 시 종료하고, 성공하면 onepaper 갱신 trace로 진행합니다."""
    return "stop" if state.get("error_response") else "continue"


def _compiled_graph():
    """Lambda warm invocation에서 재사용할 수 있도록 graph를 한 번만 compile합니다."""
    if not hasattr(_compiled_graph, "_graph"):
        workflow = StateGraph(AnswerPipelineState)
        workflow.add_node("input_transcript", RunnableLambda(input_transcript_node))
        workflow.add_node("quick_safety_flag", RunnableLambda(quick_safety_flag_node))
        workflow.add_node("dialect_normalization", RunnableLambda(dialect_normalization_node))
        workflow.add_node("rag_context_retrieval", RunnableLambda(rag_context_retrieval_node))
        workflow.add_node("semantic_extraction", RunnableLambda(semantic_extraction_node))
        workflow.add_node("schema_quote_validation", RunnableLambda(schema_quote_validation_node))
        workflow.add_node("hybrid_ir_match", RunnableLambda(hybrid_ir_match_node))
        workflow.add_node("session_validation_save", RunnableLambda(session_validation_save_node))
        workflow.add_node("safety_guardrail_save", RunnableLambda(safety_guardrail_save_node))
        workflow.add_node("onepaper_refresh", RunnableLambda(onepaper_refresh_node))
        workflow.add_node("response_payload", RunnableLambda(response_payload_node))

        workflow.add_edge(START, "input_transcript")
        workflow.add_conditional_edges(
            "input_transcript",
            route_after_required_input,
            {"continue": "quick_safety_flag", "stop": END},
        )
        workflow.add_edge("quick_safety_flag", "dialect_normalization")
        workflow.add_edge("dialect_normalization", "rag_context_retrieval")
        workflow.add_edge("rag_context_retrieval", "semantic_extraction")
        workflow.add_edge("semantic_extraction", "schema_quote_validation")
        workflow.add_conditional_edges(
            "schema_quote_validation",
            route_after_schema_validation,
            {
                "retry": "semantic_extraction",
                "continue": "hybrid_ir_match",
                "safety": "safety_guardrail_save",
                "stop": END,
            },
        )
        workflow.add_edge("hybrid_ir_match", "session_validation_save")
        workflow.add_conditional_edges(
            "session_validation_save",
            route_after_save,
            {"continue": "onepaper_refresh", "stop": END},
        )
        workflow.add_conditional_edges(
            "safety_guardrail_save",
            route_after_save,
            {"continue": "onepaper_refresh", "stop": END},
        )
        workflow.add_edge("onepaper_refresh", "response_payload")
        workflow.add_edge("response_payload", END)
        _compiled_graph._graph = workflow.compile()
    return _compiled_graph._graph

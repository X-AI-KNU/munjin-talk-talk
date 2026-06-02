"""LangGraph 파이프라인의 공용 상태와 그래프 메타데이터.

이 파일에는 노드 구현을 넣지 않습니다. 개발자가 파이프라인의 전체
형태를 먼저 볼 수 있도록, 상태 타입과 그래프 설명만 한곳에 모았습니다.
"""

from typing import Any, TypedDict


# 증상 매칭 IR을 실제로 실행해야 하는 문항 유형입니다.
# 복약/환자 질문처럼 증상 후보가 아닌 문항은 IR을 건너뜁니다.
SYMPTOM_QUESTION_TYPES = {"chief_complaint", "progress", "new_symptoms"}


class AnswerPipelineState(TypedDict, total=False):
    """LangGraph 노드 사이를 이동하는 상태 객체입니다.

    각 노드는 이 dict에 필요한 값을 추가하고, 다음 노드는 앞 노드가
    남긴 값을 읽습니다. DynamoDB에 저장되는 trace도 이 상태에서 누적됩니다.
    """

    body: dict[str, Any]
    session_id: str
    question_id: str
    question_type: str
    visit_type: str
    transcript: str
    preliminary_safety_flag: dict[str, Any] | None
    extracted: dict[str, Any]
    matched: dict[str, Any]
    validated: dict[str, Any]
    semantic_failed: bool
    safety_only: bool
    error_response: dict[str, Any]
    result_payload: dict[str, Any]
    active_path: list[str]
    trace: list[dict[str, Any]]


# 프론트/문서/API 응답에 노출되는 파이프라인 설명입니다.
# 실제 실행 그래프와 이름이 어긋나지 않도록 pipeline_graph.py의 노드 등록과
# 같은 순서를 유지합니다.
PIPELINE_GRAPH = {
    "name": "munjin_langgraph_answer_pipeline",
    "version": "v1",
    "nodes": [
        "input_transcript",
        "quick_safety_flag",
        "semantic_extraction",
        "schema_quote_validation",
        "hybrid_ir_match",
        "session_validation_save",
        "safety_guardrail_save",
        "onepaper_refresh",
        "response_payload",
    ],
    "edges": [
        ["__start__", "input_transcript"],
        ["input_transcript", "quick_safety_flag"],
        ["quick_safety_flag", "semantic_extraction"],
        ["semantic_extraction", "schema_quote_validation"],
        ["schema_quote_validation", "hybrid_ir_match"],
        ["schema_quote_validation", "safety_guardrail_save"],
        ["hybrid_ir_match", "session_validation_save"],
        ["session_validation_save", "onepaper_refresh"],
        ["safety_guardrail_save", "onepaper_refresh"],
        ["onepaper_refresh", "response_payload"],
        ["response_payload", "__end__"],
    ],
    "retry_policy": {
        "semantic_extraction": "EXTRACTION_RETRY_ATTEMPTS",
        "onepaper_final_review": "REVIEW_RETRY_ATTEMPTS",
    },
}

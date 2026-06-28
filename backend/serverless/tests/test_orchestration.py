"""orchestration.py의 핵심 함수들 단위 테스트."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _install_stubs():
    """orchestration 모듈의 외부 의존을 가짜로 교체합니다."""
    for name in [
        "settings",
        "sessions",
        "artifact_store",
        "pipeline_graph",
        "orchestration",
        "boto3",
    ]:
        sys.modules.pop(name, None)

    # boto3 stub
    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *args, **kwargs: types.SimpleNamespace(invoke=lambda **kw: {})
    boto3.resource = lambda *args, **kwargs: None
    sys.modules["boto3"] = boto3

    settings = types.ModuleType("settings")
    sys.modules["settings"] = settings

    sessions = types.ModuleType("sessions")
    sessions._store = {}
    sessions.get_session = lambda sid: sessions._store.get(sid)
    sessions.update_session = lambda sid, updates: sessions._store.get(sid, {}).update(updates)
    # 최신 main에서 추가된 의사 대기열 위치 함수도 stub으로 제공합니다.
    sessions.doctor_queue_position = lambda sid: 1
    sys.modules["sessions"] = sessions

    artifact_store = types.ModuleType("artifact_store")
    artifact_store._answers = {}
    artifact_store.load_answers = lambda session: artifact_store._answers.get(session.get("session_id"), {})
    artifact_store.save_answers = lambda session, answers: artifact_store._answers.update({session.get("session_id"): answers})
    sys.modules["artifact_store"] = artifact_store

    pipeline_graph = types.ModuleType("pipeline_graph")
    pipeline_graph.PIPELINE_GRAPH = {"name": "test_graph"}
    pipeline_graph.run_answer_pipeline = lambda body: ({"validator_passed": True, "onepager_ready": True}, None)
    sys.modules["pipeline_graph"] = pipeline_graph

    return importlib.import_module("orchestration")


def test_normalize_batch_answer_fills_defaults():
    orchestration = _install_stubs()
    answer = {
        "questionId": "Q1",
        "questionType": "chief_complaint",
        "transcript": "기침이 나요",
    }
    result = orchestration.normalize_batch_answer(answer, "sess1", "initial", "default")
    assert result["session_id"] == "sess1"
    assert result["question_id"] == "Q1"
    assert result["question_type"] == "chief_complaint"
    assert result["visit_type"] == "initial"
    assert result["transcript"] == "기침이 나요"


def test_process_answers_rejects_empty_answers():
    orchestration = _install_stubs()
    import sessions
    sessions._store["sess1"] = {"session_id": "sess1", "visit_type": "initial"}

    payload, err = orchestration.process_answers({
        "session_id": "sess1",
        "answers": [],
    })
    assert err is not None
    assert err["statusCode"] == 400


def test_process_answers_rejects_missing_session():
    orchestration = _install_stubs()
    payload, err = orchestration.process_answers({
        "session_id": "nonexistent",
        "answers": [{"question_id": "Q1", "transcript": "기침"}],
    })
    assert err is not None
    assert err["statusCode"] == 404


def test_unwrap_error_response():
    orchestration = _install_stubs()
    import json

    err = {"statusCode": 400, "body": json.dumps({"error": "test_error"})}
    status, body = orchestration.unwrap_error_response(err)
    assert status == 400
    assert body["error"] == "test_error"


def test_unwrap_error_response_invalid_body():
    orchestration = _install_stubs()
    err = {"statusCode": 500, "body": "not json"}
    status, body = orchestration.unwrap_error_response(err)
    assert status == 500
    assert body["error"] == "pipeline_error"

"""질문 세트 로더와 공개 API 계약 테스트."""

from __future__ import annotations

import importlib
import json
import sys
import types
from types import SimpleNamespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_default_question_set_loads_and_missing_set_returns_none():
    from question_sets import get_question_set  # noqa: E402

    question_set = get_question_set("default")

    assert question_set is not None
    assert question_set["id"] == "default"
    assert question_set["visits"]["initial"][0]["id"] == "Q1"
    assert get_question_set("missing-set") is None


def test_question_set_rejects_invalid_question_type():
    from question_sets import validate_question_set  # noqa: E402

    broken = {
        "id": "broken",
        "visits": {
            "initial": [{"id": "Q1", "title": "질문", "question_type": "bad_type"}],
            "followup": [{"id": "Q1", "title": "질문", "question_type": "progress"}],
        },
    }

    with pytest.raises(RuntimeError, match="Invalid question_type"):
        validate_question_set(broken)


def install_handler_stubs():
    """handler.py를 API route만 테스트할 수 있게 주변 AWS 모듈을 가짜로 바꿉니다."""
    for name in ["handler", "audio", "guide", "onepager", "orchestration", "security", "settings", "sessions"]:
        sys.modules.pop(name, None)

    settings = types.ModuleType("settings")
    settings.AUTH_SIGNING_SECRET = "unit-test-signing-secret"
    settings.AUTH_TOKEN_TTL_MINUTES = 240
    settings.STAFF_ACCESS_CODE = "staff-test"
    settings.DOCTOR_ACCESS_CODE = "doctor-test"
    settings.STAFF_ACCESS_CODE_SHA256 = ""
    settings.DOCTOR_ACCESS_CODE_SHA256 = ""
    sys.modules["settings"] = settings

    audio = types.ModuleType("audio")
    audio.generate_streaming_transcribe_url = lambda _body: ({}, None)
    sys.modules["audio"] = audio

    guide = types.ModuleType("guide")
    guide.get_guide = lambda _session_id: None
    guide.save_doctor_response = lambda _body: ({}, None)
    sys.modules["guide"] = guide

    onepager = types.ModuleType("onepager")
    onepager.get_onepager_payload = lambda _session: {}
    onepager.rerun_onepager_review = lambda _session_id: ({}, None)
    sys.modules["onepager"] = onepager

    orchestration = types.ModuleType("orchestration")
    orchestration.handle_internal_event = lambda _event, _context: {}
    orchestration.process_answer = lambda _body: ({}, None)
    orchestration.process_answers = lambda _body: ({}, None)
    orchestration.retry_answer_analysis = lambda _session_id: ({}, None)
    sys.modules["orchestration"] = orchestration

    sessions = types.ModuleType("sessions")
    sessions.create_session = lambda _body: {}
    sessions.get_session = lambda _session_id: None
    sessions.list_sessions = lambda: []
    sessions.public_session = lambda session, include_artifacts=False: session
    sessions.save_patient_consent = lambda _session_id, _body: None
    sessions.update_session = lambda _session_id, _updates: None
    sys.modules["sessions"] = sessions

    return importlib.import_module("handler")


def test_question_set_api_route_returns_public_payload_and_404():
    handler = install_handler_stubs()

    ok = handler.route("GET", "/question-sets/default", {})
    missing = handler.route("GET", "/question-sets/not-found", {})

    ok_body = json.loads(ok["body"])
    missing_body = json.loads(missing["body"])
    assert ok["statusCode"] == 200
    assert ok_body["id"] == "default"
    assert "initial" in ok_body["visits"]
    assert missing["statusCode"] == 404
    assert missing_body["error"] == "question_set_not_found"


def test_handler_logs_traceback_without_leaking_exception_to_response(capsys):
    handler = install_handler_stubs()

    def boom(_method, _path, _event):
        raise RuntimeError("sensitive backend detail")

    handler.route = boom
    result = handler.handler(
        {"requestContext": {"http": {"method": "GET"}}, "rawPath": "/boom"},
        SimpleNamespace(aws_request_id="req-1"),
    )
    body = json.loads(result["body"])
    log = json.loads(capsys.readouterr().out)

    assert result["statusCode"] == 500
    assert body["error"] == "internal_error"
    assert "sensitive backend detail" not in result["body"]
    assert log["exception_type"] == "RuntimeError"
    assert "traceback" in log
    assert "sensitive backend detail" in log["traceback"]

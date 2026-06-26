"""Doctor response completion behavior tests."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def import_guide_with_stubs():
    captured = {"saved": {}, "updates": {}}
    for name in ["guide", "artifact_store", "llm", "sessions", "settings"]:
        sys.modules.pop(name, None)

    artifact_store = types.ModuleType("artifact_store")
    artifact_store.DOCTOR_REVIEW_FILE = "doctor_review.redacted.json"
    artifact_store.GUIDE_FILE = "patient_guide.redacted.json"
    artifact_store.ONEPAPER_FILE = "onepaper.redacted.json"
    artifact_store.get_json = lambda _session, _file, default=None: default

    def put_json(_session, file_name, payload):
        captured["saved"][file_name] = payload
        return file_name

    artifact_store.put_json = put_json
    sys.modules["artifact_store"] = artifact_store

    llm = types.ModuleType("llm")
    llm.call_bedrock_json_with_meta = lambda *_args, **_kwargs: ({}, "", {})
    sys.modules["llm"] = llm

    sessions = types.ModuleType("sessions")
    sessions.get_session = lambda session_id: {"session_id": session_id, "patient": {"name": "홍길동"}}

    def update_session(_session_id, updates):
        captured["updates"].update(updates)
        return updates

    sessions.update_session = update_session
    sys.modules["sessions"] = sessions

    settings = types.ModuleType("settings")
    settings.GUIDE_MAX_TOKENS = 900
    settings.GUIDE_MODEL_ID = "guide-test-model"
    sys.modules["settings"] = settings

    return importlib.import_module("guide"), captured


def test_empty_doctor_response_marks_reviewed_without_guide():
    guide, captured = import_guide_with_stubs()

    payload, err = guide.save_doctor_response({
        "session_id": "s_no_question",
        "answers": [],
        "patient_instruction": "",
    })

    assert err is None
    assert payload["doctor_review_saved"] is True
    assert payload["patient_guide_generated"] is False
    assert payload["no_patient_guide_needed"] is True
    assert payload["guide_generation_valid"] is True
    assert captured["updates"]["status"] == "reviewed"
    assert captured["updates"]["guide_ready"] is False
    assert captured["saved"][guide.GUIDE_FILE]["generation_method"] == "no_patient_question_answers"


def test_instruction_only_response_is_reviewed_and_guide_ready():
    guide, captured = import_guide_with_stubs()

    payload, err = guide.save_doctor_response({
        "session_id": "s_instruction_only",
        "answers": [],
        "patient_instruction": "약은 중단하지 말고 복용해 주세요.",
    })

    assert err is None
    assert payload["patient_guide_generated"] is False
    assert payload["no_patient_guide_needed"] is False
    assert captured["updates"]["status"] == "reviewed"
    assert captured["updates"]["guide_ready"] is True
    assert captured["saved"][guide.DOCTOR_REVIEW_FILE]["patient_instruction"] == "약은 중단하지 말고 복용해 주세요"


def test_patient_guide_allows_meaning_preserving_polite_answer():
    guide, _captured = import_guide_with_stubs()
    captured_prompt = {}

    def fake_call(prompt, *_args, **_kwargs):
        captured_prompt["text"] = prompt
        return ({
            "items": [{
                "question": "혈압약을 계속 먹어도 되는지 문의",
                "answer_simple": ["혈압약은 계속 복용해도 됩니다."],
                "tts_emphasis_words": ["혈압약"],
            }],
            "delivery_options": ["screen", "tts", "print"],
        }, "raw-guide", {})

    guide.call_bedrock_json_with_meta = fake_call

    result = guide.generate_patient_guide(
        {"session_id": "s_guide", "patient": {"name": "홍길동"}},
        {},
        [{
            "question_summary": "혈압약을 계속 먹어도 되는지 문의",
            "answer_text": "혈압약은 계속 복용해도 됩니다.",
        }],
        "",
    )

    assert result["generation_method"] == "bedrock_nova_lite_grounded"
    assert result["items"][0]["answer_simple"] == ["혈압약은 계속 복용해도 됩니다"]
    assert "Do NOT simplify" in captured_prompt["text"]
    assert "style conversion, not medical simplification" in captured_prompt["text"]

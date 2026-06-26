"""Local dummy patient-flow QA tests.

These tests use in-memory DynamoDB/S3 doubles so the high-level queue and
safety-flag flow can be checked without touching AWS resources.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


ANSWER_FILE = "answers.redacted.json"
CONSENT_FILE = "consent.redacted.json"
DOCTOR_REVIEW_FILE = "doctor_review.redacted.json"
GUIDE_FILE = "patient_guide.redacted.json"
ONEPAPER_FILE = "onepaper.redacted.json"
TRACE_FILE = "trace.redacted.json"


class FakeTable:
    def __init__(self):
        self.items = {}

    def get_item(self, Key):
        item = self.items.get(Key["session_id"])
        return {"Item": item} if item else {}

    def put_item(self, Item, ConditionExpression=None):
        key = Item["session_id"]
        if ConditionExpression and key in self.items:
            raise RuntimeError("conditional check failed")
        self.items[key] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, **kwargs):
        key = Key["session_id"]
        item = self.items.setdefault(key, {"session_id": key})
        if UpdateExpression.startswith("ADD queue_counter"):
            item["queue_counter"] = int(item.get("queue_counter") or 0) + int(ExpressionAttributeValues[":one"])
            return {"Attributes": {"queue_counter": item["queue_counter"]}}
        if UpdateExpression.startswith("SET "):
            names = kwargs.get("ExpressionAttributeNames") or {}
            for assignment in UpdateExpression.removeprefix("SET ").split(", "):
                name_key, value_key = [part.strip() for part in assignment.split(" = ", 1)]
                item[names.get(name_key, name_key)] = ExpressionAttributeValues[value_key]
            return {"Attributes": dict(item)}
        raise AssertionError(f"Unexpected update expression: {UpdateExpression}")

    def scan(self, **_kwargs):
        return {"Items": list(self.items.values())}

    def delete_item(self, Key):
        self.items.pop(Key["session_id"], None)


def install_dummy_flow_stubs():
    modules = [
        "settings",
        "artifact_store",
        "privacy",
        "sessions",
        "onepager",
        "onepager_review",
        "llm",
        "pipeline_graph",
        "guide",
        "orchestration",
    ]
    for name in modules:
        sys.modules.pop(name, None)

    fake = FakeTable()
    artifacts = {}

    settings = types.ModuleType("settings")
    settings.table = fake
    settings.REVIEWER_MODEL_ID = "review-test-model"
    settings.REVIEW_MAX_TOKENS = 900
    settings.REVIEW_RETRY_ATTEMPTS = 1
    settings.GUIDE_MODEL_ID = "guide-test-model"
    settings.GUIDE_MAX_TOKENS = 900
    sys.modules["settings"] = settings

    llm = types.ModuleType("llm")
    llm.call_bedrock_json_with_meta = lambda *_args, **_kwargs: ({}, "", {"stubbed": True})
    sys.modules["llm"] = llm

    pipeline_graph = types.ModuleType("pipeline_graph")
    pipeline_graph.PIPELINE_GRAPH = {"name": "dummy_patient_flow_graph"}
    pipeline_graph.run_answer_pipeline = lambda _item: ({"validator_passed": True, "onepager_ready": True}, None)
    sys.modules["pipeline_graph"] = pipeline_graph

    artifact_store = types.ModuleType("artifact_store")
    artifact_store.ANSWER_FILE = ANSWER_FILE
    artifact_store.CONSENT_FILE = CONSENT_FILE
    artifact_store.DOCTOR_REVIEW_FILE = DOCTOR_REVIEW_FILE
    artifact_store.GUIDE_FILE = GUIDE_FILE
    artifact_store.ONEPAPER_FILE = ONEPAPER_FILE
    artifact_store.TRACE_FILE = TRACE_FILE
    artifact_store.artifact_meta = lambda session_id, created_at=None: {
        "bucket": "dummy-artifacts",
        "prefix": f"sessions/dummy/{session_id}/",
        "answers_key": f"sessions/dummy/{session_id}/{ANSWER_FILE}",
        "onepaper_key": f"sessions/dummy/{session_id}/{ONEPAPER_FILE}",
        "guide_key": f"sessions/dummy/{session_id}/{GUIDE_FILE}",
        "consent_key": f"sessions/dummy/{session_id}/{CONSENT_FILE}",
        "trace_key": f"sessions/dummy/{session_id}/{TRACE_FILE}",
    }

    def key(session, filename):
        return (session["session_id"], filename)

    def put_json(session, filename, payload):
        artifacts[key(session, filename)] = payload
        return filename

    def get_json(session, filename, default=None):
        return artifacts.get(key(session, filename), default)

    def load_answers(session):
        return artifacts.get(key(session, ANSWER_FILE), {})

    artifact_store.put_json = put_json
    artifact_store.get_json = get_json
    artifact_store.load_answers = load_answers
    artifact_store.save_answers = lambda session, answers: put_json(session, ANSWER_FILE, answers)
    artifact_store.save_trace = lambda session, question_id, trace: artifacts.setdefault(
        key(session, TRACE_FILE),
        {},
    ).update({question_id: trace})
    artifact_store.delete_session_artifacts = lambda session: artifacts.pop((session["session_id"], ANSWER_FILE), None)
    sys.modules["artifact_store"] = artifact_store

    privacy = types.ModuleType("privacy")
    privacy.consent_summary = lambda consent: {"accepted": bool(consent.get("accepted"))}
    privacy.safety_summary = lambda flag: None if not flag else {
        "category": flag.get("category"),
        "matched_pattern": flag.get("matched_pattern"),
    }
    privacy.sanitize_reception_patient = lambda patient: {
        "name": "더*환",
        "name_mask_version": "v2",
        "age": patient.get("age") or 72,
        "age_band": "70대",
        "gender": patient.get("gender") or "여성",
        "receipt_id": patient.get("receipt_id") or "QA-0001",
        "department": patient.get("department") or "이비인후과",
        "doctor": patient.get("doctor") or "테스트",
        "honorific": "환자님",
    }
    sys.modules["privacy"] = privacy

    sessions = importlib.import_module("sessions")
    onepager = importlib.import_module("onepager")
    onepager.apply_bedrock_onepager_review = lambda _session, payload: {
        **payload,
        "review_items": payload.get("review_items") or ["더미 QA 검토 항목"],
        "llm_review": {"stubbed": True},
    }
    guide = importlib.import_module("guide")
    orchestration = importlib.import_module("orchestration")
    orchestration.enqueue_answer_analysis = lambda _payload: (True, "")
    return fake, artifacts, sessions, onepager, guide, orchestration


def create_dummy_session(sessions, *, visit_type="initial", receipt_id="QA-0001"):
    return sessions.create_session({
        "visit_type": visit_type,
        "question_set_id": "default",
        "patient": {
            "age": 72,
            "gender": "여성",
            "receipt_id": receipt_id,
            "department": "이비인후과",
            "doctor": "테스트",
        },
    })


def test_patient_completion_is_queued_without_waiting_for_analysis():
    fake, artifacts, sessions, _onepager, _guide, orchestration = install_dummy_flow_stubs()
    session = create_dummy_session(sessions, receipt_id="QA-1001")

    payload, err = orchestration.process_answers({
        "session_id": session["session_id"],
        "visit_type": "initial",
        "question_set_id": "default",
        "answers": [
            {
                "question_id": "Q1",
                "question_type": "chief_complaint",
                "question_text": "어디가 불편하셔서 오셨어요?",
                "transcript": "어제부터 기침이 나요",
            },
            {
                "question_id": "Q4",
                "question_type": "patient_question",
                "question_text": "의사선생님께 묻고 싶은 점이 있으세요?",
                "transcript": "따로 없어요",
            },
        ],
    })

    updated = fake.items[session["session_id"]]

    assert err is None
    assert payload["patient_complete"] is True
    assert payload["analysis_status"] == "pending"
    assert updated["status"] == "analysis_pending"
    assert updated["question_status"]["Q1"]["analysis_status"] == "pending"
    assert artifacts[(session["session_id"], ANSWER_FILE)]["Q1"]["raw_text"] == "어제부터 기침이 나요"


def test_safety_dummy_answer_moves_session_to_priority_queue():
    fake, artifacts, sessions, onepager, _guide, _orchestration = install_dummy_flow_stubs()
    session = create_dummy_session(sessions, receipt_id="QA-2001")

    payload, err = onepager.validate_and_save({
        "session_id": session["session_id"],
        "visit_type": "initial",
        "question_id": "Q1",
        "question_type": "chief_complaint",
        "question_text": "어디가 불편하셔서 오셨어요?",
        "transcript": "가심이 답답허고 코물이 줄줄 나와요",
        "structured": {"standardized_text": "가슴이 답답하고 콧물이 줄줄 나옵니다."},
        "spans": [],
        "matched_slots": [],
    })

    updated = fake.items[session["session_id"]]
    answer = artifacts[(session["session_id"], ANSWER_FILE)]["Q1"]
    saved_onepager = artifacts[(session["session_id"], ONEPAPER_FILE)]

    assert err is None
    assert payload["safety_flag"]["category"] == "chest_discomfort"
    assert updated["risk"] == "high"
    assert updated["status"] == "needs_priority"
    assert answer["text"] == "가심이 답답허고 코물이 줄줄 나와요"
    assert any(slot["slot_id"] == "chest_discomfort" for slot in answer["matched_slots"])
    assert saved_onepager["safety_flags"][0]["category"] == "chest_discomfort"


def test_normal_dummy_flow_reaches_doctor_queue_and_reviewed_archive():
    fake, artifacts, sessions, onepager, guide, _orchestration = install_dummy_flow_stubs()
    session = create_dummy_session(sessions, receipt_id="QA-3001")

    payload_q1, err_q1 = onepager.validate_and_save({
        "session_id": session["session_id"],
        "visit_type": "initial",
        "question_id": "Q1",
        "question_type": "chief_complaint",
        "question_text": "어디가 불편하셔서 오셨어요?",
        "transcript": "기침이 나고 콧물이 나요",
        "structured": {"standardized_text": "기침과 콧물이 있습니다."},
        "spans": [],
        "matched_slots": [{"slot_id": "cough", "name": "기침", "normalized_text": "기침"}],
    })
    payload_q4, err_q4 = onepager.validate_and_save({
        "session_id": session["session_id"],
        "visit_type": "initial",
        "question_id": "Q4",
        "question_type": "patient_question",
        "question_text": "의사선생님께 묻고 싶은 점이 있으세요?",
        "transcript": "따로 없어요",
        "structured": {"standardized_text": "따로 질문이 없습니다.", "questions": []},
        "spans": [],
        "matched_slots": [],
    })

    assert err_q1 is None
    assert err_q4 is None
    assert payload_q1["validator_passed"] is True
    assert payload_q4["validator_passed"] is True
    assert fake.items[session["session_id"]]["status"] == "waiting_doctor"

    result, err = guide.save_doctor_response({
        "session_id": session["session_id"],
        "answers": [],
        "patient_instruction": "",
    })

    assert err is None
    assert result["no_patient_guide_needed"] is True
    assert fake.items[session["session_id"]]["status"] == "reviewed"
    assert artifacts[(session["session_id"], DOCTOR_REVIEW_FILE)]["answers"] == []
    assert artifacts[(session["session_id"], GUIDE_FILE)]["generation_method"] == "no_patient_question_answers"

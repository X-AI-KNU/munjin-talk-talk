"""DynamoDB 대기번호 원자 counter 테스트."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class FakeTable:
    """sessions.py가 사용하는 DynamoDB Table 메서드만 구현한 테스트 더블."""

    def __init__(self):
        self.items = {
            "s_old": {
                "session_id": "s_old",
                "queue_number": 7,
                "created_at": "2026-06-01T00:00:00",
                "updated_at": "2026-06-01T00:00:00",
                "patient": {"name": "김*자", "receipt_id": "R-0001"},
            }
        }

    def get_item(self, Key):
        item = self.items.get(Key["session_id"])
        return {"Item": item} if item else {}

    def put_item(self, Item, ConditionExpression=None):
        key = Item["session_id"]
        if ConditionExpression and key in self.items:
            raise RuntimeError("conditional check failed")
        self.items[key] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, **_kwargs):
        key = Key["session_id"]
        item = self.items.setdefault(key, {"session_id": key, "queue_counter": 0})
        if UpdateExpression.startswith("ADD queue_counter"):
            item["queue_counter"] = int(item.get("queue_counter") or 0) + int(ExpressionAttributeValues[":one"])
            return {"Attributes": {"queue_counter": item["queue_counter"]}}
        raise AssertionError(f"Unexpected update expression: {UpdateExpression}")

    def scan(self, **_kwargs):
        return {"Items": list(self.items.values())}


def import_sessions_with_fake_table(fake_table: FakeTable):
    """sessions 모듈이 AWS 클라이언트를 만들지 않도록 의존 모듈을 가짜로 주입합니다."""
    for name in ["settings", "artifact_store", "privacy", "sessions"]:
        sys.modules.pop(name, None)

    settings = types.ModuleType("settings")
    settings.table = fake_table
    sys.modules["settings"] = settings

    artifact_store = types.ModuleType("artifact_store")
    artifact_store.CONSENT_FILE = "consent.json"
    artifact_store.artifact_meta = lambda session_id, created_at: {"session_id": session_id, "created_at": created_at}
    artifact_store.load_answers = lambda _session: {}
    artifact_store.put_json = lambda *_args, **_kwargs: None
    sys.modules["artifact_store"] = artifact_store

    privacy = types.ModuleType("privacy")
    privacy.consent_summary = lambda consent: {"accepted": bool(consent.get("accepted"))}
    privacy.sanitize_reception_patient = lambda patient: dict(patient or {})
    sys.modules["privacy"] = privacy

    return importlib.import_module("sessions")


def test_queue_counter_is_atomic_and_meta_session_is_hidden():
    fake = FakeTable()
    sessions = import_sessions_with_fake_table(fake)

    assert sessions.next_queue_number() == 8
    assert sessions.next_queue_number() == 9
    assert fake.items[sessions.QUEUE_COUNTER_SESSION_ID]["queue_counter"] == 9

    visible = sessions.list_sessions()

    assert visible
    assert all(not item["sessionId"].startswith("__meta") for item in visible)

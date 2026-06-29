"""artifact_store.py S3 저장/조회 테스트 (S3 클라이언트 stub)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class FakeS3:
    """artifact_store가 쓰는 S3 메서드만 구현한 인메모리 더블."""

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[(Bucket, Key)] = Body
        self.last_put_kwargs = kwargs
        return {}

    def get_object(self, Bucket, Key):
        from botocore.exceptions import ClientError
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        body = self.objects[(Bucket, Key)]

        class _Body:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

        return {"Body": _Body(body)}

    def list_objects_v2(self, Bucket, Prefix, **kwargs):
        keys = [k for (b, k) in self.objects if b == Bucket and k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def delete_objects(self, Bucket, Delete):
        for obj in Delete["Objects"]:
            self.objects.pop((Bucket, obj["Key"]), None)
        return {}


@pytest.fixture()
def store(monkeypatch):
    import artifact_store
    fake = FakeS3()
    monkeypatch.setattr(artifact_store, "s3", fake)
    monkeypatch.setattr(artifact_store, "ARTIFACTS_BUCKET", "test-bucket")
    monkeypatch.setattr(artifact_store, "S3_KMS_KEY_ID", "")
    monkeypatch.setattr(artifact_store, "S3_SERVER_SIDE_ENCRYPTION", "AES256")
    return artifact_store, fake


def _session():
    return {"session_id": "s_1", "created_at": "2026-06-25T00:00:00+00:00",
            "artifact": {"prefix": "sessions/2026-06-25/s_1/"}}


def test_require_bucket_raises_when_missing(monkeypatch):
    import artifact_store
    monkeypatch.setattr(artifact_store, "ARTIFACTS_BUCKET", "")
    with pytest.raises(RuntimeError, match="ARTIFACTS_BUCKET"):
        artifact_store.require_bucket()


def test_date_part_parses_iso():
    import artifact_store
    assert artifact_store.date_part("2026-06-25T12:00:00+00:00") == "2026-06-25"


def test_date_part_invalid_falls_back_to_today():
    import artifact_store
    out = artifact_store.date_part("not-a-date")
    assert len(out) == 10 and out.count("-") == 2


def test_session_prefix_and_meta():
    import artifact_store
    prefix = artifact_store.session_prefix("s_1", "2026-06-25T00:00:00+00:00")
    assert prefix == "sessions/2026-06-25/s_1/"
    meta = artifact_store.artifact_meta("s_1", "2026-06-25T00:00:00+00:00")
    assert meta["answers_key"].endswith("answers.redacted.json")
    assert meta["onepaper_key"].endswith("onepaper.redacted.json")


def test_put_and_get_json_roundtrip(store):
    artifact_store, fake = store
    session = _session()
    key = artifact_store.put_json(session, "onepaper.redacted.json", {"patient_summary": {"display_name": "홍*동"}})
    assert key.endswith("onepaper.redacted.json")
    # 저장된 본문은 stored_at/schema_version/payload 래핑 구조
    raw = json.loads(fake.objects[("test-bucket", key)].decode("utf-8"))
    assert raw["schema_version"] == "munjin-artifact-v1"
    assert "payload" in raw
    # 조회 시 payload만 반환
    got = artifact_store.get_json(session, "onepaper.redacted.json")
    assert got["patient_summary"]["display_name"] == "홍*동"


def test_get_json_missing_returns_default(store):
    artifact_store, _ = store
    got = artifact_store.get_json(_session(), "guide.redacted.json", default={"x": 1})
    assert got == {"x": 1}


def test_put_json_applies_sse(store):
    artifact_store, fake = store
    artifact_store.put_json(_session(), "consent.json", {"accepted": True})
    assert fake.last_put_kwargs.get("ServerSideEncryption") == "AES256"


def test_put_json_redacts_pii(store):
    artifact_store, fake = store
    key = artifact_store.put_json(_session(), "answers.redacted.json", {
        "Q1": {"text": "제 번호는 010-1234-5678이에요", "spans": [], "matched_slots": [], "structured": {}}
    })
    raw = fake.objects[("test-bucket", key)].decode("utf-8")
    assert "010-1234-5678" not in raw
    assert "[연락처]" in raw


def test_save_and_load_answers(store):
    artifact_store, _ = store
    session = _session()
    artifact_store.save_answers(session, {
        "Q1": {"text": "기침이 나요", "spans": [], "matched_slots": [], "structured": {}}
    })
    loaded = artifact_store.load_answers(session)
    assert "Q1" in loaded
    assert loaded["Q1"]["text"] == "기침이 나요"


def test_save_trace_accumulates(store):
    artifact_store, _ = store
    session = _session()
    artifact_store.save_trace(session, "Q1", {"orchestration": {}, "pipeline_trace": []})
    artifact_store.save_trace(session, "Q2", {"orchestration": {}, "pipeline_trace": []})
    traces = artifact_store.get_json(session, "llm_trace.redacted.json", default={})
    assert set(traces.keys()) == {"Q1", "Q2"}


def test_delete_session_artifacts(store):
    artifact_store, fake = store
    session = _session()
    artifact_store.put_json(session, "answers.redacted.json", {})
    artifact_store.put_json(session, "consent.json", {"accepted": True})
    assert len(fake.objects) == 2
    artifact_store.delete_session_artifacts(session)
    assert len(fake.objects) == 0

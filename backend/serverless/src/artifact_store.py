"""S3 기반 문진 산출물 저장소.

DynamoDB에는 대기열과 상태 조회에 필요한 최소 메타데이터만 남깁니다.
문진 답변, 원페이퍼, 의사 답변, 환자 안내문, 최소 설명 trace는 이 모듈을
통해서만 S3에 저장합니다. 저장 직전 `artifact_policy.py`가 파일 종류별로
운영에 필요한 필드만 남기고, `privacy.py`가 직접식별정보 패턴을 가명처리합니다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from botocore.exceptions import ClientError

from artifact_policy import (
    ANSWER_FILE,
    CONSENT_FILE,
    DOCTOR_REVIEW_FILE,
    GUIDE_FILE,
    ONEPAPER_FILE,
    TRACE_FILE,
    prepare_artifact_payload,
)
from privacy import redact_payload
from settings import ARTIFACTS_BUCKET, S3_KMS_KEY_ID, S3_SERVER_SIDE_ENCRYPTION, s3
from utils import json_default, now_iso


def require_bucket() -> str:
    """S3 artifact bucket 설정이 없으면 배포 오류를 명확히 드러냅니다."""
    if not ARTIFACTS_BUCKET:
        raise RuntimeError("ARTIFACTS_BUCKET environment variable is required.")
    return ARTIFACTS_BUCKET


def date_part(value: str | None) -> str:
    """S3 prefix에 사용할 날짜를 YYYY-MM-DD 형식으로 반환합니다."""
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def session_prefix(session_id: str, created_at: str | None = None) -> str:
    """세션별 S3 폴더 prefix를 만듭니다."""
    return f"sessions/{date_part(created_at)}/{session_id}/"


def artifact_meta(session_id: str, created_at: str | None = None) -> dict[str, Any]:
    """DynamoDB 세션에 저장할 S3 위치 요약입니다."""
    prefix = session_prefix(session_id, created_at)
    return {
        "bucket": ARTIFACTS_BUCKET,
        "prefix": prefix,
        "answers_key": prefix + ANSWER_FILE,
        "onepaper_key": prefix + ONEPAPER_FILE,
        "guide_key": prefix + GUIDE_FILE,
        "consent_key": prefix + CONSENT_FILE,
        "trace_key": prefix + TRACE_FILE,
    }


def key_for(session: dict[str, Any], filename: str) -> str:
    """세션의 artifact prefix를 기준으로 파일 key를 계산합니다."""
    artifact = session.get("artifact") or {}
    prefix = artifact.get("prefix") or session_prefix(session.get("session_id"), session.get("created_at"))
    return prefix + filename


def put_json(session: dict[str, Any], filename: str, payload: Any) -> str:
    """payload를 운영 저장 정책과 가명처리를 거쳐 S3 JSON 객체로 저장합니다."""
    bucket = require_bucket()
    key = key_for(session, filename)
    cleaned_payload = prepare_artifact_payload(filename, payload)
    body = json.dumps(
        {
            "stored_at": now_iso(),
            "schema_version": "munjin-artifact-v1",
            "payload": redact_payload(cleaned_payload),
        },
        ensure_ascii=False,
        default=json_default,
    ).encode("utf-8")
    put_args = {
        "Bucket": bucket,
        "Key": key,
        "Body": body,
        "ContentType": "application/json; charset=utf-8",
    }
    # 버킷 기본 암호화가 빠져 있어도 객체 단위 암호화가 적용되도록 명시합니다.
    # KMS 키가 지정되면 aws:kms, 없으면 SSE-S3(AES256)를 사용합니다.
    if S3_KMS_KEY_ID:
        put_args["ServerSideEncryption"] = "aws:kms"
        put_args["SSEKMSKeyId"] = S3_KMS_KEY_ID
    elif S3_SERVER_SIDE_ENCRYPTION:
        put_args["ServerSideEncryption"] = S3_SERVER_SIDE_ENCRYPTION
    s3.put_object(**put_args)
    return key


def get_json(session: dict[str, Any], filename: str, default: Any = None) -> Any:
    """S3 JSON artifact를 읽습니다. 객체가 없으면 default를 반환합니다."""
    bucket = require_bucket()
    key = key_for(session, filename)
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return default
        raise
    raw = obj["Body"].read().decode("utf-8")
    data = json.loads(raw)
    return data.get("payload", default)


def load_answers(session: dict[str, Any]) -> dict[str, Any]:
    """문항별 답변 artifact를 읽고, 기존 DDB 저장 구조가 있으면 보조 경로로 읽습니다."""
    answers = get_json(session, ANSWER_FILE, default=None)
    if isinstance(answers, dict):
        return prepare_artifact_payload(ANSWER_FILE, answers)
    return prepare_artifact_payload(ANSWER_FILE, dict(session.get("responses") or session.get("question_results") or {}))


def save_answers(session: dict[str, Any], answers: dict[str, Any]) -> str:
    """문항별 답변/추출/IR 결과를 운영용 형태로 S3에 저장합니다."""
    return put_json(session, ANSWER_FILE, answers)


def save_trace(session: dict[str, Any], question_id: str, trace_payload: dict[str, Any]) -> str:
    """질문별 LLM/검증 trace를 최소 설명용 형태로 S3에 누적 저장합니다."""
    traces = get_json(session, TRACE_FILE, default={})
    if not isinstance(traces, dict):
        traces = {}
    traces[question_id] = trace_payload
    return put_json(session, TRACE_FILE, traces)


def update_question_trace(
    session: dict[str, Any],
    question_id: str,
    orchestration: dict[str, Any],
    trace: list[dict[str, Any]],
) -> None:
    """최종 LangGraph trace는 답변 artifact가 아니라 별도 최소 trace에만 반영합니다."""
    save_trace(session, question_id, {"orchestration": orchestration, "pipeline_trace": trace})

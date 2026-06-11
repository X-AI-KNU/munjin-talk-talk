"""DynamoDB 세션 저장소.

이 모듈은 문진 대기열과 세션 상태 조회에 필요한 최소 메타데이터만
DynamoDB에 저장합니다. 환자 발화, LLM 추출 결과, 원페이퍼, 환자 안내문은
`artifact_store.py`를 통해 S3에 저장하고, DynamoDB에는 S3 key와 상태만
남기는 구조를 지향합니다.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from artifact_store import artifact_meta, load_answers, put_json, CONSENT_FILE
from privacy import consent_summary, sanitize_reception_patient
from settings import table
from utils import ddb_value, mask_name, normalize_visit_type, now_iso

QUEUE_COUNTER_SESSION_ID = "__meta_queue_counter__"


def make_session_id() -> str:
    """새 문진 세션의 고유 ID를 만듭니다."""
    return f"s_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def get_session(session_id: str | None) -> dict[str, Any] | None:
    """session_id로 DynamoDB item을 조회합니다."""
    if not session_id:
        return None
    res = table.get_item(Key={"session_id": session_id})
    return res.get("Item")


def put_session(item: dict[str, Any]) -> dict[str, Any]:
    """DynamoDB에 item을 저장합니다."""
    converted = ddb_value(item)
    table.put_item(Item=converted)
    return converted


def _scan_max_queue_number() -> int:
    """기존 세션의 최대 대기번호를 읽어 counter 초기값으로 사용합니다."""
    try:
        res = table.scan(ProjectionExpression="queue_number", Limit=1000)
        numbers = [int(item.get("queue_number") or 0) for item in res.get("Items", [])]
        return max(numbers or [0])
    except Exception:
        return 0


def next_queue_number() -> int:
    """오늘 대기열 표시용 순번을 DynamoDB 원자 counter로 발급합니다.

    scan 후 max+1 방식은 동시 접수에서 같은 번호가 나올 수 있습니다.
    별도 meta item에 `ADD queue_counter :one`을 적용하면 DynamoDB가 증가를
    원자적으로 처리합니다. 실패 시에만 보수적인 fallback을 사용합니다.
    """
    try:
        try:
            table.put_item(
                Item={
                    "session_id": QUEUE_COUNTER_SESSION_ID,
                    "queue_counter": _scan_max_queue_number(),
                },
                ConditionExpression="attribute_not_exists(session_id)",
            )
        except Exception:
            # 이미 다른 요청이 counter를 만들었다면 정상 경합입니다.
            pass
        res = table.update_item(
            Key={"session_id": QUEUE_COUNTER_SESSION_ID},
            UpdateExpression="ADD queue_counter :one",
            ExpressionAttributeValues={":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        return int(res["Attributes"]["queue_counter"])
    except Exception:
        fallback = _scan_max_queue_number()
        return fallback + 1 if fallback else int(time.time()) % 10000


def update_session(session_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    """DynamoDB item의 일부 필드만 SET expression으로 갱신합니다."""
    if not updates:
        return get_session(session_id)

    names: dict[str, str] = {}
    values: dict[str, Any] = {}
    expr: list[str] = []
    for idx, (key, value) in enumerate(updates.items()):
        nk = f"#k{idx}"
        vk = f":v{idx}"
        names[nk] = key
        values[vk] = ddb_value(value)
        expr.append(f"{nk} = {vk}")

    names["#updated_at"] = "updated_at"
    values[":updated_at"] = now_iso()
    expr.append("#updated_at = :updated_at")
    res = table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET " + ", ".join(expr),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    return res.get("Attributes")


def create_session(body: dict[str, Any]) -> dict[str, Any]:
    """접수처 입력값으로 문진 세션을 생성합니다.

    실명, 생년월일, 연락처는 저장하지 않습니다. 생년월일은 나이 계산에만
    사용되고, 실명은 마스킹 표시명으로만 변환됩니다.
    """
    patient_input = body.get("patient") or body
    visit_type = normalize_visit_type(body.get("visit_type") or body.get("visitType"))
    session_id = body.get("session_id") or body.get("sessionId") or make_session_id()
    created_at = now_iso()
    patient = sanitize_reception_patient(patient_input)
    if not patient.get("receipt_id"):
        patient["receipt_id"] = f"R-{int(time.time()) % 10000:04d}"

    item = {
        "session_id": session_id,
        "queue_number": body.get("queue_number") or body.get("queueNumber") or next_queue_number(),
        "created_at": created_at,
        "updated_at": created_at,
        "expires_at": int(time.time()) + 3 * 24 * 60 * 60,
        "status": "waiting_tablet",
        "visit_type": visit_type,
        "risk": "none",
        "patient": patient,
        "artifact": artifact_meta(session_id, created_at),
        "question_status": {},
        "onepager_ready": False,
        "guide_ready": False,
    }
    return put_session(item)


def save_patient_consent(session_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
    """환자 동의 상세는 S3에, 요약은 DynamoDB에 저장합니다."""
    session = get_session(session_id)
    if not session:
        return None

    accepted = bool(body.get("accepted"))
    now = now_iso()
    consent = {
        "accepted": accepted,
        "version": body.get("version") or "munjin-privacy-consent-v1",
        "method": "patient_tablet_modal",
        "recorded_at": now,
        "accepted_at": now if accepted else None,
        "rejected_at": now if not accepted else None,
        "privacy_items": body.get("privacy_items") or [],
        "sensitive_items": body.get("sensitive_items") or [],
        "retention_notice": body.get("retention_notice") or "문진 산출물은 MVP 운영 정책에 따라 임시 보관 후 삭제됩니다.",
    }
    put_json(session, CONSENT_FILE, consent)

    updates = {
        "privacy_consent": consent_summary(consent),
    }
    if not accepted:
        updates["status"] = "consent_rejected"
    return update_session(session_id, updates)


def public_session(session: dict[str, Any], include_artifacts: bool = False) -> dict[str, Any]:
    """프론트엔드가 쓰는 세션 응답을 최소 필드 중심으로 반환합니다.

    대기열 목록에서는 artifact를 포함하지 않습니다. 직원 직접 입력처럼 세션
    상세가 필요한 API에서만 S3에 있는 가명처리 답변을 포함합니다.
    """
    patient = session.get("patient", {})
    patient_name = patient.get("name") or mask_name(patient.get("full_name"))
    payload = {
        "sessionId": session.get("session_id"),
        "session_id": session.get("session_id"),
        "queueNumber": session.get("queue_number") or 0,
        "status": session.get("status", "waiting_tablet"),
        "visitType": session.get("visit_type", "initial"),
        "visit_type": session.get("visit_type", "initial"),
        "risk": session.get("risk", "none"),
        "onepagerReady": bool(session.get("onepager_ready")),
        "guideReady": bool(session.get("guide_ready")),
        "patient": {
            "name": patient_name or "환자",
            "age": patient.get("age", ""),
            "ageBand": patient.get("age_band", ""),
            "gender": patient.get("gender", "-"),
            "receiptId": patient.get("receipt_id", ""),
            "department": patient.get("department", "이비인후과"),
            "doctor": patient.get("doctor", ""),
            "honorific": patient.get("honorific", "어르신"),
        },
        "privacyConsent": session.get("privacy_consent", {}),
        "privacy_consent": session.get("privacy_consent", {}),
        "questionStatus": session.get("question_status", {}),
        "createdAt": session.get("created_at"),
        "updatedAt": session.get("updated_at"),
    }
    if include_artifacts:
        payload["responses"] = load_answers(session)
    return payload


def list_sessions() -> list[dict[str, Any]]:
    """접수처와 의사 대기열에서 사용할 최신 세션 목록을 반환합니다."""
    res = table.scan(Limit=100)
    items = [
        item for item in res.get("Items", [])
        if not str(item.get("session_id") or "").startswith("__meta")
    ]
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return [public_session(item) for item in items]

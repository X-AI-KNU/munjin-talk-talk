"""직원/의료진/환자 접근 제어를 담당하는 보안 헬퍼.

직원과 의료진은 사람이 외울 수 있는 접근 코드를 한 번 입력합니다.
백엔드는 접근 코드가 맞을 때만 짧은 시간 유효한 HMAC 서명 토큰을 발급하고,
이후 보호 API는 ``Authorization: Bearer <token>`` 헤더로 역할을 검증합니다.

환자 태블릿은 직원이 세션을 생성할 때 발급되는 세션별 난수 토큰만 사용합니다.
이렇게 분리하면 환자는 로그인 과정을 겪지 않고, 내부 화면은 역할 기반으로 보호됩니다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs

from settings import (
    AUTH_SIGNING_SECRET,
    AUTH_TOKEN_TTL_MINUTES,
    DOCTOR_ACCESS_CODE,
    DOCTOR_ACCESS_CODE_SHA256,
    STAFF_ACCESS_CODE,
    STAFF_ACCESS_CODE_SHA256,
)
from utils import response


PATIENT_HEADER = "x-munjin-patient-token"
ACCESS_HEADER = "x-munjin-access-token"  # 기존 클라이언트 호환용. 신규 클라이언트는 Authorization을 사용합니다.
ALLOWED_ROLES = {"staff", "doctor"}


def headers(event: dict[str, Any]) -> dict[str, str]:
    """API Gateway header를 소문자 key dict로 정규화합니다."""
    return {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items() if v is not None}


def query_params(event: dict[str, Any]) -> dict[str, str]:
    """REST/HTTP API 양쪽 이벤트 형식에서 query string을 꺼냅니다."""
    direct = event.get("queryStringParameters") or {}
    if direct:
        return {str(k): str(v) for k, v in direct.items() if v is not None}
    raw = event.get("rawQueryString") or ""
    parsed = parse_qs(raw, keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items() if values}


def _b64url_encode(raw: bytes) -> str:
    """토큰에 쓰기 좋은 padding 없는 base64url 문자열로 바꿉니다."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    """padding 없는 base64url 문자열을 bytes로 되돌립니다."""
    padded = value + ("=" * (-len(value) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _same(left: str, right: str) -> bool:
    """비밀값 비교 시 타이밍 차이를 줄이기 위해 compare_digest를 사용합니다."""
    if not left or not right:
        return False
    return hmac.compare_digest(str(left), str(right))


def _sha256(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _bearer_value(value: str) -> str:
    value = str(value or "").strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value


def _role_config(role: str) -> tuple[str, str]:
    """역할별 접근 코드와 해시 설정을 반환합니다."""
    if role == "staff":
        return STAFF_ACCESS_CODE, STAFF_ACCESS_CODE_SHA256
    if role == "doctor":
        return DOCTOR_ACCESS_CODE, DOCTOR_ACCESS_CODE_SHA256
    return "", ""


def _auth_configured_for(role: str) -> bool:
    code, code_hash = _role_config(role)
    return bool((code or code_hash) and AUTH_SIGNING_SECRET)


def is_auth_configured(role: str) -> bool:
    """로그인 가능한 역할 설정이 갖춰졌는지 외부 라우터에서 확인할 때 사용합니다."""
    return _auth_configured_for(role)


def verify_access_code(role: str, access_code: str) -> bool:
    """로그인 요청의 접근 코드가 서버 설정과 일치하는지 확인합니다.

    운영에서는 *_ACCESS_CODE_SHA256 환경변수를 우선 사용할 수 있습니다.
    해시가 없으면 MVP 배포 편의를 위해 평문 접근 코드와 상수 시간 비교를 수행합니다.
    """
    if role not in ALLOWED_ROLES or not access_code:
        return False
    code, code_hash = _role_config(role)
    if code_hash:
        return _same(_sha256(access_code), code_hash)
    return _same(access_code, code)


def _sign(payload_segment: str) -> str:
    digest = hmac.new(
        AUTH_SIGNING_SECRET.encode("utf-8"),
        payload_segment.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return _b64url_encode(digest)


def issue_role_token(role: str) -> dict[str, Any]:
    """역할 세션 토큰을 발급합니다.

    토큰은 서버에 저장하지 않습니다. payload와 HMAC 서명만으로 검증되므로
    Lambda가 재시작되어도 같은 AUTH_SIGNING_SECRET이면 계속 검증할 수 있습니다.
    """
    now = int(time.time())
    ttl_seconds = max(5, AUTH_TOKEN_TTL_MINUTES) * 60
    expires_at = now + ttl_seconds
    payload = {
        "typ": "munjin-role-session",
        "role": role,
        "iat": now,
        "exp": expires_at,
        "nonce": secrets.token_urlsafe(12),
    }
    payload_segment = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    token = f"{payload_segment}.{_sign(payload_segment)}"
    return {
        "access_token": token,
        "token_type": "Bearer",
        "role": role,
        "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        "expires_in": ttl_seconds,
    }


def token_from_event(event: dict[str, Any]) -> str:
    """Authorization Bearer 토큰을 읽습니다. 기존 헤더도 세션 토큰이면 허용합니다."""
    hs = headers(event)
    return _bearer_value(hs.get("authorization") or hs.get(ACCESS_HEADER) or "")


def role_for_event(event: dict[str, Any]) -> str | None:
    """요청의 서명 세션 토큰을 검증하고 역할을 반환합니다."""
    token = token_from_event(event)
    if not token or "." not in token or not AUTH_SIGNING_SECRET:
        return None
    payload_segment, signature = token.rsplit(".", 1)
    if not _same(signature, _sign(payload_segment)):
        return None
    try:
        payload = json.loads(_b64url_decode(payload_segment).decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    if payload.get("typ") != "munjin-role-session":
        return None
    role = str(payload.get("role") or "")
    if role not in ALLOWED_ROLES:
        return None
    if int(payload.get("exp") or 0) <= int(time.time()):
        return None
    return role


def patient_token(event: dict[str, Any], body: dict[str, Any] | None = None) -> str:
    """환자 세션 토큰을 header, query string, body 순서로 확인합니다."""
    hs = headers(event)
    qs = query_params(event)
    body = body or {}
    return str(
        hs.get(PATIENT_HEADER)
        or qs.get("pt")
        or qs.get("patient_token")
        or body.get("patient_token")
        or body.get("patientToken")
        or ""
    ).strip()


def forbidden(message: str = "접근 권한이 없습니다."):
    return response(403, {"error": "forbidden", "message": message})


def auth_not_configured(role: str):
    return response(
        503,
        {
            "error": "auth_not_configured",
            "message": f"{role} 인증 설정이 서버 환경 변수에 없습니다.",
        },
    )


def require_role(event: dict[str, Any], *roles: str):
    """요청이 허용된 역할 중 하나인지 확인합니다. 통과 시 None을 반환합니다."""
    actual = role_for_event(event)
    if actual in roles:
        return None
    if all(not _auth_configured_for(role) for role in roles):
        return auth_not_configured("/".join(roles))
    return forbidden()


def session_patient_secret(session: dict[str, Any] | None) -> str:
    """DynamoDB 세션에 저장된 환자 전용 토큰을 반환합니다."""
    if not session:
        return ""
    patient_access = session.get("patient_access") or {}
    return str(patient_access.get("token") or session.get("patient_token") or "").strip()


def require_patient_session(
    event: dict[str, Any],
    session: dict[str, Any],
    body: dict[str, Any] | None = None,
    allow_roles: tuple[str, ...] = ("staff", "doctor"),
):
    """환자 토큰 또는 허용된 내부 역할 토큰으로 특정 세션 접근을 검증합니다."""
    role = role_for_event(event)
    if role in allow_roles:
        return None

    expected = session_patient_secret(session)
    if not expected:
        return response(
            503,
            {
                "error": "patient_token_not_configured",
                "message": "세션에 환자 접근 토큰이 없습니다. 접수 화면에서 세션을 다시 생성해 주세요.",
            },
        )
    if _same(patient_token(event, body), expected):
        return None
    return forbidden("이 문진 세션에 접근할 수 없습니다.")

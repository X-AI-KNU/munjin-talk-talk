"""Small shared helpers used by the backend modules.

도메인 로직이 아닌 날짜, JSON 직렬화, 문자열 정규화 같은 공통 함수를 둡니다.
특정 기능에만 쓰이는 함수는 되도록 해당 모듈 안에 둡니다.
"""

import json
import os
import re
import contextvars
from datetime import datetime, timezone
from decimal import Decimal

_REQUEST_ORIGIN = contextvars.ContextVar("request_origin", default="")

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def response(status, body):
    """API Gateway가 기대하는 JSON HTTP 응답 형식으로 감쌉니다."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": cors_allow_origin(),
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Munjin-Access-Token,X-Munjin-Patient-Token",
            "Vary": "Origin",
        },
        "body": json.dumps(body, ensure_ascii=False, default=json_default),
    }


def set_request_origin(origin):
    """현재 요청의 Origin을 저장해 CORS 응답에서 허용 여부를 판별합니다."""
    _REQUEST_ORIGIN.set(str(origin or "").strip())


def allowed_origins():
    return [item.strip() for item in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if item.strip()]


def cors_allow_origin():
    """환경 변수 기반 CORS origin을 반환합니다.

    개발/기존 배포 호환을 위해 기본값은 `*`입니다. 제출용 또는 공개 배포용
    배포에서는 SAM parameter `CorsAllowOrigin`을 Amplify HTTPS 도메인으로
    지정해 API 호출 출처를 좁히는 것을 권장합니다.
    """
    origins = allowed_origins()
    if not origins or "*" in origins:
        return "*"
    request_origin = _REQUEST_ORIGIN.get("")
    if request_origin in origins:
        return request_origin
    return origins[0]


def json_default(value):
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    raise TypeError(f"Not JSON serializable: {type(value)}")


def ddb_value(value):
    """DynamoDB가 float를 직접 받지 못하므로 Decimal로 재귀 변환합니다."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [ddb_value(item) for item in value]
    if isinstance(value, dict):
        return {key: ddb_value(item) for key, item in value.items()}
    return value


def parse_body(event):
    """API Gateway event body를 dict로 안전하게 변환합니다."""
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def normalize_visit_type(value):
    if value in ("followup", "재진"):
        return "followup"
    return "initial"


def visit_label(value):
    return "재진" if normalize_visit_type(value) == "followup" else "초진"


def mask_name(name):
    text = str(name or "").strip()
    if not text:
        return "환자"
    if len(text) == 1:
        return text
    return f"{text[0]}*{text[-1]}"


def calculate_age(birth_date):
    if not birth_date:
        return ""
    try:
        birth = datetime.strptime(birth_date, "%Y-%m-%d").date()
    except ValueError:
        return ""
    today = datetime.now().date()
    if birth > today or birth.year < 1900:
        return ""
    age = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        age -= 1
    if age < 0 or age > 130:
        return ""
    return age


def normalize_text(text):
    """검색과 비교 전에 공백/특수 공백 문자를 정리합니다."""
    if text is None:
        return ""
    text = str(text).replace("\u200b", " ").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def compact_ir(text):
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", normalize_text(text))


def load_json_file(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def split_sentences_ir(text):
    text = normalize_text(text)
    if not text:
        return []
    raw = re.split(r"(?<=[.!?。])\s+|\n+", text)
    out = []
    for item in raw:
        item = normalize_text(item).strip(" .")
        if len(item) >= 8:
            out.append(item)
    return out


def sentence_directly_mentions_symptom(sentence, symptom):
    sentence_key = compact_ir(sentence)
    symptom_key = compact_ir(symptom)
    if not sentence_key or not symptom_key:
        return False
    if symptom_key in sentence_key:
        return True
    parts = [compact_ir(part) for part in re.split(r"\s+", symptom) if len(compact_ir(part)) >= 2]
    return len(parts) >= 2 and all(part in sentence_key for part in parts)


def trim_snippet(text, max_len=180):
    text = normalize_text(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def find_keyword_quote(text, keywords):
    for kw in keywords:
        idx = text.find(kw)
        if idx >= 0:
            sentence = sentence_for(text, kw)
            if sentence:
                return clean_quote(sentence)
            start = max(0, idx - 6)
            end = min(len(text), idx + len(kw) + 10)
            return clean_quote(text[start:end])
    return ""


def clean_quote(text):
    return re.sub(r"\s+", " ", str(text or "")).strip(" .,?!。\"'")


def sentence_for(text, keyword):
    for part in re.split(r"[.?!。]", text):
        if keyword in part:
            return clean_quote(part)
    return ""


def find_first_pattern(text, patterns):
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return clean_quote(m.group(0))
    return ""


def unique(values):
    out = []
    seen = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def format_hhmm(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        dt = datetime.now()
    return f"{dt.hour:02d}:{dt.minute:02d}"

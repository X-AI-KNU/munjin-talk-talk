"""Amazon Transcribe integration without storing patient audio.

The runtime flow no longer uploads patient voice to S3. Lambda only creates a
short-lived presigned Transcribe Streaming WebSocket URL. The browser streams
PCM audio directly to Amazon Transcribe and sends only confirmed text into the
LLM/IR pipeline.
"""

import re
import uuid
from urllib.parse import urlencode

import boto3
from botocore.auth import SigV4QueryAuth
from botocore.awsrequest import AWSRequest

from settings import CUSTOM_VOCABULARY, REGION
from sessions import create_session, get_session, update_session
from utils import normalize_visit_type, response


def configured_custom_vocabulary():
    """실제 등록된 사용자 어휘집 이름이 있을 때만 Transcribe에 전달합니다."""
    value = str(CUSTOM_VOCABULARY or "").strip()
    if value.lower() in ("", "unused", "none", "null", "-"):
        return ""
    return value


def make_audio_key(session_id, question_id, content_type):
    """Legacy helper retained only for old imports; audio keys are not used."""
    ext = "webm"
    if "/" in str(content_type or ""):
        ext = content_type.split("/")[-1].split(";")[0] or "webm"
    if ext == "mpeg":
        ext = "mp3"
    return f"sessions/{session_id}/{question_id}.{ext}"


def generate_upload_url(body):
    """Deprecated endpoint: storing patient audio in S3 is disabled."""
    return None, response(410, {
        "error": "audio_storage_disabled",
        "message": "Use /transcribe-stream-url for real-time Transcribe Streaming.",
    })


def generate_streaming_transcribe_url(body):
    """Return a presigned WebSocket URL for Amazon Transcribe Streaming.

    This function does not receive or persist audio. It only signs a URL with
    the selected language, PCM encoding, and sample rate.
    """
    session_id = body.get("session_id") or body.get("sessionId")
    question_id = body.get("question_id") or body.get("questionId")
    visit_type = normalize_visit_type(body.get("visit_type") or body.get("visitType"))
    sample_rate = int(body.get("sample_rate") or body.get("sampleRate") or 16000)
    if not session_id or not question_id:
        return None, response(400, {"error": "missing_session_or_question"})
    if question_id not in ("Q1", "Q2", "Q3", "Q4"):
        return None, response(400, {"error": "invalid_question_id"})
    if sample_rate < 8000 or sample_rate > 48000:
        return None, response(400, {"error": "invalid_sample_rate"})

    session = get_session(session_id)
    if not session:
        session = create_session({"session_id": session_id, "visit_type": visit_type})

    # Amazon Transcribe Streaming의 session-id는 UUID 형식만 허용한다.
    # 서비스의 문진 session_id는 `s_...` 형태라 그대로 넘기면 WebSocket이
    # 열리자마자 ValidationException으로 종료되므로, 스트리밍 연결마다
    # AWS 규격에 맞는 별도 UUID를 발급한다. 이 값은 저장 식별자가 아니라
    # Transcribe 연결 추적용 임시 ID다.
    stream_session_id = str(uuid.uuid4())
    params = {
        "language-code": "ko-KR",
        "media-encoding": "pcm",
        "sample-rate": str(sample_rate),
        "session-id": stream_session_id,
    }
    vocabulary_name = configured_custom_vocabulary()
    if vocabulary_name:
        params["vocabulary-name"] = vocabulary_name

    url = (
        f"https://transcribestreaming.{REGION}.amazonaws.com:8443"
        f"/stream-transcription-websocket?{urlencode(params)}"
    )
    credentials = boto3.Session().get_credentials().get_frozen_credentials()
    request = AWSRequest(method="GET", url=url)
    SigV4QueryAuth(credentials, "transcribe", REGION, expires=300).add_auth(request)
    stream_url = request.url.replace("https://", "wss://", 1)

    streaming = session.get("streaming_stt", {})
    streaming[question_id] = {
        "provider": "amazon_transcribe_streaming",
        "language_code": "ko-KR",
        "sample_rate": sample_rate,
        "media_encoding": "pcm",
        "audio_stored": False,
    }
    update_session(session_id, {"streaming_stt": streaming, "status": "in_progress"})

    return {
        "stream_url": stream_url,
        "sample_rate": sample_rate,
        "media_encoding": "pcm",
        "language_code": "ko-KR",
        "audio_stored": False,
        "expires_in": 300,
    }, None


def parse_job_name(job_name):
    """Legacy batch job parser retained for compatibility tests."""
    m = re.match(r"^(.*)-(Q[1-4])(?:-[0-9A-Za-z]+)?$", str(job_name or ""))
    if not m:
        return None, None
    return m.group(1), m.group(2)


def safe_job_name(job_name):
    """Transcribe session/job names allow only a restricted character set."""
    return re.sub(r"[^0-9A-Za-z._-]", "-", str(job_name))[:180]


def get_or_start_transcript(job_name):
    """Deprecated endpoint: S3 batch transcription is disabled."""
    return response(410, {
        "error": "batch_transcribe_disabled",
        "message": "Use real-time Transcribe Streaming. Patient audio is not persisted.",
    })


def extract_confidence(payload):
    """Legacy helper retained for old tests; streaming UI no longer uses it."""
    try:
        items = payload.get("results", {}).get("items", [])
        vals = [
            float(alt.get("confidence"))
            for item in items
            for alt in item.get("alternatives", [])
            if alt.get("confidence") is not None
        ]
        if vals:
            return round(sum(vals) / len(vals), 3)
    except Exception:
        return None
    return None

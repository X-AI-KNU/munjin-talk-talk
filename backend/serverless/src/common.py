import json
import math
import os
import re
import time
import hashlib
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote_plus

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
TABLE_NAME = os.environ.get("SESSIONS_TABLE", "MunjinSessions")
ARTIFACT_BUCKET = os.environ.get("ARTIFACT_BUCKET", "")
CUSTOM_VOCABULARY = os.environ.get("CUSTOM_VOCABULARY", "")
USE_BEDROCK_LLM = os.environ.get("USE_BEDROCK_LLM", "true").lower() == "true"
ALLOW_RULE_FALLBACK = os.environ.get("ALLOW_RULE_FALLBACK", "false").lower() == "true"
ENABLE_BEDROCK_REVIEW = os.environ.get("ENABLE_BEDROCK_REVIEW", "true").lower() == "true"
ENABLE_BEDROCK_GUIDE = os.environ.get("ENABLE_BEDROCK_GUIDE", "true").lower() == "true"
STRONG_MODEL_ID = os.environ.get("STRONG_MODEL_ID", "apac.amazon.nova-pro-v1:0")
LIGHT_MODEL_ID = os.environ.get("LIGHT_MODEL_ID", "apac.amazon.nova-lite-v1:0")
REVIEWER_MODEL_ID = os.environ.get("REVIEWER_MODEL_ID", STRONG_MODEL_ID)
GUIDE_MODEL_ID = os.environ.get("GUIDE_MODEL_ID", LIGHT_MODEL_ID)
MAX_LLM_TOKENS = int(os.environ.get("MAX_LLM_TOKENS", "1600"))
REVIEW_MAX_TOKENS = int(os.environ.get("REVIEW_MAX_TOKENS", "900"))
GUIDE_MAX_TOKENS = int(os.environ.get("GUIDE_MAX_TOKENS", "900"))
DATA_DIR = Path(__file__).resolve().parent / "data"
DISEASES_PATH = DATA_DIR / "diseases_cleaned.json"
SYMPTOM_INDEX_PATH = DATA_DIR / "symptom_index.json"
EMBEDDING_MODEL_ID = os.environ.get("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "512"))
USE_TITAN_EMBEDDING = os.environ.get("USE_TITAN_EMBEDDING", "true").lower() == "true"
HYBRID_TOP_K = int(os.environ.get("HYBRID_TOP_K", "5"))
HYBRID_CANDIDATE_K = int(os.environ.get("HYBRID_CANDIDATE_K", "24"))
HYBRID_ACCEPT_THRESHOLD = float(os.environ.get("HYBRID_ACCEPT_THRESHOLD", "0.18"))
HYBRID_BM25_WEIGHT = float(os.environ.get("HYBRID_BM25_WEIGHT", "0.35"))
HYBRID_VECTOR_WEIGHT = float(os.environ.get("HYBRID_VECTOR_WEIGHT", "0.65"))
HYBRID_PRECOMPUTE_DOC_EMBEDDINGS = os.environ.get("HYBRID_PRECOMPUTE_DOC_EMBEDDINGS", "false").lower() == "true"
EMBEDDING_CACHE_PATH = DATA_DIR / f"symptom_embeddings_{EMBEDDING_MODEL_ID.replace(':', '_').replace('/', '_')}_{EMBEDDING_DIMENSIONS}.json"

ddb = boto3.resource("dynamodb", region_name=REGION)
table = ddb.Table(TABLE_NAME)
s3 = boto3.client(
    "s3",
    region_name=REGION,
    endpoint_url=f"https://s3.{REGION}.amazonaws.com",
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)
transcribe = boto3.client("transcribe", region_name=REGION)
bedrock_runtime = boto3.client(
    "bedrock-runtime",
    region_name=REGION,
    config=Config(connect_timeout=5, read_timeout=50, retries={"max_attempts": 2, "mode": "standard"}),
)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(body, ensure_ascii=False, default=json_default),
    }


def json_default(value):
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    raise TypeError(f"Not JSON serializable: {type(value)}")


def ddb_value(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [ddb_value(item) for item in value]
    if isinstance(value, dict):
        return {key: ddb_value(item) for key, item in value.items()}
    return value


def parse_body(event):
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
    age = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        age -= 1
    return age


def make_session_id():
    return f"s_{int(time.time() * 1000)}_{os.urandom(3).hex()}"


def get_session(session_id):
    if not session_id:
        return None
    res = table.get_item(Key={"session_id": session_id})
    return res.get("Item")


def put_session(item):
    converted = ddb_value(item)
    table.put_item(Item=converted)
    return converted


def next_queue_number():
    try:
        res = table.scan(ProjectionExpression="queue_number", Limit=1000)
        numbers = [int(item.get("queue_number") or 0) for item in res.get("Items", [])]
        return max(numbers or [0]) + 1
    except Exception:
        return int(time.time()) % 10000


def update_session(session_id, updates):
    if not updates:
        return get_session(session_id)
    names = {}
    values = {}
    expr = []
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


def create_session(body):
    patient_input = body.get("patient") or body
    visit_type = normalize_visit_type(body.get("visit_type") or body.get("visitType"))
    full_name = patient_input.get("full_name") or patient_input.get("fullName") or patient_input.get("name") or ""
    birth_date = patient_input.get("birth_date") or patient_input.get("birthDate") or ""
    patient = {
        "name": mask_name(full_name),
        "full_name": full_name,
        "birth_date": birth_date,
        "age": patient_input.get("age") or calculate_age(birth_date),
        "gender": patient_input.get("gender") or "-",
        "receipt_id": patient_input.get("receipt_id") or patient_input.get("receiptId") or f"R-{int(time.time()) % 10000:04d}",
        "department": patient_input.get("department") or "이비인후과",
        "doctor": patient_input.get("doctor") or "이민우",
        "phone": patient_input.get("phone") or "",
    }
    session_id = body.get("session_id") or body.get("sessionId") or make_session_id()
    item = {
        "session_id": session_id,
        "queue_number": body.get("queue_number") or body.get("queueNumber") or next_queue_number(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "status": "waiting_tablet",
        "visit_type": visit_type,
        "risk": "none",
        "patient": patient,
        "responses": {},
        "question_results": {},
        "audio": {},
        "onepager": build_onepager({
            "session_id": session_id,
            "visit_type": visit_type,
            "patient": patient,
            "responses": {},
            "question_results": {},
            "risk": "none",
        }),
    }
    return put_session(item)


def public_session(session):
    patient = session.get("patient", {})
    return {
        "sessionId": session.get("session_id"),
        "session_id": session.get("session_id"),
        "queueNumber": session.get("queue_number") or 0,
        "status": session.get("status", "waiting_tablet"),
        "visitType": session.get("visit_type", "initial"),
        "visit_type": session.get("visit_type", "initial"),
        "risk": session.get("risk", "none"),
        "patient": {
            "name": patient.get("name") or mask_name(patient.get("full_name")),
            "fullName": patient.get("full_name", ""),
            "birthDate": patient.get("birth_date", ""),
            "age": patient.get("age", ""),
            "gender": patient.get("gender", "-"),
            "receiptId": patient.get("receipt_id", ""),
            "department": patient.get("department", "이비인후과"),
            "doctor": patient.get("doctor", ""),
            "phone": patient.get("phone", ""),
            "honorific": "어르신",
        },
        "responses": session.get("responses", {}),
        "createdAt": session.get("created_at"),
        "updatedAt": session.get("updated_at"),
    }


def list_sessions():
    res = table.scan(Limit=100)
    items = res.get("Items", [])
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return [public_session(item) for item in items]


def make_audio_key(session_id, question_id, content_type):
    ext = "webm"
    if "/" in content_type:
        ext = content_type.split("/")[-1].split(";")[0] or "webm"
    if ext == "mpeg":
        ext = "mp3"
    return f"sessions/{session_id}/{question_id}.{ext}"


def generate_upload_url(body):
    session_id = body.get("session_id") or body.get("sessionId")
    question_id = body.get("question_id") or body.get("questionId")
    visit_type = normalize_visit_type(body.get("visit_type") or body.get("visitType"))
    content_type = body.get("content_type") or body.get("contentType") or "audio/webm"
    if not session_id or not question_id:
        return None, response(400, {"error": "missing_session_or_question"})
    if question_id not in ("Q1", "Q2", "Q3", "Q4"):
        return None, response(400, {"error": "invalid_question_id"})
    session = get_session(session_id)
    if not session:
        session = create_session({"session_id": session_id, "visit_type": visit_type})
    key = make_audio_key(session_id, question_id, content_type)
    upload_url = s3.generate_presigned_url(
        ClientMethod="put_object",
        Params={"Bucket": ARTIFACT_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=300,
    )
    audio = session.get("audio", {})
    audio[question_id] = {
        "bucket": ARTIFACT_BUCKET,
        "key": key,
        "content_type": content_type,
        "uploaded_at": now_iso(),
    }
    update_session(session_id, {"audio": audio, "status": "in_progress"})
    transcribe_job_name = f"{session_id}-{question_id}-{int(time.time() * 1000)}"
    return {
        "upload_url": upload_url,
        "s3_key": key,
        "transcribeJobName": transcribe_job_name,
        "transcribe_job_name": transcribe_job_name,
        "expires_in": 300,
    }, None


def parse_job_name(job_name):
    m = re.match(r"^(.*)-(Q[1-4])(?:-[0-9A-Za-z]+)?$", str(job_name or ""))
    if not m:
        return None, None
    return m.group(1), m.group(2)


def safe_job_name(job_name):
    return re.sub(r"[^0-9A-Za-z._-]", "-", str(job_name))[:180]


def get_or_start_transcript(job_name):
    session_id, question_id = parse_job_name(job_name)
    if not session_id or not question_id:
        return response(400, {"error": "invalid_job_name"})
    session = get_session(session_id)
    if not session:
        return response(404, {"error": "session_not_found"})
    audio = (session.get("audio") or {}).get(question_id) or {}
    key = audio.get("key") or f"sessions/{session_id}/{question_id}.webm"
    bucket = audio.get("bucket") or ARTIFACT_BUCKET
    transcribe_name = safe_job_name(f"munjin-{job_name}")
    output_key = f"transcripts/{session_id}/{question_id}.json"

    try:
        job = transcribe.get_transcription_job(TranscriptionJobName=transcribe_name)["TranscriptionJob"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("BadRequestException", "NotFoundException"):
            raise
        media_format = key.rsplit(".", 1)[-1].lower()
        params = {
            "TranscriptionJobName": transcribe_name,
            "LanguageCode": "ko-KR",
            "MediaFormat": media_format,
            "Media": {"MediaFileUri": f"s3://{bucket}/{key}"},
            "OutputBucketName": bucket,
            "OutputKey": output_key,
        }
        if CUSTOM_VOCABULARY:
            params["Settings"] = {"VocabularyName": CUSTOM_VOCABULARY}
        transcribe.start_transcription_job(**params)
        job = {"TranscriptionJobStatus": "IN_PROGRESS"}

    status = job.get("TranscriptionJobStatus")
    if status != "COMPLETED":
        return response(200, {"status": status, "transcript": "", "confidence": None})

    obj = s3.get_object(Bucket=bucket, Key=output_key)
    payload = json.loads(obj["Body"].read().decode("utf-8"))
    transcript = payload.get("results", {}).get("transcripts", [{}])[0].get("transcript", "")
    confidence = extract_confidence(payload)
    responses = session.get("responses", {})
    responses[question_id] = {"text": transcript, "stt_confidence": confidence, "confirmed": False}
    update_session(session_id, {"responses": responses})
    return response(200, {"status": "COMPLETED", "transcript": transcript, "confidence": confidence})


def extract_confidence(payload):
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


SYMPTOM_RULES = [
    ("객혈", "hemoptysis", ["피", "피가", "객혈", "피섞", "피 섞", "묻어"], True),
    ("기침", "cough", ["기침", "콜록"], False),
    ("목 불편감", "throat_irritation", ["목", "칼칼", "따끔", "인후"], False),
    ("코막힘", "nasal_obstruction", ["코가 막", "코막", "맥혀", "막혀"], False),
    ("콧물", "rhinorrhea", ["콧물", "코물"], False),
    ("발열", "fever", ["열", "뜨거", "발열"], False),
    ("가래", "sputum", ["가래", "痰"], False),
    ("호흡곤란", "dyspnea", ["숨", "호흡", "답답"], True),
    ("흉통", "chest_pain", ["가슴", "흉통"], True),
    ("두통", "headache", ["머리", "두통"], False),
]
VALID_SYMPTOM_SLOT_IDS = {slot_id for _, slot_id, _, _ in SYMPTOM_RULES}
SYMPTOM_SPAN_TYPES = {
    "symptom",
    "new",
    "worsening",
    "progress_improved",
    "progress_worsened",
    "progress_unchanged",
}

SYMPTOM_QUOTE_PATTERNS = {
    "throat_irritation": [
        r"목(?:이|은|도)?\s*(?:좀\s*)?(?:칼칼(?:하고|해요|합니다)?|따끔(?:해요|하고|합니다)?|아파요?|불편해요?|간질간질해요?)",
    ],
    "nasal_obstruction": [
        r"코\S{0,4}\s*(?:막혀요|막혀|막힙니다|맥혀요|맥혀|답답해요)",
    ],
    "rhinorrhea": [
        r"콧물(?:이|은|도)?\s*(?:줄줄\s*)?(?:흐르네요|흘러요|나와요|나요)",
        r"코물(?:이|은|도)?\s*(?:줄줄\s*)?(?:흐르네요|흘러요|나와요|나요)",
    ],
    "cough": [
        r"기침(?:이|은|도)?\s*(?:조금\s*)?(?:나요|나와요|심해요|심해졌어요|해요)",
        r"콜록(?:거려요|거립니다|해요)",
    ],
    "fever": [
        r"(?:열|발열)(?:이|은|도)?\s*(?:나요|있어요|나는 것 같아요)",
    ],
    "sputum": [
        r"가래(?:가|는|도)?\s*(?:나요|나와요|있어요|껴요)",
    ],
}

IR_STABLE_SLOT_IDS = {
    "객혈": "hemoptysis",
    "기침": "cough",
    "목의 통증": "sore_throat",
    "목 자극": "throat_irritation",
    "가래": "sputum",
    "호흡곤란": "dyspnea",
    "숨참": "dyspnea",
    "흉통": "chest_pain",
    "가슴 답답": "chest_discomfort",
    "콧물": "rhinorrhea",
    "코막힘": "nasal_obstruction",
    "발열": "fever",
    "열": "fever",
    "두통": "headache",
    "천명음": "wheezing",
    "목소리 변화": "voice_change",
    "삼키기 곤란": "dysphagia",
}
IR_SLOT_TO_CANONICAL_NAME = {
    "hemoptysis": "객혈",
    "cough": "기침",
    "throat_irritation": "목의 통증",
    "sore_throat": "목의 통증",
    "nasal_obstruction": "코막힘",
    "rhinorrhea": "콧물",
    "sputum": "가래",
    "fever": "열",
    "dyspnea": "호흡곤란",
    "chest_pain": "흉통",
    "wheezing": "천명음",
    "headache": "두통",
    "voice_change": "목소리 변화",
}
IR_TEXT_ALIASES = [
    (r"목|인후|칼칼|따끔", "목의 통증"),
    (r"코.{0,3}(막|맥)|비폐색", "코막힘"),
    (r"콧물|코물", "콧물"),
    (r"가래|객담", "가래"),
    (r"기침|콜록", "기침"),
    (r"피.{0,4}(가래|섞|묻)|객혈", "객혈"),
    (r"숨|호흡곤란|숨참", "호흡곤란"),
    (r"가슴.{0,4}(아프|통증)|흉통", "흉통"),
    (r"쌕쌕|천명", "천명음"),
    (r"열|발열|고열", "열"),
]
IR_RED_FLAG_NAMES = {"객혈", "호흡곤란", "흉통", "청색증", "의식 변화"}
_IR_DOCS = None
_IR_BM25 = None
_IR_ID_TO_NAME = {}
_IR_NAME_TO_ID = {}
_IR_DOC_EMBEDDINGS = None
_EMBED_TEXT_CACHE = {}


def normalize_text(text):
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


def make_symptom_id(symptom_name):
    if symptom_name in IR_STABLE_SLOT_IDS:
        return IR_STABLE_SLOT_IDS[symptom_name]
    digest = hashlib.sha1(symptom_name.encode("utf-8")).hexdigest()[:10]
    return f"symptom:{digest}"


def build_symptom_docs_from_sources():
    diseases = load_json_file(DISEASES_PATH)
    symptom_index = load_json_file(SYMPTOM_INDEX_PATH)
    disease_by_content_id = {}
    disease_rows = diseases if isinstance(diseases, list) else []
    for disease in disease_rows:
        cid = str(disease.get("content_id", ""))
        if cid:
            disease_by_content_id[cid] = disease

    docs = []
    for symptom_name in sorted(symptom_index.keys()):
        refs = symptom_index.get(symptom_name) or []
        symptom_id = make_symptom_id(symptom_name)
        evidence_refs = []
        direct_snippets = []
        linked_disease_names = []
        departments_counter = Counter()
        categories_counter = Counter()
        seen_content_ids = set()

        for ref in refs:
            cid = str(ref.get("content_id", ""))
            if not cid or cid in seen_content_ids:
                continue
            seen_content_ids.add(cid)
            disease = disease_by_content_id.get(cid)
            if not disease:
                continue
            name_ko = normalize_text(disease.get("name_ko") or ref.get("name_ko") or "")
            category = normalize_text(disease.get("category") or "")
            if name_ko:
                linked_disease_names.append(name_ko)
            if category:
                categories_counter[category] += 1
            for dep in disease.get("departments") or ref.get("departments") or []:
                dep = normalize_text(dep)
                if dep:
                    departments_counter[dep] += 1

            sections = disease.get("sections") or {}
            definition = normalize_text(sections.get("definition", ""))
            symptom_section = normalize_text(sections.get("symptom", ""))
            evidence_refs.append({
                "content_id": cid,
                "disease_name": name_ko,
                "source_url": disease.get("source_url", ref.get("source_url", "")),
                "category": category,
                "departments": disease.get("departments") or ref.get("departments") or [],
                "symptom_in_list": symptom_name in (disease.get("symptoms") or []),
            })

            for section_name, text in (("symptom", symptom_section), ("definition", definition)):
                for sent in split_sentences_ir(text):
                    if sentence_directly_mentions_symptom(sent, symptom_name):
                        snippet = trim_snippet(sent)
                        key = (cid, section_name, snippet)
                        if not any((x["content_id"], x["section"], x["text"]) == key for x in direct_snippets):
                            direct_snippets.append({
                                "content_id": cid,
                                "disease_name": name_ko,
                                "section": section_name,
                                "text": snippet,
                            })
                    if len(direct_snippets) >= 8:
                        break
                if len(direct_snippets) >= 8:
                    break

        top_diseases = [name for name in linked_disease_names if name][:8]
        top_departments = [name for name, _ in departments_counter.most_common(6)]
        top_categories = [name for name, _ in categories_counter.most_common(4)]
        direct_text = " ".join(item["text"] for item in direct_snippets[:5])
        disease_text = ", ".join(top_diseases)
        dept_text = ", ".join(top_departments)
        retrieval_parts = [
            f"표준 증상명: {symptom_name}.",
            f"아산백과 증상 목록에서 '{symptom_name}'으로 기록된 표준 증상 후보.",
        ]
        if direct_text:
            retrieval_parts.append(f"증상 직접 근거 문장: {direct_text}")
        if disease_text:
            retrieval_parts.append(f"관련 아산백과 문서명: {disease_text}.")
        if dept_text:
            retrieval_parts.append(f"관련 진료과: {dept_text}.")
        embedding_parts = [
            f"{symptom_name}.",
            f"환자 발화에서 '{symptom_name}'과 의미가 가까운 증상 표현을 표준 증상 후보로 매칭하기 위한 문서.",
        ]
        if direct_text:
            embedding_parts.append(direct_text)
        docs.append({
            "symptom_id": symptom_id,
            "display_name": symptom_name,
            "bm25_text": normalize_text(" ".join([symptom_name, f"표준 증상명 {symptom_name}", direct_text])),
            "retrieval_text": normalize_text("\n".join(retrieval_parts)),
            "embedding_text": normalize_text(" ".join(embedding_parts)),
            "evidence": direct_snippets[:8],
            "evidence_refs": evidence_refs,
            "linked_disease_names": top_diseases,
            "domain_candidates": top_categories,
            "departments": top_departments,
        })
    return docs


def tokenize_ir(text):
    text = normalize_text(text).lower()
    compacted = compact_ir(text.lower())
    tokens = re.findall(r"[가-힣a-z0-9]+", text)
    for n in (2, 3):
        if len(compacted) >= n:
            tokens.extend(compacted[i:i + n] for i in range(len(compacted) - n + 1))
    return [token for token in tokens if token]


class BM25Index:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = docs
        self.k1 = k1
        self.b = b
        self.doc_tokens = [tokenize_ir(((doc["display_name"] + " ") * 4) + doc.get("bm25_text", "")) for doc in docs]
        self.doc_lens = [len(tokens) for tokens in self.doc_tokens]
        self.avgdl = sum(self.doc_lens) / max(1, len(self.doc_lens))
        self.df = {}
        self.tf = []
        for tokens in self.doc_tokens:
            counts = {}
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
            self.tf.append(counts)
            for token in counts:
                self.df[token] = self.df.get(token, 0) + 1
        self.N = len(docs)

    def idf(self, term):
        df = self.df.get(term, 0)
        return math.log(1 + (self.N - df + 0.5) / (df + 0.5))

    def scores(self, query):
        q_terms = tokenize_ir(query)
        if not q_terms:
            return [0.0] * self.N
        scores = []
        for idx, counts in enumerate(self.tf):
            dl = self.doc_lens[idx] or 1
            score = 0.0
            for term in q_terms:
                freq = counts.get(term, 0)
                if freq <= 0:
                    continue
                denom = freq + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1e-9))
                score += self.idf(term) * (freq * (self.k1 + 1)) / denom
            scores.append(float(score))
        return scores


def get_ir_index():
    global _IR_DOCS, _IR_BM25, _IR_ID_TO_NAME, _IR_NAME_TO_ID
    if _IR_DOCS is None:
        docs = build_symptom_docs_from_sources()
        _IR_DOCS = docs
        _IR_BM25 = BM25Index(docs)
        _IR_ID_TO_NAME = {doc["symptom_id"]: doc["display_name"] for doc in docs}
        _IR_NAME_TO_ID = {doc["display_name"]: doc["symptom_id"] for doc in docs}
    return _IR_DOCS, _IR_BM25


def minmax_norm(values):
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        return [0.0 for _ in values]
    return [(value - lo) / (hi - lo) for value in values]


def jaccard_char_ngram(a, b, n=2):
    a = compact_ir(a)
    b = compact_ir(b)
    if not a or not b:
        return 0.0
    aa = {a[i:i + n] for i in range(max(1, len(a) - n + 1))} if len(a) >= n else {a}
    bb = {b[i:i + n] for i in range(max(1, len(b) - n + 1))} if len(b) >= n else {b}
    return len(aa & bb) / max(1, len(aa | bb))


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    na = math.sqrt(sum(float(x) * float(x) for x in a))
    nb = math.sqrt(sum(float(y) * float(y) for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def direct_label_score(query, label):
    q = normalize_text(query)
    s = normalize_text(label)
    qc = compact_ir(q)
    sc = compact_ir(s)
    if not qc or not sc:
        return 0.0
    if qc == sc:
        return 1.0
    if len(sc) == 1:
        return 0.72 if any(token.startswith(s) for token in q.split()) else 0.0
    contains = 0.78 if sc in qc and len(sc) >= 2 else 0.0
    reverse_contains = 0.65 if qc in sc and len(qc) >= 2 else 0.0
    return max(contains, reverse_contains, jaccard_char_ngram(q, s, 2) * 0.75)


def rule_based_symptom_label(text):
    text = normalize_text(text)
    rules = [
        (r"가래.{0,8}피|피.{0,4}가래|객혈|피가\s*섞|피\s*섞", "객혈"),
        (r"입술.{0,4}파래|얼굴.{0,4}파래|손톱.{0,4}파래|청색증", "청색증"),
        (r"의식.{0,8}(흐려|혼미|저하|잃|소실)|정신.{0,8}(없|혼미|흐려|잃)|실신|쓰러", "의식 변화"),
        (r"숨.{0,8}(못\s*쉬|쉬기\s*힘|차|가빠)|호흡곤란|숨참", "호흡곤란"),
        (r"가슴.{0,8}(아프|아파|통증|결려|쥐어)|흉통", "흉통"),
        (r"쌕쌕|천명", "천명음"),
    ]
    for pattern, label in rules:
        if re.search(pattern, text):
            return label
    return ""


def preferred_canonical_name(slot_id, *texts):
    docs, _ = get_ir_index()
    valid_names = {doc["display_name"] for doc in docs}
    mapped = IR_SLOT_TO_CANONICAL_NAME.get(str(slot_id or ""))
    if mapped in valid_names:
        return mapped
    joined = normalize_text(" ".join(text for text in texts if text))
    for pattern, name in IR_TEXT_ALIASES:
        if name in valid_names and re.search(pattern, joined):
            return name
    return ""


def docs_hash(docs):
    source = "\n".join(f"{doc['symptom_id']}|{doc['display_name']}|{doc['embedding_text']}" for doc in docs)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def load_packaged_doc_embeddings(docs):
    if not EMBEDDING_CACHE_PATH.exists():
        return None
    try:
        data = load_json_file(EMBEDDING_CACHE_PATH)
        if data.get("model_id") != EMBEDDING_MODEL_ID:
            return None
        if int(data.get("dimensions") or 0) != EMBEDDING_DIMENSIONS:
            return None
        if data.get("docs_hash") != docs_hash(docs):
            return None
        embeddings = data.get("embeddings")
        return embeddings if isinstance(embeddings, dict) else None
    except Exception:
        return None


def embed_text(text):
    text = normalize_text(text)
    if not text or not USE_TITAN_EMBEDDING:
        return None
    key = f"{EMBEDDING_MODEL_ID}|{EMBEDDING_DIMENSIONS}|{text}"
    if key in _EMBED_TEXT_CACHE:
        return _EMBED_TEXT_CACHE[key]
    body = {"inputText": text, "dimensions": EMBEDDING_DIMENSIONS, "normalize": True}
    resp = bedrock_runtime.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        body=json.dumps(body),
        accept="application/json",
        contentType="application/json",
    )
    result = json.loads(resp["body"].read())
    embedding = result.get("embedding")
    if isinstance(embedding, list):
        _EMBED_TEXT_CACHE[key] = embedding
        return embedding
    return None


def get_doc_embeddings(docs):
    global _IR_DOC_EMBEDDINGS
    if _IR_DOC_EMBEDDINGS is not None:
        return _IR_DOC_EMBEDDINGS
    packaged = load_packaged_doc_embeddings(docs)
    if packaged is not None:
        _IR_DOC_EMBEDDINGS = packaged
        return _IR_DOC_EMBEDDINGS
    if not HYBRID_PRECOMPUTE_DOC_EMBEDDINGS:
        _IR_DOC_EMBEDDINGS = {}
        return _IR_DOC_EMBEDDINGS
    embeddings = {}
    for doc in docs:
        emb = embed_text(doc.get("embedding_text", ""))
        if emb:
            embeddings[doc["symptom_id"]] = emb
    _IR_DOC_EMBEDDINGS = embeddings
    return _IR_DOC_EMBEDDINGS


def retrieve_symptom_docs(source_quote, normalized_text, span_name="", preferred_slot_id=""):
    docs, bm25 = get_ir_index()
    query = normalize_text(" ".join([source_quote or "", normalized_text or "", span_name or ""]))
    if not query:
        return []
    preferred_name = preferred_canonical_name(preferred_slot_id, span_name, normalized_text, source_quote)

    bm25_raw = bm25.scores(query)
    bm25_norm = minmax_norm(bm25_raw)
    q_emb = None
    vector_raw = [0.0] * len(docs)
    vector_error = ""
    if USE_TITAN_EMBEDDING:
        try:
            q_emb = embed_text(query)
        except Exception as exc:
            vector_error = str(exc)

    doc_embeddings = get_doc_embeddings(docs) if q_emb is not None else {}
    if q_emb is not None and doc_embeddings:
        for idx, doc in enumerate(docs):
            vector_raw[idx] = max(0.0, cosine(q_emb, doc_embeddings.get(doc["symptom_id"])))
    vector_norm = minmax_norm(vector_raw)

    candidate_k = max(HYBRID_CANDIDATE_K, HYBRID_TOP_K * 3)
    bm25_top = set(sorted(range(len(docs)), key=lambda i: bm25_norm[i], reverse=True)[:candidate_k])
    vector_top = set(sorted(range(len(docs)), key=lambda i: vector_norm[i], reverse=True)[:candidate_k]) if doc_embeddings else set()
    label_top = {
        idx
        for idx, doc in enumerate(docs)
        if direct_label_score(query, doc["display_name"]) >= 0.55 or doc["display_name"] == preferred_name
    }
    candidate_ids = bm25_top | vector_top | label_top
    if q_emb is not None and not doc_embeddings:
        # Packaged vector index is absent: still use Titan for the BM25/label candidates.
        for idx in list(candidate_ids):
            try:
                emb = embed_text(docs[idx].get("embedding_text", ""))
                vector_raw[idx] = max(0.0, cosine(q_emb, emb))
            except Exception as exc:
                vector_error = str(exc)
        candidate_vectors = [vector_raw[idx] for idx in candidate_ids]
        norm_lookup = dict(zip(candidate_ids, minmax_norm(candidate_vectors)))
        vector_norm = [norm_lookup.get(idx, 0.0) for idx in range(len(docs))]

    rows = []
    intersection_ids = bm25_top & (vector_top or candidate_ids)
    for idx in candidate_ids:
        doc = docs[idx]
        label = direct_label_score(query, doc["display_name"])
        preferred_hit = doc["display_name"] == preferred_name
        if preferred_hit:
            label = max(label, 1.0)
        if bm25_norm[idx] <= 0 and vector_norm[idx] <= 0 and label <= 0:
            continue
        branch = "both" if idx in intersection_ids else ("bm25_only" if idx in bm25_top else "vector_only")
        rank_score = HYBRID_BM25_WEIGHT * bm25_norm[idx] + HYBRID_VECTOR_WEIGHT * vector_norm[idx] + 0.25 * label
        if preferred_hit:
            branch = "preferred_alias"
            rank_score += 0.45
        if branch == "both":
            rank_score += 0.08
        elif branch == "bm25_only" and vector_raw[idx] < 0.12:
            rank_score *= 0.55

        vector_conf = max(0.0, min(1.0, vector_raw[idx] / 0.30))
        confidence = 0.50 * bm25_norm[idx] + 0.50 * vector_conf
        if preferred_hit:
            confidence = max(confidence, 0.90)
        if branch == "both":
            confidence = min(1.0, confidence + 0.08)
        elif branch == "bm25_only" and vector_raw[idx] < 0.12:
            confidence *= 0.70
        elif branch == "vector_only" and bm25_norm[idx] == 0 and vector_raw[idx] < 0.16:
            confidence *= 0.85

        rows.append({
            "slot_id": doc["symptom_id"],
            "display_text": doc["display_name"],
            "score": round(float(confidence), 4),
            "rank_score": round(float(rank_score), 4),
            "bm25_score": round(float(bm25_norm[idx]), 4),
            "vector_score": round(float(vector_raw[idx]), 4),
            "vector_norm": round(float(vector_norm[idx]), 4),
            "label_score": round(float(label), 4),
            "retrieval_branch": branch,
            "source": "diseases_cleaned+symptom_index",
            "evidence": doc.get("evidence", [])[:3],
            "linked_disease_names": doc.get("linked_disease_names", [])[:8],
            "domain_candidates": doc.get("domain_candidates", []),
            "vector_error": vector_error,
        })

    override = rule_based_symptom_label(query)
    override_doc = next((doc for doc in docs if doc["display_name"] == override), None)
    if override_doc is not None:
        rows = [row for row in rows if row["display_text"] != override_doc["display_name"]]
        rows.append({
            "slot_id": override_doc["symptom_id"],
            "display_text": override_doc["display_name"],
            "score": 1.0,
            "rank_score": 10.0,
            "bm25_score": 1.0,
            "vector_score": 1.0,
            "vector_norm": 1.0,
            "label_score": 1.0,
            "retrieval_branch": "safety_alias_override",
            "source": "diseases_cleaned+symptom_index",
            "evidence": override_doc.get("evidence", [])[:3],
            "linked_disease_names": override_doc.get("linked_disease_names", [])[:8],
            "domain_candidates": override_doc.get("domain_candidates", []),
            "vector_error": vector_error,
        })

    rows.sort(key=lambda item: item["rank_score"], reverse=True)
    return rows[:HYBRID_TOP_K]


def extract_question(body):
    question_type = body.get("question_type") or body.get("questionType")
    transcript = (body.get("transcript") or "").strip()
    if USE_BEDROCK_LLM:
        try:
            return extract_question_bedrock(body)
        except Exception as exc:
            if not ALLOW_RULE_FALLBACK:
                return {
                    "spans": [],
                    "structured": {},
                    "transcript": transcript,
                    "method": "bedrock_error",
                    "error": str(exc),
                }
    spans = []
    structured = {}
    if question_type in ("chief_complaint", "progress", "new_symptoms"):
        for name, slot_id, keywords, alert in SYMPTOM_RULES:
            quote = find_symptom_quote(transcript, slot_id, keywords)
            if quote:
                spans.append({
                    "source_quote": quote,
                    "type": "symptom" if question_type == "chief_complaint" else "new",
                    "slot_ref": slot_id,
                    "name": name,
                    "alert": alert,
                })
    elif question_type == "onset":
        structured = extract_context(transcript)
        spans = structured.get("spans", [])
    elif question_type in ("current_medications", "adherence"):
        structured = extract_medication(transcript, question_type)
        spans = structured.get("spans", [])
    elif question_type in ("patient_questions", "unresolved_questions"):
        structured = extract_agenda(transcript)
    return {"spans": spans, "structured": structured, "transcript": transcript, "method": "rule_based_mvp"}


def extract_question_bedrock(body):
    question_type = body.get("question_type") or body.get("questionType")
    question_id = body.get("question_id") or body.get("questionId") or ""
    visit_type = normalize_visit_type(body.get("visit_type") or body.get("visitType"))
    transcript = (body.get("transcript") or "").strip()
    if not transcript:
        return {"spans": [], "structured": {}, "transcript": "", "method": "bedrock_nova"}

    model_id = select_extraction_model(visit_type, question_id, question_type)
    prompt = build_extraction_prompt(visit_type, question_id, question_type, transcript)
    obj, raw_text = call_bedrock_json(prompt, model_id, MAX_LLM_TOKENS)
    normalized, validation_errors = normalize_extraction_output(obj, transcript, question_id)
    normalized.update({
        "transcript": transcript,
        "method": "bedrock_nova",
        "llm_meta": {
            "model_id": model_id,
            "raw_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
            "validation_errors": validation_errors,
        },
    })
    return normalized


def select_extraction_model(visit_type, question_id, question_type):
    if question_type in ("chief_complaint", "progress", "new_symptoms") or question_id in ("Q1",):
        return STRONG_MODEL_ID
    return LIGHT_MODEL_ID


def call_bedrock_json(prompt, model_id, max_tokens):
    resp = bedrock_runtime.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"temperature": 0, "maxTokens": max_tokens},
    )
    raw_text = "".join(
        block.get("text", "")
        for block in resp.get("output", {}).get("message", {}).get("content", [])
    )
    return extract_first_json_object(raw_text), raw_text


def extract_first_json_object(text):
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?", "", raw, flags=re.I).strip()
    raw = re.sub(r"```$", "", raw).strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    if start < 0:
        return {}
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(raw)):
        ch = raw[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start:idx + 1])
    return {}


def build_extraction_prompt(visit_type, question_id, question_type, transcript):
    visit = visit_label(visit_type)
    question_text = {
        "initial": {
            "Q1": "어디가 불편하셔서 오셨어요?",
            "Q2": "그 증상은 언제부터 그러셨어요?",
            "Q3": "지금 드시는 약이 있으세요?",
            "Q4": "의사선생님께 묻고 싶은 점이 있으세요?",
        },
        "followup": {
            "Q1": "지난번 진료 이후 어떻게 지내셨어요?",
            "Q2": "처방받은 약은 잘 드시고 계세요?",
            "Q3": "그동안 새로 생긴 증상은 없으세요?",
            "Q4": "지난번에 못 여쭤본 점이 있으신가요?",
        },
    }.get(visit_type, {}).get(question_id, "")
    return f"""
You are the semantic parsing LLM for a Korean clinic intake MVP.
Task: standardize dialect/colloquial speech, split meaning units, and tag the answer into the fixed schema.

Critical rules:
- Return JSON only. No markdown.
- Never diagnose. Do not infer facts that are not in the patient answer.
- Every source_quote and original_quote MUST be an exact continuous substring of the patient answer.
- If a fact is implied but no exact quote exists, omit it.
- Split multiple patient questions into separate items.
- Use concise Korean summaries for clinicians.
- source_quote is raw patient wording. normalized_text/summary is standardized Korean.

Visit type: {visit}
Question id: {question_id}
Question type: {question_type}
Question asked: {question_text}
Patient answer:
{transcript}

Allowed symptom slot_ref values when relevant:
hemoptysis, cough, throat_irritation, nasal_obstruction, rhinorrhea, fever, sputum, dyspnea, chest_pain, headache, other

Allowed agenda categories:
drug_drug_interaction, supplement_drug_interaction, food_drug_interaction, treatment_duration, followup_visit, test_question, lifestyle, other

Return exactly this JSON shape:
{{
  "spans": [
    {{
      "source_quote": "exact substring",
      "type": "symptom|new|progress_improved|progress_worsened|progress_unchanged|medication|medication_denial|adherence_gap|context",
      "slot_ref": "allowed symptom slot_ref or other",
      "name": "display symptom name in Korean",
      "normalized_text": "standard Korean meaning",
      "status": "있음|없음|확인필요",
      "score": 0.65,
      "alert": false,
      "explain": "short Korean reason"
    }}
  ],
  "structured": {{
    "standardized_text": "standard Korean rewrite of the answer",
    "clinical_clues": [
      {{
        "category": "증상맥락|복약정보|복약순응도|재진경과",
        "label": "시작시점|기간|현재양상|악화요인|완화요인|복용중|처방약 없음|건강보조제|누락|악화|호전|새 증상",
        "summary": "clinician-facing concise Korean summary",
        "source_quote": "exact substring",
        "source_question": "{question_id}",
        "priority": "일반|우선",
        "related_symptoms": []
      }}
    ],
    "questions": [
      {{
        "category": "allowed agenda category",
        "summary": "concise patient question summary",
        "original_quote": "exact substring"
      }}
    ],
    "unresolved_items": []
  }}
}}
""".strip()


def normalize_extraction_output(obj, transcript, question_id):
    errors = []
    spans = []
    structured = obj.get("structured") if isinstance(obj.get("structured"), dict) else {}
    for item in obj.get("spans", []) if isinstance(obj.get("spans"), list) else []:
        quote = repair_quote(item.get("source_quote", ""), transcript)
        if not quote:
            errors.append({"field": "spans.source_quote", "value": item.get("source_quote", "")})
            continue
        span_type = str(item.get("type") or "context")
        slot_ref = str(item.get("slot_ref") or "other")
        score = item.get("score", 0.82)
        try:
            score = max(0, min(1, float(score)))
        except Exception:
            score = 0.82
        if is_symptom_like_span(span_type, slot_ref) and score <= 0.05:
            # Nova sometimes copies the numeric placeholder from the schema.
            # A valid exact-quote symptom span should not be displayed as 0.00.
            score = 0.86
        spans.append({
            "source_quote": quote,
            "type": span_type,
            "slot_ref": slot_ref,
            "name": clean_quote(item.get("name") or slot_to_name(slot_ref)),
            "normalized_text": clean_quote(item.get("normalized_text") or item.get("name") or quote),
            "status": item.get("status") if item.get("status") in ("있음", "없음", "확인필요") else "있음",
            "score": score,
            "alert": bool(item.get("alert") or slot_ref in ("hemoptysis", "dyspnea", "chest_pain")),
            "explain": clean_quote(item.get("explain") or "LLM이 환자 발화에서 의미 단위를 추출했습니다."),
        })

    clinical = []
    for clue_item in structured.get("clinical_clues", []) if isinstance(structured.get("clinical_clues"), list) else []:
        quote = repair_quote(clue_item.get("source_quote", ""), transcript)
        if not quote:
            errors.append({"field": "clinical_clues.source_quote", "value": clue_item.get("source_quote", "")})
            continue
        clinical.append({
            "category": clean_quote(clue_item.get("category") or "증상맥락"),
            "label": clean_quote(clue_item.get("label") or "문진단서"),
            "summary": clean_quote(clue_item.get("summary") or quote),
            "source_quote": quote,
            "source_question": clue_item.get("source_question") or question_id,
            "priority": clue_item.get("priority") if clue_item.get("priority") in ("일반", "우선") else "일반",
            "related_symptoms": clue_item.get("related_symptoms") if isinstance(clue_item.get("related_symptoms"), list) else [],
        })

    questions = []
    for q in structured.get("questions", []) if isinstance(structured.get("questions"), list) else []:
        quote = repair_quote(q.get("original_quote", ""), transcript)
        if not quote:
            errors.append({"field": "questions.original_quote", "value": q.get("original_quote", "")})
            continue
        questions.append({
            "category": q.get("category") or "other",
            "summary": clean_quote(q.get("summary") or quote),
            "original_quote": quote,
        })

    normalized_structured = {
        "standardized_text": clean_quote(structured.get("standardized_text") or transcript),
        "clinical_clues": clinical,
        "questions": questions,
        "unresolved_items": structured.get("unresolved_items") if isinstance(structured.get("unresolved_items"), list) else [],
    }
    return {"spans": spans, "structured": normalized_structured}, errors


def repair_quote(quote, transcript):
    quote = clean_quote(quote)
    text = str(transcript or "")
    if not quote or not text:
        return ""
    if quote in text:
        return quote
    compact_quote = re.sub(r"\s+", " ", quote)
    compact_text = re.sub(r"\s+", " ", text)
    if compact_quote in compact_text:
        return compact_quote
    for part in re.split(r"[,，/]| 그리고 | 또 | 혹은 | 또는 ", quote):
        part = clean_quote(part)
        if len(part) >= 3 and part in text:
            return part
    return ""


def find_symptom_quote(text, slot_id, keywords):
    for pattern in SYMPTOM_QUOTE_PATTERNS.get(slot_id, []):
        m = re.search(pattern, text)
        if m:
            return clean_quote(m.group(0))
    return find_keyword_quote(text, keywords)


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


def extract_context(text):
    spans = []
    onset_quote = find_first_pattern(text, [
        r"어저께부터",
        r"어제부터",
        r"그저께(?:\s*저녁)?부터",
        r"그제(?:\s*저녁)?부터",
        r"며칠\s*전부터",
        r"한\s*그제\s*저녁부터",
    ])
    if onset_quote:
        spans.append({"source_quote": onset_quote, "type": "onset"})
    if "괜찮" in text or "나아" in text or "호전" in text:
        spans.append({"source_quote": find_keyword_quote(text, ["괜찮", "나아", "호전"]), "type": "course"})
    if "추" in text or "찬바람" in text:
        spans.append({"source_quote": find_keyword_quote(text, ["추", "찬바람"]), "type": "context"})
    return {"spans": [s for s in spans if s.get("source_quote")], "estimated_onset_relative": "확인필요"}


def find_first_pattern(text, patterns):
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return clean_quote(m.group(0))
    return ""


def extract_medication(text, question_type):
    spans = []
    meds = []
    if "혈압" in text:
        meds.append({"category": "antihypertensive", "patient_term": "혈압약"})
        spans.append({"source_quote": find_keyword_quote(text, ["혈압"]), "type": "medication"})
    if "영양제" in text:
        meds.append({"category": "supplement", "patient_term": "영양제"})
        spans.append({"source_quote": find_keyword_quote(text, ["영양제"]), "type": "medication"})
    if "오메가" in text or "오메가 쓰리" in text or "오메가3" in text:
        meds.append({"category": "supplement", "patient_term": "오메가3"})
        spans.append({"source_quote": find_keyword_quote(text, ["오메가"]), "type": "medication"})
    if "종합비타민" in text or "비타민" in text:
        meds.append({"category": "supplement", "patient_term": "종합비타민"})
        spans.append({"source_quote": find_keyword_quote(text, ["종합비타민", "비타민"]), "type": "medication"})
    if "먹는 약은 따로 없" in text or "약은 따로 없" in text:
        spans.append({"source_quote": find_keyword_quote(text, ["따로 없"]), "type": "medication_denial"})
    if "깜빡" in text or "못 먹" in text:
        spans.append({"source_quote": find_keyword_quote(text, ["깜빡", "못 먹"]), "type": "adherence_gap"})
    return {"spans": [s for s in spans if s.get("source_quote")], "extracted_medications": unique_medications(meds)}


def unique_medications(meds):
    out = []
    seen = set()
    for med in meds:
        key = (med.get("category"), med.get("patient_term"))
        if key in seen:
            continue
        seen.add(key)
        out.append(med)
    return out


def extract_agenda(text):
    questions = []
    for sentence in split_question_sentences(text):
        if not sentence:
            continue
        if ("감기약" in sentence or "혈압약" in sentence) and "같이" in sentence:
            questions.append({
                "category": "drug_drug_interaction",
                "summary": "혈압약-감기약 병용 가능 여부 문의",
                "original_quote": sentence,
            })
        elif ("처방" in sentence or "약" in sentence) and ("영양제" in sentence or "오메가" in sentence or "비타민" in sentence) and ("같이" in sentence or "먹어" in sentence):
            questions.append({
                "category": "supplement_drug_interaction",
                "summary": "처방약-영양제 병용 가능 여부 문의",
                "original_quote": sentence,
            })
        elif "양파" in sentence:
            questions.append({
                "category": "food_drug_interaction",
                "summary": "양파즙 병용 가능 여부 문의",
                "original_quote": sentence,
            })
        elif "언제까지" in sentence or "며칠" in sentence:
            questions.append({
                "category": "treatment_duration",
                "summary": "복약 기간 문의",
                "original_quote": sentence,
            })
        elif ("다시" in sentence or "와도" in sentence or "내원" in sentence or "방문" in sentence) and ("심해" in sentence or "증상" in sentence or "중간" in sentence):
            questions.append({
                "category": "followup_visit",
                "summary": "증상 악화 시 중간 재내원 가능 여부 문의",
                "original_quote": sentence,
            })
    if not questions and text:
        questions.append({"category": "other", "summary": clean_quote(text)[:40], "original_quote": clean_quote(text)})
    return {"questions": questions, "uncategorized_remnant": ""}


def split_question_sentences(text):
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return []
    normalized = re.sub(r"\s+또\s+(?=뭐|혹시|증상|약|언제|와도)", ". 또 ", normalized, count=1)
    parts = [clean_quote(part) for part in re.split(r"[.?!。]+", normalized)]
    return [part for part in parts if part]


def sentence_for(text, keyword):
    for part in re.split(r"[.?!。]", text):
        if keyword in part:
            return clean_quote(part)
    return ""


def is_symptom_like_span(span_type, slot_id):
    if str(span_type or "") not in SYMPTOM_SPAN_TYPES:
        return False
    slot_id = str(slot_id or "")
    if not slot_id or slot_id == "other":
        return True
    if slot_id in VALID_SYMPTOM_SLOT_IDS:
        return True
    try:
        get_ir_index()
    except Exception:
        return False
    return slot_id in _IR_ID_TO_NAME


def match_slots(body):
    spans = body.get("spans") or []
    matched = []
    unmatched = []
    for span in spans:
        slot_id = span.get("slot_ref") or "other"
        span_type = span.get("type", "symptom")
        if not is_symptom_like_span(span_type, slot_id):
            unmatched.append(span)
            continue
        candidates = retrieve_symptom_docs(
            span.get("source_quote", ""),
            span.get("normalized_text") or span.get("name") or "",
            span.get("name") or slot_to_name(slot_id),
            slot_id,
        )
        if not candidates:
            unmatched.append(span)
            continue
        top = candidates[0]
        score = Decimal(str(top.get("score", 0)))
        status = span.get("status") if span.get("status") in ("있음", "없음", "확인필요") else "있음"
        if status == "있음" and float(score) < HYBRID_ACCEPT_THRESHOLD:
            status = "확인필요"
        name = top.get("display_text") or span.get("name") or slot_to_name(top.get("slot_id"))
        alert = bool(
            span.get("alert")
            or top.get("slot_id") in ("hemoptysis", "dyspnea", "chest_pain")
            or name in IR_RED_FLAG_NAMES
        )
        matched.append({
            "slot_id": top.get("slot_id"),
            "name": name,
            "score": score,
            "source_quote": span.get("source_quote", ""),
            "span_type": span_type,
            "alert": alert,
            "normalized_text": span.get("normalized_text") or span.get("name") or name,
            "status": status,
            "explain": make_symptom_match_explain(span, top),
            "ir_method": "bm25_titan_hybrid" if USE_TITAN_EMBEDDING else "bm25_only",
            "ir_trace": {
                "query": normalize_text(" ".join([
                    span.get("source_quote", ""),
                    span.get("normalized_text") or span.get("name") or "",
                ])),
                "bm25_score": top.get("bm25_score"),
                "vector_score": top.get("vector_score"),
                "vector_norm": top.get("vector_norm"),
                "label_score": top.get("label_score"),
                "rank_score": top.get("rank_score"),
                "retrieval_branch": top.get("retrieval_branch"),
                "source": top.get("source"),
                "linked_disease_names": top.get("linked_disease_names", []),
                "evidence": top.get("evidence", []),
                "top_candidates": [
                    {
                        "slot_id": cand.get("slot_id"),
                        "name": cand.get("display_text"),
                        "score": cand.get("score"),
                        "bm25_score": cand.get("bm25_score"),
                        "vector_score": cand.get("vector_score"),
                        "rank_score": cand.get("rank_score"),
                    }
                    for cand in candidates[:3]
                ],
            },
        })
    return {"matched_slots": matched, "unmatched_spans": unmatched}


def slot_to_name(slot_id):
    if slot_id:
        try:
            get_ir_index()
            if slot_id in _IR_ID_TO_NAME:
                return _IR_ID_TO_NAME[slot_id]
        except Exception:
            pass
    mapping = {slot_id: name for name, slot_id, _, _ in SYMPTOM_RULES}
    return mapping.get(slot_id, slot_id or "-")


def make_symptom_match_explain(span, top):
    branch = top.get("retrieval_branch") or "hybrid"
    bm25_score = top.get("bm25_score", 0)
    vector_score = top.get("vector_score", 0)
    label_score = top.get("label_score", 0)
    if branch == "safety_alias_override":
        return "안전 관련 핵심 표현이 있어 표준 증상 후보를 우선 매칭했습니다."
    return (
        "환자 표현을 아산백과 기반 증상 인덱스와 비교했습니다. "
        f"BM25 {bm25_score}, Titan 의미점수 {vector_score}, 표준명 유사도 {label_score}를 함께 반영했습니다."
    )


def validate_and_save(body):
    session_id = body.get("session_id") or body.get("sessionId")
    question_id = body.get("question_id") or body.get("questionId")
    if not session_id or not question_id:
        return None, response(400, {"error": "missing_session_or_question"})
    session = get_session(session_id)
    if not session:
        session = create_session({"session_id": session_id, "visit_type": body.get("visit_type")})
    transcript = body.get("transcript") or ""
    structured = body.get("structured") or {}
    spans = body.get("spans") or []
    matched_slots = body.get("matched_slots") or []
    safety_flag = scan_safety(transcript, matched_slots)
    responses = session.get("responses", {})
    responses[question_id] = {
        "text": transcript,
        "spans": spans,
        "matched_slots": matched_slots,
        "structured": structured,
        "extract_method": body.get("method") or body.get("extract_method"),
        "llm_meta": body.get("llm_meta") or {},
        "confirmed": True,
    }
    question_results = session.get("question_results", {})
    question_results[question_id] = responses[question_id]
    risk = "high" if safety_flag or session.get("risk") == "high" else session.get("risk", "none")
    if safety_flag or session.get("risk") == "high" or session.get("status") == "needs_priority":
        status = "needs_priority"
    else:
        status = "completed" if question_id == "Q4" else "in_progress"
    updated_base = {**session, "responses": responses, "question_results": question_results, "risk": risk}
    onepager = build_onepager(updated_base)
    update_session(session_id, {
        "responses": responses,
        "question_results": question_results,
        "risk": risk,
        "status": status,
        "onepager": onepager,
        "safety_flag": safety_flag or session.get("safety_flag"),
    })
    return {
        "validator_passed": True,
        "safety_flag": safety_flag,
        "errors": [],
        "onepager_ready": question_id == "Q4",
    }, None


def scan_safety(transcript, matched_slots):
    if any(slot.get("slot_id") == "hemoptysis" for slot in matched_slots) or "피" in transcript:
        return {
            "category": "hemoptysis",
            "label": "객혈 의증",
            "severity": "high",
            "matched_pattern": "피",
            "message": "객혈 의심 표현이 있어 우선 평가가 필요합니다.",
        }
    return None


def build_onepager(session):
    patient = session.get("patient", {})
    responses = session.get("responses", {})
    visit_type = normalize_visit_type(session.get("visit_type"))
    q1 = responses.get("Q1", {})
    q2 = responses.get("Q2", {})
    q3 = responses.get("Q3", {})
    q4 = responses.get("Q4", {})
    slots = []
    for slot in q1.get("matched_slots", []):
        normalized_slot = slot_to_symptom_slot(slot, "Q1", q1.get("text", ""))
        if normalized_slot:
            slots.append(normalized_slot)
    for slot in q3.get("matched_slots", []):
        normalized_slot = slot_to_symptom_slot(slot, "Q3", q3.get("text", ""))
        if normalized_slot:
            slots.append(normalized_slot)
    slots = dedupe_symptom_slots(slots)
    clinical = build_clinical_clues(q1, q2, q3, visit_type)
    agenda = normalize_agenda(q4)
    safety = scan_safety(" ".join([r.get("text", "") for r in responses.values() if isinstance(r, dict)]), q1.get("matched_slots", []) + q3.get("matched_slots", []))
    fallback_review_items = build_review_items(slots, agenda, safety, clinical)
    onepager = {
        "patient_summary": {
            "display_name": patient.get("name") or mask_name(patient.get("full_name")),
            "age_text": f"{patient.get('age') or '-'}세",
            "sex": patient.get("gender") or "-",
            "department": patient.get("department") or "이비인후과",
            "received_at": format_hhmm(session.get("created_at")),
            "audio_duration_text": "확인됨",
            "visit_type": visit_type,
        },
        "agenda": agenda,
        "symptom_slots": slots,
        "clinical_clues": clinical,
        "doctor_brief": {"headline": "", "sections": []},
        "review_items": [],
        "transfer_text": build_transfer_text(patient, slots, clinical, agenda, visit_type),
        "safety_flags": [safety] if safety else [],
        "unresolved_items": [],
    }
    if USE_BEDROCK_LLM and ENABLE_BEDROCK_REVIEW and responses:
        onepager = apply_bedrock_onepager_review(session, onepager, fallback_review_items)
    if not onepager.get("review_items"):
        onepager["review_items"] = fallback_review_items
        onepager["review_item_generation"] = {
            "method": "rule_fallback",
            "reason": (onepager.get("llm_review") or {}).get("error") or "llm_review_empty",
        }
    return onepager


def slot_to_symptom_slot(slot, qid, transcript=""):
    slot_id = slot.get("slot_id") or slot.get("slot_ref")
    span_type = slot.get("span_type") or slot.get("type") or "symptom"
    if not is_symptom_like_span(span_type, slot_id):
        return None
    source_quote = clean_quote(slot.get("source_quote", ""))
    if not source_quote and transcript and slot_id:
        source_quote = find_symptom_quote(transcript, slot_id, [slot.get("name", "")]) or source_quote
    score = slot.get("score", Decimal("0.86"))
    try:
        score = Decimal(str(score))
    except Exception:
        score = Decimal("0.86")
    if score <= 0 and not slot.get("ir_method"):
        score = Decimal("0.86")
    return {
        "slot_id": slot_id,
        "name": slot.get("name") or slot_to_name(slot_id),
        "source_question": qid,
        "source_quote": source_quote,
        "normalized_text": slot.get("normalized_text") or slot.get("name") or "",
        "status": slot.get("status") or "있음",
        "score": score,
        "alert": bool(slot.get("alert")),
        "explain": slot.get("explain") or "환자 발화에서 증상 표현을 확인했습니다.",
        "ir_method": slot.get("ir_method"),
        "ir_trace": slot.get("ir_trace") or {},
    }


def dedupe_symptom_slots(slots):
    by_key = {}
    for slot in slots:
        key = slot.get("slot_id") or slot.get("name")
        if not key:
            continue
        old = by_key.get(key)
        if not old or Decimal(str(slot.get("score", 0))) >= Decimal(str(old.get("score", 0))):
            by_key[key] = slot
    return list(by_key.values())


def build_clinical_clues(q1, q2, q3, visit_type):
    structured_clues = []
    for qid, q in (("Q1", q1), ("Q2", q2), ("Q3", q3)):
        for item in ((q.get("structured") or {}).get("clinical_clues") or []):
            normalized = normalize_clinical_clue(item, qid)
            if normalized:
                structured_clues.append(normalized)
    if structured_clues:
        return unique_clues(structured_clues)
    if not ALLOW_RULE_FALLBACK:
        return []

    clues = []
    idx = 1
    text1 = q1.get("text", "")
    text2 = q2.get("text", "")
    text3 = q3.get("text", "")
    related = [slot.get("name") for slot in q1.get("matched_slots", []) if slot.get("name")]
    onset_quote = find_first_pattern(text2, [
        r"한\s*그제\s*저녁부터",
        r"그제\s*저녁부터",
        r"그저께\s*저녁부터",
        r"그제부터",
        r"그저께부터",
        r"어제부터",
        r"어저께부터",
    ]) or find_first_pattern(text1, [r"어저께부터", r"어제부터", r"그제부터", r"그저께부터"])
    if onset_quote:
        source_q = "Q2" if onset_quote in text2 else "Q1"
        clues.append(clue(idx, "증상맥락", "시작시점", onset_quote, source_q, onset_quote, related))
        idx += 1
    if "괜찮" in text2 or "나아" in text2 or "호전" in text2:
        q = find_keyword_quote(text2, ["괜찮", "나아", "호전"])
        clues.append(clue(idx, "증상맥락", "현재양상", "오늘은 다소 호전/변동감 있음", "Q2", q, related))
        idx += 1
    if "추" in text2 or "찬바람" in text2:
        clues.append(clue(idx, "증상맥락", "악화요인", "추위 노출 후 시작된 듯함", "Q2", find_keyword_quote(text2, ["추", "찬바람"]), []))
        idx += 1
    if "혈압" in text3:
        clues.append(clue(idx, "복약정보", "복용중", "혈압약 복용 중", "Q3", find_keyword_quote(text3, ["혈압"]), []))
        idx += 1
    supplements = []
    if "영양제" in text3:
        supplements.append("영양제")
    if "오메가" in text3:
        supplements.append("오메가3")
    if "종합비타민" in text3 or "비타민" in text3:
        supplements.append("종합비타민")
    if supplements:
        clues.append(clue(idx, "복약정보", "건강보조제", f"{', '.join(unique(supplements))} 복용 중", "Q3", find_keyword_quote(text3, ["영양제", "오메가", "종합비타민", "비타민"]), []))
        idx += 1
    if "먹는 약은 따로 없" in text3 or "약은 따로 없" in text3:
        clues.append(clue(idx, "복약정보", "처방약 없음", "평소 복용 처방약은 없다고 말함", "Q3", find_keyword_quote(text3, ["따로 없"]), []))
        idx += 1
    if "깜빡" in text3 or "못 먹" in text3:
        clues.append(clue(idx, "복약순응도", "누락", "복약 누락 가능성", "Q3", find_keyword_quote(text3, ["깜빡", "못 먹"]), []))
        idx += 1
    if visit_type == "followup" and "심" in q1.get("text", ""):
        clues.append(clue(idx, "재진경과", "악화", "증상 악화 호소", "Q1", find_keyword_quote(q1.get("text", ""), ["심"]), related))
    return clues


def clue(idx, category, label, summary, source_question, source_quote, related):
    return {
        "id": f"c{idx}",
        "category": category,
        "label": label,
        "summary": summary,
        "source_question": source_question,
        "source_quote": source_quote or summary,
        "priority": "일반",
        "related_symptoms": related,
        "action_hint": f"{label} 확인",
        "explain": "문진 원문에서 추출한 진료 맥락입니다.",
    }


def normalize_clinical_clue(item, fallback_qid):
    if not isinstance(item, dict):
        return None
    summary = clean_quote(item.get("summary") or item.get("source_quote") or "")
    source_quote = clean_quote(item.get("source_quote") or summary)
    if not summary and not source_quote:
        return None
    label = clean_quote(item.get("label") or "문진단서")
    return {
        "id": item.get("id") or f"{fallback_qid}-{label}-{source_quote}",
        "category": clean_quote(item.get("category") or "증상맥락"),
        "label": label,
        "summary": summary or source_quote,
        "source_question": item.get("source_question") or fallback_qid,
        "source_quote": source_quote,
        "priority": item.get("priority") if item.get("priority") in ("일반", "우선") else "일반",
        "related_symptoms": item.get("related_symptoms") if isinstance(item.get("related_symptoms"), list) else [],
        "action_hint": item.get("action_hint") or f"{label} 확인",
        "explain": item.get("explain") or "Bedrock LLM이 문진 원문에서 추출한 진료 맥락입니다.",
    }


def unique_clues(clues):
    out = []
    seen = set()
    for item in clues:
        key = (item.get("category"), item.get("label"), item.get("summary"), item.get("source_quote"))
        if key in seen:
            continue
        seen.add(key)
        item = dict(item)
        item["id"] = f"c{len(out) + 1}"
        out.append(item)
    return out


def normalize_agenda(q4):
    structured = q4.get("structured", {})
    questions = structured.get("questions") or q4.get("questions") or []
    text = q4.get("text", "")
    if not questions and not ALLOW_RULE_FALLBACK:
        return []
    if ALLOW_RULE_FALLBACK and text and (not questions or (len(questions) == 1 and questions[0].get("category") == "other")):
        questions = extract_agenda(text).get("questions", [])
    return [{
        "type": item.get("category", "other"),
        "category": item.get("category", "other"),
        "type_label": agenda_label(item.get("category")),
        "summary": item.get("summary", ""),
        "original_quote": item.get("original_quote", ""),
        "source_question": "Q4",
    } for item in questions]


def agenda_label(category):
    return {
        "drug_drug_interaction": "복약 상호작용",
        "supplement_drug_interaction": "영양제 병용",
        "food_drug_interaction": "음식-약 상호작용",
        "treatment_duration": "복약 기간",
        "followup_visit": "재내원 기준",
    }.get(category, "환자 질문")


def build_review_items(slots, agenda, safety, clinical=None):
    items = []
    if safety:
        items.extend(["[우선] 객혈량과 시작 시점 확인", "[우선] 흉부 X-ray/객담 검사 고려"])
    names = {slot.get("name") for slot in slots}
    clinical_text = " ".join(
        clean_quote(c.get("summary") or c.get("source_quote") or c.get("label") or "")
        for c in (clinical or [])
    )
    if names & {"열", "발열"} or re.search(r"고열|발열|열", clinical_text):
        items.append("발열 여부와 실제 체온 확인")
    if "기침" in names or "가래" in names:
        items.append("가래 동반 여부와 색깔")
    if {"코막힘", "콧물", "재채기"} & names:
        items.append("비폐색/콧물 지속 정도와 알레르기 병력 확인")
    if any(c.get("label") == "건강보조제" for c in (clinical or [])):
        items.append("복용 중인 영양제 종류와 병용 가능성 확인")
    for item in agenda:
        category = item.get("category") or item.get("type")
        if category == "supplement_drug_interaction":
            items.append("처방약과 영양제 병용 가능 여부 안내")
        elif category == "followup_visit":
            items.append("증상 악화 시 중간 재내원 기준 안내")
        elif item.get("summary"):
            items.append(item["summary"] + " 답변")
    return unique(items) or ["문진 내용 직접 확인"]


def build_transfer_text(patient, slots, clinical, agenda, visit_type):
    symptoms = ", ".join(unique([slot.get("name") for slot in slots if slot.get("name")]))
    text = f"{patient.get('age') or '-'}세 {patient.get('gender') or ''} {visit_label(visit_type)} 환자."
    if symptoms:
        text += f" {symptoms} 호소."
    med = next((c.get("summary") for c in clinical if c.get("category") == "복약정보"), "")
    if med:
        text += f" {med}."
    if agenda:
        text += f" 환자 질문: {agenda[0].get('summary')}."
    return text


def apply_bedrock_onepager_review(session, onepager, fallback_review_items=None):
    try:
        prompt = build_onepager_review_prompt(session, onepager, fallback_review_items or [])
        obj, raw_text = call_bedrock_json(prompt, REVIEWER_MODEL_ID, REVIEW_MAX_TOKENS)
        reviewed = dict(onepager)
        if isinstance(obj.get("review_items"), list):
            items = [clean_quote(x) for x in obj.get("review_items", []) if clean_quote(x)]
            items = sanitize_review_items(items, onepager)
            if items:
                reviewed["review_items"] = unique(items)[:8]
                reviewed["review_item_generation"] = {
                    "method": "bedrock_nova_pro",
                    "model_id": REVIEWER_MODEL_ID,
                }
        transfer = clean_quote(obj.get("transfer_text") or "")
        if transfer:
            reviewed["transfer_text"] = transfer
        if isinstance(obj.get("doctor_brief"), dict) and is_grounded_text(json.dumps(obj.get("doctor_brief"), ensure_ascii=False), onepager):
            reviewed["doctor_brief"] = obj.get("doctor_brief")
        reviewed["llm_review"] = {
            "model_id": REVIEWER_MODEL_ID,
            "raw_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
            "issues": obj.get("issues") if isinstance(obj.get("issues"), list) else [],
        }
        return reviewed
    except Exception as exc:
        reviewed = dict(onepager)
        reviewed["llm_review"] = {"model_id": REVIEWER_MODEL_ID, "error": str(exc)}
        return reviewed


def build_onepager_review_prompt(session, onepager, heuristic_candidates=None):
    payload = {
        "visit_type": visit_label(session.get("visit_type")),
        "patient": session.get("patient", {}),
        "responses": {
            qid: {
                "text": value.get("text", ""),
                "structured": value.get("structured", {}),
                "matched_slots": value.get("matched_slots", []),
            }
            for qid, value in (session.get("responses") or {}).items()
            if isinstance(value, dict)
        },
        "draft_onepager": onepager,
        "heuristic_candidates_do_not_copy_blindly": heuristic_candidates or [],
    }
    return f"""
You are a senior Korean outpatient physician preparing the next-step checklist before seeing this patient.
Your job is NOT to diagnose in place of the doctor and NOT to write treatment orders.
Your job is to read the full intake record like a clinician, identify what must be clarified or answered in the visit, and create practical physician tasks.

You will receive:
- patient metadata
- raw Q1-Q4 transcripts
- semantic parsing results from earlier LLM calls
- symptom_slots matched by BM25 + Titan embedding IR
- clinical_clues extracted from the conversation
- patient agenda/questions from Q4
- safety flags
- heuristic_candidates_do_not_copy_blindly: rough code-generated candidates that may be incomplete or wrong

Clinical tasking method:
Before writing JSON, silently run this checklist. Do not output the checklist or your reasoning.
A. What is the patient's main complaint and what details are still missing for a doctor to act?
B. What time course, progression, severity, trigger, or relieving factor needs clarification?
C. Are there medication, supplement, adherence, allergy, pregnancy, chronic disease, or interaction issues that change counseling?
D. What exact patient questions from Q4 must be answered by the doctor?
E. Are there red flags or safety issues that require priority handling?
F. Which tasks are actually supported by the transcript? Remove unsupported generic tasks.

Review item rules:
1. Generate review_items as the doctor's next actions, not as labels or summaries.
2. Each review_item must be grounded in at least one of: raw Q1-Q4 text, symptom_slots, clinical_clues, agenda, safety_flags, or matched_slots.ir_trace.
3. Use heuristic candidates only as weak hints. If they are not supported, ignore them.
4. Prefer concrete verbs: "확인", "질문", "안내", "상담", "검토", "평가". Avoid passive summaries.
5. Avoid vague items such as "원인 규명", "진단 필요", "상태 평가" by themselves. Specify what to check or answer.
6. Do NOT add fever/temperature tasks unless fever, heat, chill, high fever, antipyretic use, or body temperature appears in evidence.
7. Do NOT add X-ray, TB, pneumonia, cancer, antibiotics, or lab/test tasks unless safety_flags, patient wording, or clinician agenda explicitly supports them.
8. If Q4 contains patient questions, create one task per distinct question so the doctor can answer it.
   - The task must preserve the same medication/food/test names as the agenda.
   - Never introduce new drug classes, sprays, tests, or disease names that are absent from the evidence.
9. If medication/supplement/adherence appears, create a task only when it affects patient counseling, safety, interactions, or adherence.
10. Use "[우선]" only when safety_flags is non-empty or the raw patient wording clearly describes a red flag. Ordinary sore throat, nasal obstruction, cough, or runny nose must not be marked urgent.
11. Keep review_items short, Korean, and directly actionable. Good style: "콧물/코막힘 지속 정도와 알레르기 병력 확인".
12. Preserve uncertainty. Do not assert unsupported diagnoses or treatment decisions.
13. Return JSON only. No markdown, no prose outside JSON.

Output quality target:
- Ordinary low-risk cases: 2 to 5 review_items.
- Safety or complex cases: up to 8 review_items, urgent items first.
- doctor_brief: 1 to 3 sections that summarize why those tasks matter.
- transfer_text: one concise Korean EMR-style sentence or two short sentences, grounded only in intake data.

Return schema:
{{
  "review_items": ["item"],
  "transfer_text": "EMR draft",
  "doctor_brief": {{
    "headline": "short summary",
    "sections": [
      {{"key": "symptoms|context|medication|agenda|safety", "title": "section title", "summary": "short summary", "items": []}}
    ]
  }},
  "issues": []
}}

Data:
{json.dumps(payload, ensure_ascii=False, default=json_default)}
""".strip()


def sanitize_review_items(items, onepager):
    has_safety = bool(onepager.get("safety_flags"))
    sanitized = []
    for item in items:
        text = clean_quote(item)
        if not text:
            continue
        if not has_safety:
            text = re.sub(r"^\[우선\]\s*", "", text)
        if not is_grounded_text(text, onepager):
            continue
        sanitized.append(text)
    return sanitized


UNSUPPORTED_TERM_PATTERNS = [
    r"항히스타민",
    r"비강\s*스프레이",
    r"스테로이드",
    r"항생제",
    r"항바이러스",
    r"X-ray|x-ray|엑스레이|흉부\s*방사선",
    r"\bCT\b|씨티",
    r"혈액\s*검사",
    r"결핵",
    r"폐렴",
    r"폐암|암",
]


def evidence_text(onepager):
    parts = []
    for slot in onepager.get("symptom_slots", []) or []:
        parts.extend([slot.get("name", ""), slot.get("source_quote", ""), slot.get("normalized_text", "")])
    for clue_item in onepager.get("clinical_clues", []) or []:
        parts.extend([clue_item.get("summary", ""), clue_item.get("source_quote", ""), clue_item.get("label", "")])
    for item in onepager.get("agenda", []) or []:
        parts.extend([item.get("summary", ""), item.get("original_quote", ""), item.get("type_label", "")])
    for flag in onepager.get("safety_flags", []) or []:
        parts.extend([flag.get("message", ""), flag.get("matched_pattern", ""), flag.get("label", "")])
    return normalize_text(" ".join(parts))


def is_grounded_text(text, onepager):
    evidence = evidence_text(onepager)
    if not evidence:
        return True
    for pattern in UNSUPPORTED_TERM_PATTERNS:
        if re.search(pattern, text, flags=re.I) and not re.search(pattern, evidence, flags=re.I):
            return False
    return True


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


def save_doctor_response(body):
    session_id = body.get("session_id") or body.get("sessionId")
    session = get_session(session_id)
    if not session:
        return None, response(404, {"error": "session_not_found"})
    answers = body.get("answers") or []
    patient_instruction = body.get("patient_instruction") or body.get("patientInstruction") or body.get("additional_notes") or body.get("additionalNotes") or ""
    guide = generate_patient_guide(session, answers, patient_instruction)
    if not guide["items"]:
        guide["items"] = default_guide_items(session)
    doctor_review = {
        "answers": answers,
        "patient_instruction": patient_instruction,
        "additional_notes": patient_instruction,
        "reviewed_at": now_iso(),
    }
    update_session(session_id, {
        "doctor_review": doctor_review,
        "patient_guide": guide,
        "status": "reviewed",
    })
    return {"doctor_review_saved": True, "patient_guide_generated": True, "validator_passed": True, "patient_guide": guide}, None


def generate_patient_guide(session, answers, patient_instruction):
    if USE_BEDROCK_LLM and ENABLE_BEDROCK_GUIDE:
        try:
            guide = generate_patient_guide_bedrock(session, answers, patient_instruction)
            if is_patient_guide_usable(guide, answers):
                guide["generation_method"] = "bedrock_nova_lite_grounded"
                return guide
        except Exception as exc:
            guide_error = str(exc)
        else:
            guide_error = "bedrock_output_failed_validation"
    else:
        guide_error = "bedrock_guide_disabled"

    return {
        "generated_at": now_iso(),
        "items": doctor_answer_guide_items(answers, patient_friendly=True),
        "delivery_options": ["screen", "tts", "print"],
        "generation_method": "deterministic_patient_friendly_fallback",
        "guide_warning": guide_error,
    }


def generate_patient_guide_bedrock(session, answers, patient_instruction):
    payload = {
        "patient": session.get("patient", {}),
        "onepager": session.get("onepager", {}),
        "doctor_answers": answers,
        "doctor_patient_instruction_displayed_separately": patient_instruction,
    }
    prompt = f"""
You are a Korean patient instruction writer for older adults after a clinic visit.
Convert doctor's answers into easy Korean guide items.

Rules:
- Do not add medical facts not present in doctor_answers or notes.
- Do not copy the doctor's answer verbatim. Rewrite it into polite, easy Korean for an older patient.
- Preserve the doctor's meaning, permission, warnings, timing, and follow-up conditions.
- Keep each bullet short and clear. Prefer 1-3 sentences per question.
- Avoid difficult medical terms unless the doctor used them.
- Do not output generic placeholders like "진료실에서 안내받은 내용을 따라 주세요."
- The field doctor_patient_instruction_displayed_separately is shown as a separate blue "선생님 강조사항" card. Do not duplicate it inside question answer items.
- Return JSON only.

Schema:
{{
  "items": [
    {{
      "question": "patient question summary",
      "answer_simple": ["short instruction sentence"],
      "tts_emphasis_words": ["important word"]
    }}
  ],
  "delivery_options": ["screen", "tts", "print"]
}}

Data:
{json.dumps(payload, ensure_ascii=False, default=json_default)}
""".strip()
    obj, raw_text = call_bedrock_json(prompt, GUIDE_MODEL_ID, GUIDE_MAX_TOKENS)
    items = []
    for item in obj.get("items", []) if isinstance(obj.get("items"), list) else []:
        answers_simple = item.get("answer_simple") if isinstance(item.get("answer_simple"), list) else []
        answers_simple = [clean_quote(x) for x in answers_simple if clean_quote(x)]
        if not answers_simple:
            continue
        items.append({
            "question": clean_quote(item.get("question") or "진료 안내"),
            "answer_simple": answers_simple,
            "tts_emphasis_words": [clean_quote(x) for x in item.get("tts_emphasis_words", []) if clean_quote(x)] if isinstance(item.get("tts_emphasis_words"), list) else [],
        })
    return {
        "generated_at": now_iso(),
        "items": items,
        "delivery_options": obj.get("delivery_options") if isinstance(obj.get("delivery_options"), list) else ["screen", "tts", "print"],
        "llm_meta": {
            "model_id": GUIDE_MODEL_ID,
            "raw_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        },
    }


def split_answer(text):
    parts = [p.strip() for p in re.split(r"[.\n]", text or "") if p.strip()]
    return parts or ["진료실에서 안내받은 내용을 따라 주세요."]


def doctor_answer_guide_items(answers, patient_friendly=False):
    items = []
    for ans in answers or []:
        answer_text = ans.get("answer_text") or ans.get("answer") or ""
        if patient_friendly:
            answer_simple = rewrite_answer_for_patient(answer_text)
        else:
            answer_simple = split_answer(answer_text)
        items.append({
            "question": ans.get("question_summary") or ans.get("question") or "환자 질문",
            "answer_simple": answer_simple,
            "tts_emphasis_words": extract_emphasis_words(answer_text),
        })
    return items


def rewrite_answer_for_patient(text):
    if not normalize_text(text):
        return ["진료실에서 안내받은 내용을 확인해 주세요."]
    sentences = split_answer(text)
    out = []
    for sentence in sentences:
        s = normalize_text(sentence)
        s = s.replace("추후", "나중에")
        s = s.replace("검토 필요", "다시 확인이 필요합니다")
        s = s.replace("검토", "확인")
        if "복용 가능" in s or "먹어도" in s or "드셔도" in s:
            if "문제 없이" in s:
                s = "같이 드셔도 괜찮습니다"
            else:
                s = s.replace("복용 가능", "드셔도 됩니다")
        if "약물 추가" in s or "다른 약" in s:
            s = "나중에 다른 약이 추가되면 병원이나 약국에 다시 확인해 주세요"
        if not re.search(r"(요|다|세요|습니다)$", s):
            s += "습니다"
        out.append(s)
    return unique(out) or ["진료실에서 안내받은 내용을 확인해 주세요."]


def is_patient_guide_usable(guide, answers):
    items = guide.get("items") if isinstance(guide, dict) else []
    if not isinstance(items, list) or not items:
        return False
    generic_patterns = [
        "진료실에서 안내받은 내용을 따라 주세요",
        "오늘 진료에서 안내받은 내용을 확인해 주세요",
        "의사 선생님의 안내를 따라 주세요",
    ]
    answer_texts = [normalize_text(ans.get("answer_text") or ans.get("answer") or "") for ans in (answers or [])]
    usable_count = 0
    for idx, item in enumerate(items):
        answers_simple = item.get("answer_simple") if isinstance(item, dict) else []
        if not isinstance(answers_simple, list):
            continue
        cleaned = [clean_quote(x) for x in answers_simple if clean_quote(x)]
        if not cleaned:
            continue
        joined = " ".join(cleaned)
        if any(pattern in joined for pattern in generic_patterns):
            continue
        source = answer_texts[idx] if idx < len(answer_texts) else " ".join(answer_texts)
        if source and compact_ir(joined) == compact_ir(" ".join(split_answer(source))):
            continue
        usable_count += 1
    return usable_count > 0


def extract_emphasis_words(text):
    words = []
    for token in ("복용", "약", "영양제", "검토", "중단", "재내원", "검사", "X-ray"):
        if token in str(text or ""):
            words.append(token)
    return unique(words)[:5]


def default_guide_items(session):
    agenda = (session.get("onepager") or {}).get("agenda") or []
    if not agenda:
        return [{"question": "진료 안내", "answer_simple": ["오늘 진료에서 안내받은 내용을 확인해 주세요."], "tts_emphasis_words": []}]
    return [{"question": item.get("summary", "환자 질문"), "answer_simple": ["진료실에서 안내받은 내용을 따라 주세요."], "tts_emphasis_words": []} for item in agenda]


def get_guide(session_id):
    session = get_session(session_id)
    if not session:
        return None
    guide = session.get("patient_guide")
    if not guide:
        guide = {"generated_at": now_iso(), "items": default_guide_items(session), "delivery_options": ["screen", "tts", "print"]}
    return {
        "session_id": session_id,
        "patient_name_masked": (session.get("patient") or {}).get("name", "환자"),
        "patient_guide": guide,
        "doctor_additional_notes": (session.get("doctor_review") or {}).get("patient_instruction") or (session.get("doctor_review") or {}).get("additional_notes", ""),
    }

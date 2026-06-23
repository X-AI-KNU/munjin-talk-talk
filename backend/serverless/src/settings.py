"""Lambda 런타임 설정과 AWS client 초기화.

환경 변수, 데이터 파일 경로, boto3 client/resource를 한 곳에서 관리합니다.
Lambda warm invocation에서는 모듈 전역 객체가 재사용되므로, AWS client를
매 요청마다 다시 만들지 않습니다.
"""

from pathlib import Path
import os

import boto3
from botocore.config import Config


# 배포 리전과 핵심 저장소 이름은 SAM template에서 환경 변수로 주입합니다.
REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
TABLE_NAME = os.environ.get("SESSIONS_TABLE", "MunjinSessions")
ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET", "")
CUSTOM_VOCABULARY = os.environ.get("CUSTOM_VOCABULARY", "")
DOMAIN_PACK = os.environ.get("DOMAIN_PACK", "respiratory")
QUESTION_SET = os.environ.get("QUESTION_SET", "default")

# 사투리 RAG / 표준어 변환 설정입니다.
DIALECT_PACK = os.environ.get("DIALECT_PACK", "dialect_kangwon")
DIALECT_TOP_K = int(os.environ.get("DIALECT_TOP_K", "8"))
DIALECT_NORMALIZER_MODEL_ID = os.environ.get("DIALECT_NORMALIZER_MODEL_ID", "apac.amazon.nova-lite-v1:0")
DIALECT_MAX_TOKENS = int(os.environ.get("DIALECT_MAX_TOKENS", "700"))

# 직원/의료진 로그인 설정입니다.
# 사람이 입력하는 접근 코드는 *_ACCESS_CODE로 받고, 기존 배포 호환을 위해
# 기존 이름인 *_ACCESS_TOKEN도 보조 설정값으로 읽습니다.
STAFF_ACCESS_CODE = os.environ.get("STAFF_ACCESS_CODE") or os.environ.get("STAFF_ACCESS_TOKEN", "")
DOCTOR_ACCESS_CODE = os.environ.get("DOCTOR_ACCESS_CODE") or os.environ.get("DOCTOR_ACCESS_TOKEN", "")
STAFF_ACCESS_CODE_SHA256 = os.environ.get("STAFF_ACCESS_CODE_SHA256", "")
DOCTOR_ACCESS_CODE_SHA256 = os.environ.get("DOCTOR_ACCESS_CODE_SHA256", "")
AUTH_SIGNING_SECRET = os.environ.get("AUTH_SIGNING_SECRET", "")
AUTH_TOKEN_TTL_MINUTES = int(os.environ.get("AUTH_TOKEN_TTL_MINUTES", "240"))
S3_SERVER_SIDE_ENCRYPTION = os.environ.get("S3_SERVER_SIDE_ENCRYPTION", "AES256")
S3_KMS_KEY_ID = os.environ.get("S3_KMS_KEY_ID", "")

# Bedrock 모델 라우팅입니다. 난도가 높은 의미 추출/검토는 Pro 계열,
# 환자 안내문처럼 상대적으로 가벼운 변환은 Lite 계열을 기본값으로 둡니다.
STRONG_MODEL_ID = os.environ.get("STRONG_MODEL_ID", "apac.amazon.nova-pro-v1:0")
LIGHT_MODEL_ID = os.environ.get("LIGHT_MODEL_ID", "apac.amazon.nova-lite-v1:0")
REVIEWER_MODEL_ID = os.environ.get("REVIEWER_MODEL_ID", STRONG_MODEL_ID)
GUIDE_MODEL_ID = os.environ.get("GUIDE_MODEL_ID", LIGHT_MODEL_ID)
MAX_LLM_TOKENS = int(os.environ.get("MAX_LLM_TOKENS", "1600"))
REVIEW_MAX_TOKENS = int(os.environ.get("REVIEW_MAX_TOKENS", "900"))
GUIDE_MAX_TOKENS = int(os.environ.get("GUIDE_MAX_TOKENS", "900"))
EXTRACTION_RETRY_ATTEMPTS = int(os.environ.get("EXTRACTION_RETRY_ATTEMPTS", "3"))
REVIEW_RETRY_ATTEMPTS = int(os.environ.get("REVIEW_RETRY_ATTEMPTS", "2"))

# IR 검색에 필요한 원천 데이터와 사전 계산된 Titan embedding 파일 위치입니다.
DATA_DIR = Path(__file__).resolve().parent / "data"
DISEASES_PATH = DATA_DIR / "diseases_cleaned.json"
SYMPTOM_INDEX_PATH = DATA_DIR / "symptom_index.json"
EMBEDDING_MODEL_ID = os.environ.get("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "512"))
HYBRID_TOP_K = int(os.environ.get("HYBRID_TOP_K", "5"))
HYBRID_CANDIDATE_K = int(os.environ.get("HYBRID_CANDIDATE_K", "24"))
HYBRID_ACCEPT_THRESHOLD = float(os.environ.get("HYBRID_ACCEPT_THRESHOLD", "0.18"))
HYBRID_BM25_WEIGHT = float(os.environ.get("HYBRID_BM25_WEIGHT", "0.35"))
HYBRID_VECTOR_WEIGHT = float(os.environ.get("HYBRID_VECTOR_WEIGHT", "0.65"))
HYBRID_MIN_VECTOR_SCORE = float(os.environ.get("HYBRID_MIN_VECTOR_SCORE", "0.12"))
HYBRID_MIN_BM25_SCORE = float(os.environ.get("HYBRID_MIN_BM25_SCORE", "0.04"))
HYBRID_MIN_LABEL_SCORE = float(os.environ.get("HYBRID_MIN_LABEL_SCORE", "0.55"))
EMBEDDING_CACHE_PATH = DATA_DIR / (
    f"symptom_embeddings_{EMBEDDING_MODEL_ID.replace(':', '_').replace('/', '_')}_{EMBEDDING_DIMENSIONS}.json"
)

# boto3 client/resource는 모듈 전역에서 생성해 Lambda cold start 비용을 줄입니다.
ddb = boto3.resource("dynamodb", region_name=REGION)
table = ddb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=REGION)
bedrock_runtime = boto3.client(
    "bedrock-runtime",
    region_name=REGION,
    config=Config(connect_timeout=5, read_timeout=50, retries={"max_attempts": 2, "mode": "standard"}),
)

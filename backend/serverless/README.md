# 🚀 문진톡톡 · Serverless Backend

문진톡톡 MVP의 AWS 서버리스 백엔드. AWS SAM으로 API Gateway · Lambda · 환경 변수 · route를 배포합니다. 핵심 역할은 환자 문진 텍스트를 안전하게 구조화해 의료진 원페이퍼와 환자 안내문으로 이어지는 서버 측 처리를 제공하는 것입니다.

> 📍 [루트 README](../../README.md) · [백엔드 개요](../README.md) · [배포 가이드](../../docs/DEPLOYMENT.md)

---

## 1. 핵심 원칙

1. 음성 원본 파일은 저장하지 않습니다.
2. DynamoDB에는 세션 상태와 S3 artifact pointer만 저장합니다.
3. 답변·원페이퍼·의사 답변·안내문은 운영용 S3 artifact로 저장합니다.
4. LLM/LangGraph/IR 추적은 `llm_trace.redacted.json` 하나에 최소 설명 단위로만 저장합니다.
5. LLM 출력은 Pydantic schema와 source_quote 검증을 통과해야 저장됩니다.
6. 증상 매칭은 LLM 단독 판단이 아니라 BM25 + Titan Vector Hybrid IR을 통과해야 합니다.
7. 검증 실패를 정상 결과처럼 조용히 대체하지 않습니다.
8. 의료진 UI와 운영 artifact에는 내부 rank score를 숫자로 노출하지 않습니다.

---

## 2. AWS 구성

```text
API Gateway HTTP API
  → Lambda Python 3.12
     → DynamoDB MunjinSessions      (세션 상태 + S3 pointer)
     → S3 artifact bucket           (가명처리 산출물)
     → Amazon Bedrock Nova Pro/Lite (추출·리뷰·안내문 변환)
     → Amazon Titan Text Embeddings (Hybrid IR vector)
     → Amazon Transcribe Streaming  (presigned URL)
```

**DynamoDB 저장:** session_id, queue_number, status, visit_type, 마스킹 환자 표시정보, age_band, risk, artifact key, question_status. **미저장:** 실명·생년월일·연락처 원문, 문항 원문, 원페이퍼/안내문/의사 답변 전체.

**S3 artifact:**
```text
sessions/YYYY-MM-DD/{session_id}/
  consent.json  answers.redacted.json  onepaper.redacted.json
  doctor_review.redacted.json  patient_guide.redacted.json  llm_trace.redacted.json
```
제출 환경 운영 설정: Block Public Access, 기본 암호화, Lifecycle 3일 삭제, Macie, Lambda role 중심 `GetObject`/`PutObject` 권한 제한.

**Bedrock:** Nova Pro(의미 추출·Q4 분리·원페이퍼 리뷰), Nova Lite(가벼운 구조화·안내문 변환), Titan Embeddings(IR vector). **Transcribe:** 음성 미업로드, 브라우저가 presigned WebSocket으로 직접 스트리밍.

---

## 3. 폴더 구조

```text
backend/serverless/
├── README.md
├── template.yaml
├── src/
│   ├── handler.py  orchestration.py  settings.py
│   ├── sessions.py  artifact_store.py  artifact_policy.py  privacy.py  audio.py
│   ├── pipeline_graph.py  pipeline_nodes.py  pipeline_state.py  pipeline_trace.py
│   ├── dialect_config.py  dialect_rag.py  dialect_normalization.py
│   ├── rag_context.py  langchain_prompting.py  llm.py
│   ├── extraction_prompts.py  extraction_schema.py  clinical_terms.py  clinical_state.py
│   ├── domain_config.py  question_sets.py  utils.py
│   ├── retrieval.py  retrieval_documents.py  retrieval_embeddings.py  retrieval_scoring.py
│   ├── onepager.py  onepager_sections.py  onepager_review.py  guide.py
│   ├── schemas/  ├─ extraction.py ├─ review.py └─ guide.py
│   └── data/
│       ├── README.md
│       ├── dialect_packs/dialect_kangwon.csv/json
│       ├── domain_packs/respiratory.json (+ respiratory_fewshot.txt)
│       ├── question_sets/default.json
│       └── (비공개 배치) diseases_cleaned / symptom_index / embedding cache
└── tests/
    └── pytest 기반 회귀 검증 코드와 프롬프트 기준 파일
```

---

## 4. 주요 모듈

| 파일 | 역할 |
| --- | --- |
| `handler.py` | API Gateway route 분기 |
| `orchestration.py` | `/process-answer` 전체 처리 진입점 |
| `settings.py` | AWS client, 환경 변수, 모델 설정 |
| `sessions.py` | DynamoDB 세션 생성·조회·상태 갱신 |
| `artifact_store.py` / `artifact_policy.py` | S3 저장·조회 / 저장 필드 정리 |
| `privacy.py` | 저장 전 가명처리·요약 helper |
| `audio.py` | Transcribe Streaming presigned URL |
| `pipeline_graph.py` / `pipeline_nodes.py` / `pipeline_state.py` / `pipeline_trace.py` | LangGraph 정의·처리·상태·trace |
| `dialect_config.py` / `dialect_rag.py` / `dialect_normalization.py` | 강원 방언팩 로딩·검색·표준화 보조 |
| `rag_context.py` | RAG 참고 문맥 검색 |
| `langchain_prompting.py` / `llm.py` | Bedrock JSON chain / 호출 wrapper |
| `extraction_prompts.py` / `extraction_schema.py` | Q별 prompt / extraction 보조 스키마 |
| `domain_config.py` / `question_sets.py` | 도메인팩 로딩·기본 질문값 / 질문셋 로딩 |
| `clinical_terms.py` / `clinical_state.py` | 임상 용어 / 임상 상태 helper |
| `retrieval.py` (+ `_documents`/`_embeddings`/`_scoring`) | Hybrid IR |
| `onepager.py` / `onepager_sections.py` / `onepager_review.py` | 원페이퍼 생성·섹션·리뷰 |
| `guide.py` | 의사 답변 저장·환자 안내문 생성 |
| `schemas/{extraction,review,guide}.py` | Pydantic 검증 스키마 |

---

## 5. API 목록

| Method | Path | 역할 |
| --- | --- | --- |
| `POST` | `/auth/login` | 직원/의사 접근 코드 로그인, Bearer 세션 토큰 발급 |
| `POST` | `/sessions` | 접수처 문진 세션 생성 |
| `GET` | `/sessions/{session_id}` | 세션 상세 조회 |
| `POST` | `/sessions/{session_id}/consent` | 환자 이용 동의 저장 |
| `POST` | `/sessions/{session_id}/staff-help` | 직원 도움 요청 |
| `GET` | `/doctor/queue` | 의사 대기열 조회 |
| `POST` | `/transcribe-stream-url` | Transcribe Streaming URL 발급 |
| `POST` | `/process-answer` | 환자 답변 처리 |
| `GET` | `/question-sets/{question_set_id}` | 문진 질문셋 조회 |
| `GET` | `/onepager/{session_id}` | 원페이퍼 조회 |
| `POST` | `/onepager/{session_id}/review` | 원페이퍼 AI 재검토 재실행 |
| `POST` | `/doctor-response` | 의사 답변·강조사항 저장 |
| `GET` | `/guide/{session_id}` | 환자 안내문 조회 |

---

## 6. 문항 처리 흐름

```text
POST /process-answer
  → input_transcript → quick_safety_flag → dialect_normalization → rag_context_retrieval
  → semantic_extraction → schema_quote_validation
  → (검증 실패 시 semantic_extraction으로 retry)
  → hybrid_ir_match → session_validation_save → onepaper_refresh → response_payload

safety 분기: schema_quote_validation → safety_guardrail_save → response_payload
```

저장 규칙: `session_validation_save`는 DynamoDB에 답변 전체를 저장하지 않습니다. 검증된 답변은 S3 `answers.redacted.json`에, 설명은 `llm_trace.redacted.json`에 최소 단위로. DynamoDB에는 `question_status`·`risk`·`status`·S3 key만 갱신.

---

## 7. 환경 변수

| 변수 | 필수 | 설명 |
| --- | --- | --- |
| `SESSIONS_TABLE` | ✅ | DynamoDB table name |
| `ARTIFACTS_BUCKET` | ✅ | 가명처리 artifact S3 bucket |
| `AWS_REGION` | | 기본 `ap-northeast-2` |
| `CUSTOM_VOCABULARY` | | Transcribe custom vocabulary |
| `ALLOWED_ORIGINS` | | CORS origin (SAM `CorsAllowOrigin`) |
| `STAFF_ACCESS_CODE` / `DOCTOR_ACCESS_CODE` | ✅ | 직원/의료진 로그인 모달에서 입력하는 접근 코드 |
| `STAFF_ACCESS_CODE_SHA256` / `DOCTOR_ACCESS_CODE_SHA256` | | 접근 코드를 평문 대신 SHA-256 해시로 검증할 때 사용 |
| `AUTH_SIGNING_SECRET` | ✅ | 로그인 성공 후 발급하는 역할 세션 토큰의 HMAC 서명 비밀값 |
| `AUTH_TOKEN_TTL_MINUTES` | | 직원/의료진 세션 토큰 유효 시간. 기본 240분 |
| `STRONG_MODEL_ID` / `LIGHT_MODEL_ID` | | Bedrock 강/경 모델. 기본 Nova Pro / Nova Lite |
| `REVIEWER_MODEL_ID` / `GUIDE_MODEL_ID` | | 원페이퍼 리뷰 / 안내문 모델 (미설정 시 strong/light) |
| `MAX_LLM_TOKENS` / `REVIEW_MAX_TOKENS` / `GUIDE_MAX_TOKENS` | | 최대 출력 토큰 |
| `EXTRACTION_RETRY_ATTEMPTS` / `REVIEW_RETRY_ATTEMPTS` | | 재시도 횟수 |
| `EMBEDDING_MODEL_ID` / `EMBEDDING_DIMENSIONS` | | Titan embedding 모델 / 차원(기본 512) |
| `HYBRID_TOP_K` / `HYBRID_CANDIDATE_K` | | IR 반환·내부 후보 개수 |
| `HYBRID_ACCEPT_THRESHOLD` | | IR 후보 채택 최소 기준 |
| `HYBRID_BM25_WEIGHT` / `HYBRID_VECTOR_WEIGHT` | | 점수 가중치 |
| `HYBRID_MIN_VECTOR_SCORE` / `HYBRID_MIN_BM25_SCORE` / `HYBRID_MIN_LABEL_SCORE` | | 채택 최소 기준 |

공개 저장소에는 원천 의료 백과 본문과 파생 인덱스·embedding cache가 포함되지 않습니다. SAM 배포 전 팀 내부 비공개 데이터 저장소에서 `src/data/diseases_cleaned.json`, `src/data/symptom_index.json`, `src/data/symptom_embeddings_amazon.titan-embed-text-v2_0_512.json`을 배치해야 Hybrid IR이 정상 동작합니다.

---

## 8. SAM 배포

```bash
cd backend/serverless
sam build
sam deploy --guided
```

권장 입력 예시:

```text
Stack Name: munjin-mvp-backend
AWS Region: ap-northeast-2
SessionsTableName: MunjinSessions
ArtifactsBucketName: <s3-artifact-bucket-name>
LambdaRoleArn: <lambda-role-arn>
CorsAllowOrigin: https://<amplify-branch-domain>
Confirm changes before deploy: y
Allow SAM CLI IAM role creation: n
MunjinApiFunction has no authentication. Is this okay?: y
```

배포 후 CloudFormation output의 `ApiEndpoint`를 프론트 Amplify 환경 변수 `VITE_API_BASE_URL`에 입력합니다.

---

## 9. Lambda IAM 권한

DynamoDB `GetItem`/`PutItem`/`UpdateItem`/`Scan`, S3 artifact bucket `GetObject`/`PutObject`, Bedrock model invoke, Transcribe streaming URL 생성 권한, CloudWatch Logs 쓰기. 운영에서는 wildcard 대신 구체적 resource ARN으로 제한합니다.

---

## 10. 로컬 검증

```bash
# Python 문법
python -m compileall src

# 검증
pip install -r src/requirements.txt pytest
python -m pytest tests/ -q
```

<details>
<summary>SAM template / Windows</summary>

```bash
sam validate
sam build
# telemetry 권한 오류 시: SAM_CLI_TELEMETRY=0 sam validate
```
</details>

---

## 11. 최종 동작 확인 기준

1. `POST /sessions` 성공
2. DynamoDB item에 `patient.full_name`/`birth_date`/`phone`이 **없어야** 함
3. `POST /sessions/{id}/consent` 성공 → S3 `consent.json` 생성
4. `POST /process-answer` 성공 → S3 `answers`·`onepaper`·`llm_trace` `.redacted.json` 생성
5. DynamoDB item에 `responses`/`question_results`/`onepager`/`doctor_review`/`patient_guide`가 **없어야** 함
6. `GET /onepager/{id}`가 S3 artifact를 읽어 payload 반환
7. `POST /doctor-response` 후 S3 `doctor_review`·`patient_guide` `.redacted.json` 생성
8. `GET /guide/{id}` 안내문 payload 반환

---

## 12. 자주 보는 오류

| 증상 | 원인 | 확인 |
| --- | --- | --- |
| `ARTIFACTS_BUCKET ... required` | SAM parameter/env 누락 | CloudFormation parameter, Lambda env |
| `AccessDenied` on S3 | Lambda role 권한 없음 | IAM policy의 bucket ARN |
| Bedrock 호출 실패 | 모델 접근 권한/region 불일치 | Bedrock model access, region |
| Transcribe 연결 실패 | HTTPS/마이크/URL 문제 | 브라우저 권한, `/transcribe-stream-url` 응답 |
| validation 422 | LLM JSON schema/quote 실패 | response validation error, S3 trace |
| 원페이퍼 비어 있음 | 답변 artifact 없음/`/process-answer` 실패 | S3 `answers.redacted.json`, CloudWatch |

---

## 13. Git 제외 파일

```text
backend/serverless/.aws-sam/   samconfig.toml
frontend/node_modules/  frontend/dist/  frontend/.env  frontend/.env.local
.env  .env.local  *.zip
```

---

## 14. 참고 문서

[루트 README](../../README.md) · [백엔드 개요](../README.md) · [LangGraph 파이프라인](../../docs/LANGGRAPH_PIPELINE.md) · [DATA_SCHEMA](../../docs/DATA_SCHEMA.md) · [SECURITY_DATA_INVENTORY](../../docs/SECURITY_DATA_INVENTORY.md) · [DEPLOYMENT](../../docs/DEPLOYMENT.md)

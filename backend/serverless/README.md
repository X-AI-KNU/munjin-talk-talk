# 문진톡톡 Serverless Backend

이 디렉터리는 문진톡톡 MVP의 AWS 서버리스 백엔드입니다. AWS SAM으로 API Gateway, Lambda, 환경 변수, route를 배포합니다.

백엔드의 핵심 역할은 환자 문진 텍스트를 안전하게 구조화하고, 의료진 원페이퍼와 환자 안내문으로 이어지는 서버 측 처리를 제공하는 것입니다.

---

## 1. 핵심 원칙

1. 음성 원본 파일은 저장하지 않습니다.
2. DynamoDB에는 세션 상태와 S3 artifact pointer만 저장합니다.
3. 문진 답변, 원페이퍼, 의사 답변, 환자 안내문은 운영용 S3 artifact로 저장합니다.
4. LLM/LangGraph/IR 추적은 `llm_trace.redacted.json` 하나에 최소 설명 단위만 저장합니다.
5. LLM 출력은 Pydantic schema와 source_quote 검증을 통과해야 저장됩니다.
6. 증상 매칭은 LLM 단독 판단이 아니라 BM25 + Titan Vector Hybrid IR을 통과해야 합니다.
7. rule-based extraction fallback으로 LLM 실패를 조용히 대체하지 않습니다.
8. 의료진 UI와 운영 artifact에는 내부 rank score를 숫자로 노출하지 않습니다.

---

## 2. AWS 구성

```text
API Gateway HTTP API
  -> Lambda Python 3.12
     -> DynamoDB MunjinSessions
     -> S3 artifact bucket
     -> Amazon Bedrock Nova Pro / Nova Lite
     -> Amazon Titan Text Embeddings
     -> Amazon Transcribe Streaming presigned URL
```

### DynamoDB

용도:

- 문진 세션 ID
- 대기 순번
- 세션 상태
- 초진/재진
- 마스킹 환자 표시 정보
- 위험도 요약
- S3 artifact key
- 문항별 완료 상태

저장하지 않는 값:

- 실명 원문
- 생년월일 원문
- 연락처 원문
- 문항별 환자 발화 원문
- 원페이퍼 전체 JSON
- 의사 답변 전문
- 환자 안내문 전체 JSON

### S3 artifact bucket

용도:

```text
sessions/YYYY-MM-DD/{session_id}/
  consent.json
  answers.redacted.json
  onepaper.redacted.json
  doctor_review.redacted.json
  patient_guide.redacted.json
  llm_trace.redacted.json
```

운영 설정 권장:

- Block Public Access 활성화
- 기본 암호화 또는 KMS 적용
- Lifecycle 3일 삭제
- Macie 민감정보 탐지
- Lambda role만 `GetObject`, `PutObject` 허용

### Bedrock

사용 모델:

- Nova Pro: 의미 추출, Q4 환자 질문 분리, 원페이퍼 리뷰
- Nova Lite: 비교적 가벼운 구조화, 환자 안내문 변환
- Titan Text Embeddings: Hybrid IR vector similarity

### Transcribe

현재 구조는 Amazon Transcribe Streaming을 사용합니다. 환자 음성을 S3에 업로드하지 않고, 브라우저가 presigned WebSocket URL로 직접 스트리밍합니다.

---

## 3. 폴더 구조

```text
backend/serverless/
|-- README.md
|-- template.yaml
|-- src/
|   |-- handler.py
|   |-- settings.py
|   |-- artifact_store.py
|   |-- privacy.py
|   |-- sessions.py
|   |-- audio.py
|   |-- orchestration.py
|   |-- pipeline_graph.py
|   |-- pipeline_nodes.py
|   |-- pipeline_state.py
|   |-- pipeline_trace.py
|   |-- rag_context.py
|   |-- extraction_prompts.py
|   |-- extraction_schema.py
|   |-- langchain_prompting.py
|   |-- llm.py
|   |-- retrieval.py
|   |-- retrieval_documents.py
|   |-- retrieval_embeddings.py
|   |-- retrieval_scoring.py
|   |-- clinical_terms.py
|   |-- domain_config.py
|   |-- onepager.py
|   |-- onepager_sections.py
|   |-- onepager_review.py
|   |-- guide.py
|   |-- schemas/
|   `-- data/
|       |-- domain_pack_respiratory.json
|       |-- diseases_cleaned.json
|       |-- symptom_index.json
|       `-- symptom_embeddings_*.json
`-- tests/
    `-- test_schema_and_artifact_policy.py
```

---

## 4. 주요 모듈

| 파일 | 역할 |
| --- | --- |
| `handler.py` | API Gateway route 분기 |
| `settings.py` | AWS client, 환경 변수, 모델 설정 |
| `sessions.py` | DynamoDB 세션 생성, 조회, 상태 갱신 |
| `artifact_store.py` | S3 artifact 저장과 조회 |
| `artifact_policy.py` | 운영 artifact와 최소 trace 저장 필드 정리 |
| `privacy.py` | 저장 전 가명처리와 요약 helper |
| `audio.py` | Transcribe Streaming presigned URL 발급 |
| `orchestration.py` | `/process-answer` 전체 처리 진입점 |
| `pipeline_graph.py` | LangGraph 노드와 edge 정의 |
| `pipeline_nodes.py` | 각 pipeline node의 실제 처리 |
| `pipeline_state.py` | LangGraph state 구조 |
| `pipeline_trace.py` | active path와 trace 저장 |
| `rag_context.py` | 원천 JSON과 제한 alias bridge 기반 RAG 참고 문맥 검색 |
| `extraction_prompts.py` | Q별 영어 prompt |
| `domain_config.py` | 도메인팩 JSON 로딩, 기본 질문 문구 fallback, 허용 symptom slot 제공 |
| `data/domain_pack_respiratory.json` | 호흡기계 MVP의 증상 slot, alias, safety flag, 기본 질문 문구 |
| `langchain_prompting.py` | LangChain PromptTemplate, Bedrock Runnable, JSON parser chain |
| `llm.py` | LLM JSON 호출 호환 wrapper와 chain meta 반환 |
| `schemas/extraction.py` | Pydantic extraction schema |
| `retrieval.py` | Hybrid IR 진입점 |
| `retrieval_documents.py` | 원천 JSON을 검색 문서로 변환 |
| `retrieval_embeddings.py` | Titan embedding 로딩과 cosine similarity |
| `retrieval_scoring.py` | BM25, vector, label score 계산 |
| `onepager.py` | 문항 결과 저장과 원페이퍼 artifact 생성 |
| `onepager_sections.py` | 원페이퍼 섹션 조립 |
| `onepager_review.py` | Nova Pro 기반 원페이퍼 final review |
| `guide.py` | 의사 답변 저장과 환자 안내문 생성 |

---

## 5. API 목록

| Method | Path | 역할 |
| --- | --- | --- |
| `POST` | `/sessions` | 접수처 문진 세션 생성 |
| `GET` | `/sessions/{session_id}` | 세션 상세 조회 |
| `POST` | `/sessions/{session_id}/consent` | 환자 서비스 이용 동의 저장 |
| `POST` | `/sessions/{session_id}/staff-help` | 직원 도움 요청 |
| `GET` | `/doctor/queue` | 의사 대기열 조회 |
| `POST` | `/transcribe-stream-url` | Transcribe Streaming URL 발급 |
| `POST` | `/process-answer` | 환자 답변 처리 |
| `GET` | `/onepager/{session_id}` | 원페이퍼 조회 |
| `POST` | `/doctor-response` | 의사 답변 및 강조사항 저장 |
| `GET` | `/guide/{session_id}` | 환자 안내문 조회 |

---

## 6. 문항 처리 흐름

```text
POST /process-answer
  -> input_transcript
  -> quick_safety_flag
  -> rag_context_retrieval
  -> semantic_extraction
  -> schema_quote_validation
  -> 검증 실패 시 semantic_extraction으로 retry
  -> hybrid_ir_match
  -> session_validation_save
  -> onepaper_refresh
  -> response_payload
```

Safety flag가 먼저 감지되면 일부 경로는 다음처럼 분기할 수 있습니다.

```text
schema_quote_validation
  -> safety_guardrail_save
  -> response_payload
```

중요한 저장 규칙:

- `session_validation_save`는 DynamoDB에 환자 답변 전체를 저장하지 않습니다.
- 검증된 답변은 S3 `answers.redacted.json`에 저장하고, graph/validator/IR 설명은 S3 `llm_trace.redacted.json`에 최소 단위로 저장합니다.
- DynamoDB에는 `question_status`, `risk`, `status`, S3 key만 갱신합니다.

---

## 7. 환경 변수

| 변수 | 필수 | 설명 |
| --- | --- | --- |
| `SESSIONS_TABLE` | 예 | DynamoDB table name |
| `ARTIFACTS_BUCKET` | 예 | 가명처리 artifact를 저장할 S3 bucket |
| `AWS_REGION` | 아니오 | AWS region, 기본 `ap-northeast-2` |
| `CUSTOM_VOCABULARY` | 아니오 | Transcribe custom vocabulary 이름 |
| `ALLOWED_ORIGINS` | 아니오 | API 응답 CORS origin. SAM `CorsAllowOrigin`에서 주입 |
| `STRONG_MODEL_ID` | 아니오 | 고난도 의미 추출과 검토용 Bedrock 모델. 기본 Nova Pro |
| `LIGHT_MODEL_ID` | 아니오 | 가벼운 구조화와 안내문 변환용 Bedrock 모델. 기본 Nova Lite |
| `REVIEWER_MODEL_ID` | 아니오 | 원페이퍼 리뷰 모델. 미설정 시 `STRONG_MODEL_ID` 사용 |
| `GUIDE_MODEL_ID` | 아니오 | 환자 안내문 모델. 미설정 시 `LIGHT_MODEL_ID` 사용 |
| `MAX_LLM_TOKENS` | 아니오 | 문항 extraction 최대 출력 토큰 |
| `REVIEW_MAX_TOKENS` | 아니오 | 원페이퍼 review 최대 출력 토큰 |
| `GUIDE_MAX_TOKENS` | 아니오 | 환자 안내문 최대 출력 토큰 |
| `EXTRACTION_RETRY_ATTEMPTS` | 아니오 | schema/source_quote 검증 실패 시 extraction 재시도 횟수 |
| `REVIEW_RETRY_ATTEMPTS` | 아니오 | 원페이퍼 review 재시도 횟수 |
| `EMBEDDING_MODEL_ID` | 아니오 | Titan embedding 모델 |
| `EMBEDDING_DIMENSIONS` | 아니오 | embedding 차원. 기본 512 |
| `HYBRID_TOP_K` | 아니오 | 최종 IR 후보 반환 개수 |
| `HYBRID_CANDIDATE_K` | 아니오 | 내부 검색 후보 개수 |
| `HYBRID_ACCEPT_THRESHOLD` | 아니오 | IR 후보 채택 최소 기준 |
| `HYBRID_BM25_WEIGHT` | 아니오 | BM25 정규화 점수 가중치 |
| `HYBRID_VECTOR_WEIGHT` | 아니오 | Titan vector 정규화 점수 가중치 |
| `HYBRID_MIN_VECTOR_SCORE` | 아니오 | 후보 채택 최소 vector 기준 |
| `HYBRID_MIN_BM25_SCORE` | 아니오 | 후보 채택 최소 BM25 기준 |
| `HYBRID_MIN_LABEL_SCORE` | 아니오 | 후보 채택 최소 label 기준 |

---

## 8. SAM 배포

```powershell
cd backend/serverless
sam build
sam deploy --guided
```

권장 입력 예시:

```text
Stack Name: munjin-mvp-backend-test
AWS Region: ap-northeast-2
Parameter SessionsTableName: MunjinSessionsTest
Parameter ArtifactsBucketName: <s3-artifact-bucket-name>
Parameter LambdaRoleArn: <lambda-role-arn>
Parameter CustomVocabularyName:
Parameter CorsAllowOrigin: https://<amplify-branch-domain>
Confirm changes before deploy: y
Allow SAM CLI IAM role creation: n
MunjinApiFunction has no authentication. Is this okay?: y
```

배포가 끝나면 CloudFormation output의 `ApiEndpoint` 값을 프론트엔드 Amplify 환경 변수 `VITE_API_BASE_URL`에 입력합니다.

---

## 9. Lambda IAM 권한

Lambda role에는 최소한 다음 권한이 필요합니다.

- DynamoDB `GetItem`, `PutItem`, `UpdateItem`, `Scan`
- S3 artifact bucket `GetObject`, `PutObject`
- Bedrock model invoke
- Transcribe streaming URL 생성을 위한 권한
- CloudWatch Logs 쓰기

운영 환경에서는 wildcard보다 구체적인 resource ARN으로 제한해야 합니다.

---

## 10. 로컬 검증

Python syntax:

```powershell
python -m compileall backend/serverless/src
```

SAM template:

```powershell
cd backend/serverless
sam validate
```

SAM build:

```powershell
sam build
```

SAM CLI가 telemetry metadata 파일 권한 오류를 내면 다음을 먼저 시도합니다.

```powershell
$env:SAM_CLI_TELEMETRY='0'
sam validate
```

---

## 11. Smoke Test 기준

배포 후 최소 확인:

1. `POST /sessions`가 성공한다.
2. DynamoDB item에 `patient.full_name`, `patient.birth_date`, `patient.phone`이 없어야 한다.
3. `POST /sessions/{id}/consent`가 성공하고 S3 `consent.json`이 생성된다.
4. `POST /process-answer`가 성공한다.
5. S3 `answers.redacted.json`, `onepaper.redacted.json`, `llm_trace.redacted.json`이 생성된다.
6. DynamoDB item에 `responses`, `question_results`, `onepager`, `doctor_review`, `patient_guide`가 없어야 한다.
7. `GET /onepager/{id}`가 S3 artifact를 읽어 화면용 payload를 반환한다.
8. `POST /doctor-response` 후 S3 `doctor_review.redacted.json`, `patient_guide.redacted.json`이 생성된다.
9. `GET /guide/{id}`가 환자 안내문 payload를 반환한다.

---

## 12. 자주 보는 오류

| 증상 | 원인 | 확인 |
| --- | --- | --- |
| `ARTIFACTS_BUCKET environment variable is required` | SAM parameter 또는 Lambda env 누락 | CloudFormation parameter, Lambda 환경 변수 확인 |
| `AccessDenied` on S3 | Lambda role에 artifact bucket 권한 없음 | IAM policy의 bucket ARN 확인 |
| Bedrock 호출 실패 | 모델 접근 권한 없음 또는 region 불일치 | Bedrock model access, region 확인 |
| Transcribe 연결 실패 | HTTPS/마이크 권한/Streaming URL 문제 | 브라우저 권한, `/transcribe-stream-url` 응답 확인 |
| validation 422 | LLM JSON이 schema/source_quote 검증 실패 | response의 validation error와 S3 trace 확인 |
| 원페이퍼가 비어 있음 | 아직 답변 artifact가 없거나 `/process-answer` 실패 | S3 `answers.redacted.json`, CloudWatch Logs 확인 |

---

## 13. Git에 포함하지 않는 파일

다음 파일은 로컬 산출물 또는 민감 설정이므로 Git에 포함하지 않습니다.

```text
backend/serverless/.aws-sam/
backend/serverless/samconfig.toml
frontend/node_modules/
frontend/dist/
frontend/.env
frontend/.env.local
.env
.env.local
*.zip
```

---

## 14. 참고 문서

- [../../README.md](../../README.md)
- [../README.md](../README.md)
- [../../docs/LANGGRAPH_PIPELINE.md](../../docs/LANGGRAPH_PIPELINE.md)
- [../../docs/DATA_SCHEMA.md](../../docs/DATA_SCHEMA.md)
- [../../docs/SECURITY_DATA_INVENTORY.md](../../docs/SECURITY_DATA_INVENTORY.md)
- [../../docs/DEPLOYMENT.md](../../docs/DEPLOYMENT.md)

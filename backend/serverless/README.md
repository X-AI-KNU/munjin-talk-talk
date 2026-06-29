# 문진톡톡 서버리스 백엔드 (AWS SAM)

AWS Serverless Application Model(SAM) 기반으로 배포되는 문진톡톡의 핵심 백엔드 서비스입니다. 

Amazon API Gateway(HTTP API)와 AWS Lambda(Python 3.12)를 중심으로 DynamoDB, S3, Amazon Transcribe Streaming, Amazon Bedrock, Amazon Titan Embeddings를 유기적으로 결합하여 서버리스 AI 문진 분석 파이프라인을 구동합니다.

---

## 1. 인프라 아키텍처 구성

| AWS 서비스 | 주요 역할 및 적용 스택 |
| --- | --- |
| **API Gateway (HTTP API)** | 프론트엔드 라우팅 및 초저지연 REST API 요청 수신 |
| **AWS Lambda (Python 3.12)** | 세션 제어, 답변 수합, LangGraph 분석 엔진 구동, 원페이퍼/안내문 산출 |
| **Amazon DynamoDB** | 문진 세션의 경량 상태값(State) 및 S3 산출물 포인터 초고속 조회 |
| **Amazon S3** | PII 가명처리된 비식별 문진 데이터 및 중간 추론 Trace 아카이빙 |
| **Amazon Transcribe Streaming** | 서버 스토리지에 파일 저장이 없는 실시간 스트리밍 STT |
| **Amazon Bedrock** | 문맥 표준화, 의미 추출, 원페이퍼/안내문 생성용 LLM 추론 (Nova Pro/Lite) |
| **Amazon Titan Embeddings** | 표준 증상 문서 매칭을 위한 고차원 텍스트 벡터 임베딩 생성 |

---

## 2. 핵심 아키텍처 설계 원칙

1. **일괄 제출 기반 처리:** 환자의 문진 답변(Q1~Q4)은 개별 전송되지 않고, 최종 입력 완료 시점에 `/process-answers` 엔드포인트로 일괄 수합됩니다.
2. **Non-Blocking UX:** 무거운 LLM 분석 연산과 환자 화면 전환을 완전히 분리하여, 환자는 답변 제출 즉시 대기 시간 없이 완료 화면으로 이동합니다.
3. **이벤트 기반 비동기 실행:** API 핸들러는 답변을 저장한 직후, Lambda 자기 자신을 `Event Invocation(비동기)` 방식으로 호출하여 백그라운드 분석을 트리거합니다.
4. **엄격한 스키마 통제:** LLM이 생성한 모든 결과물은 사전에 정의된 Pydantic 엄격 스키마와 원문 기반 근거 대조(Source Quote Validator)를 통과해야만 유효 데이터로 확정됩니다.
5. **다층 파이프라인 검색:** 증상 매칭은 `BM25(키워드)` + `Titan Vector(의미)` + `Label Signal` 스코어링 융합과 Linker Validator 검증을 거칩니다.
6. **PII 최소화 및 간접 참조:** DynamoDB 상태 테이블에는 환자의 문진 원문을 텍스트로 저장하지 않으며, S3에 가명 처리되어 저장된 파일의 Object Key만 포인터로 유지합니다.
7. **Zero-Storage 음성 보안:** 전송된 음성 스트림은 STT 변환 즉시 메모리에서 소멸하며, 스토리지에 음성 원본(`.wav` 등)을 일절 남기지 않습니다.

---

## 3. REST API 규격

| Method | Path | 설명 | 인증 권한 |
| :---: | --- | --- | :---: |
| `POST` | `/auth/login` | 직원 및 의사 접근 코드 기반 로그인 토큰 발급 | 없음 |
| `POST` | `/sessions` | 신규 문진 접수 세션 생성 | 직원 |
| `GET` | `/sessions/{session_id}` | 특정 세션의 진행 상태 및 세부 정보 조회 | 세션/직원/의사 |
| `GET` | `/sessions` | 당일 생성된 전체 접수 세션 목록 조회 | 직원 |
| `POST` | `/process-answers` | Q1~Q4 답변 일괄 저장 및 비동기 분석 큐 등록 | 환자 세션 |
| `POST` | `/process-answer` | *(단일 문항 레거시 및 회귀 테스트용 보조 API)* | 환자 세션 |
| `POST` | `/transcribe/stream-url` | Transcribe Streaming용 WebSocket Presigned URL 발급 | 환자 세션 |
| `GET` | `/doctor/queue` | 의료진 진료 대기열 목록 조회 | 의사 |
| `GET` | `/onepaper/{session_id}` | 의료진용 최종 정제 원페이퍼 데이터 조회 | 의사 |
| `POST` | `/doctor-response` | 진료 후 의사의 소견 및 지시사항 답변 저장 | 의사 |
| `POST` | `/doctor/reanalyze` | 저장된 의사 답변을 바탕으로 AI 파이프라인 재분석 트리거 | 의사 |
| `GET` | `/guide/{session_id}` | 환자 눈높이 맞춤형 진료 안내문 조회 | 세션/직원/의사 |

*(참고: 실제 라우터 핸들러 매핑은 `handler.py`를 기준으로 작동합니다.)*

---

## 4. 디렉터리 구성

```text
serverless/
├── template.yaml              # AWS SAM 인프라 규격 정의서
├── README.md
├── src/
│   ├── handler.py             # API Gateway 진입점 핸들러
│   ├── security.py            # JWT 토큰 생성 및 권한 검증
│   ├── settings.py            # 런타임 환경 변수 로더
│   ├── orchestration.py       # 비동기 분석 오케스트레이션 및 리트라이 제어
│   ├── sessions.py            # DynamoDB 세션 상태 CRUD
│   ├── artifact_store.py      # S3 아티팩트 입출력 인터페이스
│   ├── artifact_policy.py     # 산출물 비식별화 및 보존 정책
│   ├── privacy.py             # PII 정규표현식 마스킹 유틸리티
│   ├── audio.py               # Transcribe Presigned URL 발급기
│   ├── pipeline_graph.py      # LangGraph 워크플로우 명세
│   ├── pipeline_nodes.py      # LangGraph 그래프 노드 단위 로직
│   ├── pipeline_state.py      # 파이프라인 상태 제어 타입 정의
│   ├── pipeline_trace.py      # 단계별 추론 로그 수집기
│   ├── langchain_prompting.py # LLM 프롬프트 템플릿 모음
│   ├── llm.py                 # Amazon Bedrock Wrapper
│   ├── rag_context.py         # RAG 문맥 통합 검색기
│   ├── dialect_rag.py         # 강원 방언 -> 표준어 변환 RAG
│   ├── retrieval.py           # Hybrid IR 검색 엔진 코어
│   ├── retrieval_documents.py # 의학 백과 파싱 로직
│   ├── retrieval_embeddings.py# 벡터 임베딩 생성기
│   ├── retrieval_scoring.py   # RRF 및 융합 스코어링 계산기
│   ├── onepager.py            # 원페이퍼 JSON 조립기
│   ├── onepager_sections.py   # 원페이퍼 세부 파트 구성
│   ├── onepager_review.py     # 원페이퍼 안전성 검토 로직
│   ├── guide.py               # 환자 안내문 텍스트 생성기
│   ├── schemas/               # Pydantic 데이터 검증 스키마
│   └── data/                  # 정적 참조 인덱스 배치 경로
└── tests/                     # Pytest 검증 스크립트
```

---

## 5. 환경 변수

| 변수명 | 설명 | 기본값 / 예시 |
| --- | --- | --- |
| `SESSIONS_TABLE` | DynamoDB 세션 테이블명 | `MunjinSessions` |
| `ARTIFACTS_BUCKET` | S3 산출물 저장 버킷명 | - |
| `STAFF_ACCESS_CODE` | 현장 직원 전용 접근 코드 | *(하위 호환: `STAFF_ACCESS_TOKEN`)* |
| `DOCTOR_ACCESS_CODE` | 의료진 전용 접근 코드 | *(하위 호환: `DOCTOR_ACCESS_TOKEN`)* |
| `AUTH_SIGNING_SECRET` | 세션 JWT 서명용 대칭키 Secret | *(고엔트로피 긴 난수 권장)* |
| `AUTH_TOKEN_TTL_MINUTES` | 로그인 세션 토큰 유지 시간(분) | `720` |
| `ALLOWED_ORIGINS` | CORS 허용 프론트엔드 출처 | `https://*.amplifyapp.com` |
| `DOMAIN_PACK` | 진료 특화 도메인팩 식별자 | `respiratory` |
| `QUESTION_SET` | 문진 세트 식별자 | `default` |
| `DIALECT_PACK` | 사투리 해독 방언팩 식별자 | `dialect_kangwon` |
| `DIALECT_TOP_K` | 방언 RAG 검색 후보 수 | `3` |
| `LIGHT_MODEL_ID` | 고속 포맷팅용 Bedrock 모델 ID | `amazon.nova-lite-v1:0` |
| `STRONG_MODEL_ID` | 심층 추론용 Bedrock 모델 ID | `amazon.nova-pro-v1:0` |
| `REVIEWER_MODEL_ID`| 교차 검증용 LLM 모델 ID | - |
| `GUIDE_MODEL_ID`   | 안내문 작성용 LLM 모델 ID | - |
| `EMBEDDING_MODEL_ID`| 임베딩 생성 모델 ID | `amazon.titan-embed-text-v2:0` |
| `EMBEDDING_DIMENSIONS`| 임베딩 벡터 차원 수 | `512` |
| `S3_SERVER_SIDE_ENCRYPTION` | S3 서버 측 암호화 프로토콜 | `AES256` 또는 `aws:kms` |
| `S3_KMS_KEY_ID`    | KMS 고객 관리형 키 ARN | *(비어 있을 시 SSE-S3 적용)* |
| `CUSTOM_VOCABULARY`| Transcribe 의료 전문 어휘 집합명 | *(비어 있을 시 기본 사전 사용)* |

---

## 6. AWS SAM 빌드 및 배포 가이드

### Step 1. 빌드 (Build)

```powershell
cd backend/serverless
$env:SAM_CLI_TELEMETRY="0"
sam build
```

### Step 2. 클라우드 배포 (Deploy)

> 💡 **PowerShell 배포 시 주의사항:** `CustomVocabularyName` 파라미터를 빈 값으로 배포할 때 `""` 형태로 입력하면 셸 파싱 오류가 발생할 수 있습니다. 공백으로 둘 경우 해당 파라미터 줄을 생략하거나, `sam deploy --guided` 실행 시 Enter로 통과시키십시오.

```powershell
sam deploy `
  --stack-name munjin-mvp-backend `
  --region ap-northeast-2 `
  --capabilities CAPABILITY_IAM `
  --resolve-s3 `
  --parameter-overrides `
    SessionsTableName=MunjinSessions `
    ArtifactsBucketName=<s3-artifact-bucket-name> `
    LambdaRoleArn=<lambda-role-arn> `
    CorsAllowOrigin=https://<amplify-branch-domain> `
    StaffAccessToken=<직원접근코드> `
    DoctorAccessToken=<의료진접근코드> `
    AuthSigningSecret=<긴난수>
```

배포 완료 후 터미널에 출력되는 `ApiEndpoint` 값을 프론트엔드 환경 변수(`VITE_API_BASE_URL`)에 입력합니다.

---

## 7. ⚠️ 필수 런타임 데이터 배치 가이드

본 프로젝트는 의학 백과 원천 데이터의 저작권 및 이용 범위 보호를 위해 핵심 인덱스 파일을 Git 공개 저장소에서 제외했습니다. 

로컬 파이프라인 테스트 및 클라우드 Lambda 정상 구동을 위해, **배포 전 반드시 아래 3개의 파일을 `src/data/` 경로에 수동으로 배치해야 합니다.**

```text
src/data/diseases_cleaned.json
src/data/symptom_index.json
src/data/symptom_embeddings_amazon.titan-embed-text-v2_0_512.json
```
*(데이터셋 스펙 및 생성 기준은 [src/data/README.md](src/data/README.md)를 참고하십시오.)*

---

## 8. 권장 인프라 보안 및 운영 설정

| AWS 서비스 | 핵심 권장 설정 모음 |
| --- | --- |
| **Amplify** | WAF 방화벽 연동, SPA 라우팅 Rewrite 설정, 환경 변수 주입 |
| **API Gateway** | 엄격한 CORS Origin 제한, API Throttling(Rate Limit) 설정 |
| **Lambda** | 환경 변수 암호화 확인, CloudWatch Log Retention 기간 지정(예: 14일) |
| **DynamoDB** | TTL 속성(`expires_at`) 활성화, 삭제 방지(Deletion Protection) 켜기 |
| **S3** | Public Access 차단, Lifecycle 규칙(3일 후 삭제) 적용, SSE 암호화 |
| **Macie** | S3 아티팩트 버킷 내 미등록 PII 존재 여부 상시 감지 |
| **CloudTrail** | API 호출 인프라 감사 로그 기록 |
| **Organizations**| AWS AI Services Opt-out 정책 활성화 (데이터 학습 이용 원천 차단) |

---

## 9. 최소 권한 원칙(PoLP) 기반 IAM 정책

Lambda 실행 역할(Execution Role)에 부여되어야 하는 권한 범위입니다. 보안을 위해 와일드카드(`*`) 대신 생성된 리소스의 ARN을 직접 기입하십시오.

- **DynamoDB:** `GetItem`, `PutItem`, `UpdateItem`, `Query`, `Scan`
- **S3:** `GetObject`, `PutObject`
- **Bedrock:** `bedrock:InvokeModel`
- **Transcribe:** Streaming Presigned URL 발급 권한
- **Lambda:** 자기 자신에 대한 비동기 호출(`lambda:InvokeFunction`) 권한
- **CloudWatch Logs:** 로그 그룹 생성 및 스트림 쓰기 권한

---

## 10. 로컬 테스트 및 검증

문진톡톡 백엔드는 `tests/` 아래 28개 Pytest 스위트로 파이프라인 각 단계를 검증합니다. 실제 Bedrock/IR/저장 호출은 monkeypatch seam으로 대체되므로 **AWS 자격 증명이나 비공개 런타임 데이터 없이도 단위·통합 테스트가 실행**됩니다. 각 테스트가 `src/` 경로를 자동으로 `sys.path`에 추가하므로 `backend/serverless` 디렉터리에서 실행하면 됩니다.

### 10.1 빠른 실행

```bash
cd backend/serverless
python -m compileall src        # 문법/임포트 컴파일 점검
python -m pytest tests/ -q       # 전체 테스트
sam validate                     # SAM 템플릿 유효성 검사
```

<details>
<summary>Windows PowerShell</summary>

```powershell
cd backend/serverless
$env:SAM_CLI_TELEMETRY="0"       # Telemetry 권한 오류 방지
python -m compileall src
python -m pytest tests/ -q
sam validate
```
</details>

### 10.2 자주 쓰는 Pytest 옵션

```bash
python -m pytest tests/ -v                          # 상세 결과
python -m pytest tests/test_pipeline_graph.py        # 특정 파일만
python -m pytest tests/ -k "safety or privacy"       # 이름으로 필터
python -m pytest tests/ -x                            # 첫 실패 시 중단
python -m pytest tests/ --lf                          # 직전 실패만 재실행
```

### 10.3 테스트 스위트 구성

| 영역 | 테스트 파일 | 확인하는 것 |
| --- | --- | --- |
| 파이프라인/오케스트레이션 | `test_pipeline_graph.py`, `test_orchestration.py`, `test_orchestration_continuation.py` | 입력검증→안전감지→사투리→RAG→추출→검증→IR→저장→응답까지 그래프가 끝까지 흐르는지, 비동기 재개 흐름 |
| 스키마/원문 검증 | `test_extraction_schema.py`, `test_schema_and_artifact_policy.py`, `test_schema_slots.py` | Pydantic 필수 필드·enum·`source_quote` grounding, 재시도 트리거 |
| 임상 상태/Hybrid IR | `test_clinical_state.py`, `test_clinical_terms.py`, `test_retrieval_query.py`, `test_retrieval_scoring.py`, `test_ir_noise_and_safety.py`, `test_symptom_rescue.py` | 증상 상태 필터, BM25+Vector 스코어링, 잡음·안전 플래그, 증상 복원 |
| 사투리 RAG | `test_dialect_rag.py` | 강원 방언 → 표준어 정규화, 원문 보존 |
| 도메인/문항 설정 | `test_domain_and_question_config.py`, `test_domain_data_and_fewshots.py`, `test_question_sets.py` | 도메인팩·질문셋·fewshot 로딩 정합성 |
| 프라이버시/보안 | `test_privacy_masking.py`, `test_privacy_redaction.py`, `test_security.py`, `test_artifact_policy.py`, `test_artifact_store.py` | PII 마스킹·가명처리, 접근 코드/토큰 검증, 산출물 비식별 정책 |
| 원페이퍼/안내문 | `test_onepager_review_fallback.py`, `test_onepager_sections.py`, `test_guide_completion.py` | 원페이퍼 조립·검토 fallback, 환자 안내문 생성 |
| 프롬프트 골든 | `test_prompts_golden.py` | 프롬프트 템플릿이 골든 픽스처(`tests/fixtures/prompts_golden.json`)와 일치하는지 |
| 세션/플로우 | `test_dummy_patient_flow.py`, `test_sessions_queue.py` | 환자 더미 플로우, 세션 대기열 상태 전이 |
| 유틸 | `test_utils.py` | 공통 유틸 함수 |

> `langgraph` 미설치 환경에서는 `pytest.importorskip("langgraph")`로 그래프 테스트가 자동 skip되며 나머지 단위 테스트는 그대로 실행됩니다.

### 10.4 커버리지 측정 (선택)

```bash
pip install pytest-cov
python -m pytest tests/ --cov=src --cov-report=term-missing
```

### 10.5 프론트엔드 테스트 (참고)

프론트엔드는 Vitest를 사용합니다. 백엔드와 별도로 실행합니다.

```bash
cd frontend
npm install
npm run test                     # vitest run (단일 실행)
```

---

## 11. 배포 검증 체크리스트 (Smoke Test)

- [ ] `/auth/login` 엔드포인트를 통한 직원/의사 접근 코드 검증 정상 통과
- [ ] `/sessions` 호출 시 신규 접수 세션 생성 성공
- [ ] 환자 Q1~Q4 제출 시 `/process-answers`가 즉각적인 200 OK 반환
- [ ] DynamoDB의 세션 `status`가 `analysis_pending`으로 즉시 변경됨
- [ ] 백그라운드 Lambda 실행 후 상태가 `waiting_doctor` 또는 `needs_priority`로 전환됨
- [ ] S3 아티팩트 버킷에 비식별 처리된(`*.redacted.json`) 결과 파일 생성 완료
- [ ] 분석 완료 전 진입 시 의료진 원페이퍼 화면에 '분석 중' 상태 알림 정상 표시
- [ ] 분석 완료 후 증상, 환자 원문, 문진 요약, 확인 항목, EMR 초안 정상 렌더링
- [ ] 의사 코멘트 저장 이후 환자용 안내문 데이터 조회 성공

---

## 12. `.gitignore` 주요 대상

본 저장소에 커밋되지 않도록 통제되는 파일 목록입니다.

```text
.aws-sam/
samconfig.toml
src/data/diseases_cleaned.json
src/data/symptom_index.json
src/data/symptom_embeddings_*.json
__pycache__/
.pytest_cache/
```

---

## 13. 트러블슈팅 가이드

| 증상 | 주요 원인 | 체크 포인트 |
| --- | --- | --- |
| **원페이퍼가 계속 생성 중 상태임** | 백그라운드 Lambda 실행 실패 또는 Bedrock 모델 호출 권한 부족 | CloudWatch Lambda 로그, DynamoDB `status` 필드 |
| **증상 매칭 결과가 빈 값으로 나옴** | `src/data/` 내의 비공개 인덱스 파일 누락 | 필수 런타임 파일 3종 존재 여부 확인 |
| **브라우저 CORS 차단 에러** | Amplify 출처와 API Gateway 허용 Origin 불일치 | Lambda 환경 변수 `ALLOWED_ORIGINS` 값 대조 |
| **접근 코드 로그인 실패** | 배포 시 주입된 파라미터 값 오타 | Lambda 환경 변수 `STAFF/DOCTOR_ACCESS_CODE` 대조 |
| **SAM Deploy 파라미터 에러** | PowerShell의 빈 문자열(`""`) 파싱 오류 | 파라미터 생략 후 `sam deploy --guided` 실행 |

---

## 14. 관련 문서 모음

- [루트 프로젝트 소개](../../README.md)
- [백엔드 상위 아키텍처](../README.md)
- [데이터 스키마 명세서](../../docs/DATA_SCHEMA.md)
- [LangGraph 파이프라인 구조](../../docs/LANGGRAPH_PIPELINE.md)
- [도메인 인덱스 데이터 가이드](src/data/README.md)

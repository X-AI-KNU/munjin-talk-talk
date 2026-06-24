# 문진톡톡 Serverless Backend

AWS SAM으로 배포하는 문진톡톡 백엔드입니다. API Gateway HTTP API와 Lambda Python 3.12를 중심으로 DynamoDB, S3, Transcribe Streaming, Bedrock, Titan Embeddings를 사용합니다.

---

## 1. 배포 구성

| AWS 서비스 | 역할 |
| --- | --- |
| API Gateway HTTP API | 프론트엔드 요청 수신 |
| Lambda | 세션 관리, 문진 답변 저장, LangGraph 분석, 원페이퍼/안내문 처리 |
| DynamoDB | 최소 세션 상태와 S3 artifact pointer 저장 |
| S3 | 가명처리된 운영 artifact 저장 |
| Amazon Transcribe Streaming | 음성 파일 저장 없는 STT |
| Amazon Bedrock | Nova Pro/Lite LLM 호출 |
| Amazon Titan Embeddings | 증상 문서 vector embedding |

---

## 2. 주요 처리 원칙

1. 환자 문진은 Q1~Q4를 모두 받은 뒤 `/process-answers`로 일괄 저장합니다.
2. 환자는 LLM 분석을 기다리지 않고 완료 화면으로 이동합니다.
3. Lambda는 async invocation으로 백그라운드 분석을 수행합니다.
4. LLM 출력은 Pydantic schema와 source quote validator를 통과해야 합니다.
5. 증상 매칭은 BM25 + Titan Vector + label signal + linker validator를 거칩니다.
6. DynamoDB에는 전체 문진 원문을 저장하지 않고 S3 artifact key만 저장합니다.
7. 음성 원본 파일은 저장하지 않습니다.

---

## 3. API 목록

| Method | Path | 설명 | 인증 |
| --- | --- | --- | --- |
| `POST` | `/auth/login` | 직원/의사 접근 코드 로그인 | 없음 |
| `POST` | `/sessions` | 접수 세션 생성 | 직원 |
| `GET` | `/sessions/{session_id}` | 세션 조회 | 세션/직원/의사 |
| `GET` | `/sessions` | 오늘 접수 목록 조회 | 직원 |
| `POST` | `/process-answers` | Q1~Q4 답변 일괄 저장, 분석 큐 등록 | 환자 세션 |
| `POST` | `/process-answer` | 단일 문항 처리 호환 endpoint | 환자 세션 |
| `POST` | `/transcribe/stream-url` | Transcribe Streaming presigned URL 발급 | 환자 세션 |
| `GET` | `/doctor/queue` | 의사 대기열 | 의사 |
| `GET` | `/onepaper/{session_id}` | 원페이퍼 조회 | 의사 |
| `POST` | `/doctor-response` | 의사 답변 저장 | 의사 |
| `POST` | `/doctor/reanalyze` | 저장된 답변으로 AI 재분석 | 의사 |
| `GET` | `/guide/{session_id}` | 환자 안내문 조회 | 세션/직원/의사 |

실제 route 이름은 `handler.py`를 기준으로 확인합니다.

---

## 4. 폴더 구조

```text
serverless/
├── template.yaml
├── README.md
├── src/
│   ├── handler.py
│   ├── auth.py
│   ├── settings.py
│   ├── orchestration.py
│   ├── sessions.py
│   ├── artifact_store.py
│   ├── artifact_policy.py
│   ├── privacy.py
│   ├── audio.py
│   ├── pipeline_graph.py
│   ├── pipeline_nodes.py
│   ├── pipeline_state.py
│   ├── pipeline_trace.py
│   ├── langchain_prompting.py
│   ├── llm.py
│   ├── rag_context.py
│   ├── dialect_rag.py
│   ├── retrieval.py
│   ├── retrieval_documents.py
│   ├── retrieval_embeddings.py
│   ├── retrieval_scoring.py
│   ├── onepager.py
│   ├── onepager_sections.py
│   ├── onepager_review.py
│   ├── guide.py
│   ├── schemas/
│   └── data/
└── tests/
```

---

## 5. 환경 변수

| 변수 | 설명 |
| --- | --- |
| `SESSIONS_TABLE` | DynamoDB table name |
| `ARTIFACT_BUCKET` | S3 artifact bucket name |
| `STAFF_ACCESS_TOKEN` | 직원 접근 코드 |
| `DOCTOR_ACCESS_TOKEN` | 의료진 접근 코드 |
| `AUTH_SIGNING_SECRET` | 로그인 세션 토큰 서명 secret |
| `CORS_ALLOW_ORIGIN` | 허용할 Amplify origin |
| `USE_BEDROCK_LLM` | Bedrock LLM 사용 여부 |
| `ENABLE_BEDROCK_REVIEW` | 원페이퍼 review LLM 사용 여부 |
| `ENABLE_BEDROCK_GUIDE` | 환자 안내문 LLM 사용 여부 |
| `LIGHT_MODEL_ID` | Nova Lite model id |
| `STRONG_MODEL_ID` | Nova Pro model id |
| `REVIEWER_MODEL_ID` | review LLM model id |
| `GUIDE_MODEL_ID` | guide LLM model id |
| `CUSTOM_VOCABULARY` | Transcribe custom vocabulary name, 없으면 빈 값 |

접근 코드는 사람이 외울 수 있는 값으로 운영 환경에서 설정하고, `AUTH_SIGNING_SECRET`은 긴 난수로 유지합니다.

---

## 6. SAM 배포

### 1단계: 빌드

```powershell
cd C:\Users\CGB\munjin-talk-talk-mvp\backend\serverless
$env:SAM_CLI_TELEMETRY="0"
sam build
```

### 2단계: 배포

`CustomVocabularyName`을 비워 배포하는 경우 PowerShell에서 `CustomVocabularyName=""` 형식은 오류가 날 수 있습니다. 빈 값으로 배포할 때는 `CustomVocabularyName=` 항목을 생략하거나 `sam deploy --guided`에서 Enter로 비워 둡니다.

```powershell
sam deploy `
  --stack-name munjin-mvp-backend `
  --region ap-northeast-2 `
  --capabilities CAPABILITY_IAM `
  --resolve-s3 `
  --parameter-overrides `
    SessionsTableName=MunjinSessions `
    ArtifactsBucketName=munjin-mvp-artifacts-cgb-289984444869-ap-northeast-2-an `
    LambdaRoleArn=arn:aws:iam::289984444869:role/munjin-lambda-role `
    CorsAllowOrigin=https://main.dv5herezqtt1t.amplifyapp.com `
    StaffAccessToken=<직원접근코드> `
    DoctorAccessToken=<의료진접근코드> `
    AuthSigningSecret=<긴난수>
```

배포 후 출력되는 `ApiEndpoint`를 Amplify 환경 변수 `VITE_API_BASE_URL`에 넣습니다.

---

## 7. 런타임 데이터 배치

공개 저장소에는 저작권 또는 이용 범위 검토가 필요한 원천 의료 백과 데이터와 파생 인덱스가 포함되지 않습니다. 배포 전 아래 파일을 `src/data/`에 배치해야 Hybrid IR이 정상 동작합니다.

```text
src/data/diseases_cleaned.json
src/data/symptom_index.json
src/data/symptom_embeddings_amazon.titan-embed-text-v2_0_512.json
```

자세한 기준은 [src/data/README.md](src/data/README.md)를 확인합니다.

---

## 8. AWS 콘솔 운영 설정

| 영역 | 권장 설정 |
| --- | --- |
| Amplify | WAF 활성화, SPA rewrite, `VITE_API_BASE_URL` 설정 |
| API Gateway | CORS origin 제한, throttling |
| Lambda | 환경 변수 확인, CloudWatch log retention 설정 |
| DynamoDB | TTL 속성 `expires_at`, 삭제 방지, 암호화 기본 활성 |
| S3 | public access block, lifecycle 3일 삭제, server-side encryption |
| Macie | artifact bucket 민감정보 탐지 |
| CloudTrail | 관리 이벤트 기록 |
| GuardDuty | 위협 탐지 활성화 |
| Security Hub | 보안 통합 대시보드 |
| Organizations | AI Services opt-out policy |

---

## 9. Lambda IAM 권한

Lambda role에는 최소한 다음 권한이 필요합니다.

| 서비스 | 필요 권한 |
| --- | --- |
| DynamoDB | `GetItem`, `PutItem`, `UpdateItem`, `Query`, `Scan` |
| S3 | `GetObject`, `PutObject` |
| Bedrock | `bedrock:InvokeModel` |
| Transcribe | streaming presigned URL 발급에 필요한 권한 |
| Lambda | 자기 자신 async invoke 권한 |
| CloudWatch Logs | 로그 작성 |

가능하면 resource ARN을 실제 table, bucket, Lambda function으로 제한합니다.

---

## 10. 로컬 검증

```powershell
cd C:\Users\CGB\munjin-talk-talk-mvp\backend\serverless
python -m compileall src
python -m pytest tests/ -q
sam validate
```

SAM CLI telemetry 권한 오류가 나면:

```powershell
$env:SAM_CLI_TELEMETRY="0"
```

---

## 11. 최종 동작 확인 기준

- `/auth/login`에서 직원/의사 접근 코드가 정상 검증됨
- `/sessions`로 세션 생성 가능
- 환자 Q1~Q4 완료 후 `/process-answers`가 즉시 성공 응답
- DynamoDB status가 `analysis_pending`으로 바뀜
- 백그라운드 분석 후 `waiting_doctor` 또는 `needs_priority`로 전환
- S3에 redacted artifact가 생성됨
- 원페이퍼가 준비되기 전에는 의사 화면에서 분석 중 상태 표시
- 원페이퍼 준비 후 증상, 원문, 문진 요약, 확인 항목, EMR 초안 표시
- 의사 답변 저장 후 환자 안내문 조회 가능

---

## 12. Git 제외 파일

다음 항목은 공개 저장소에 올리지 않습니다.

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

## 13. 자주 보는 오류

| 증상 | 원인 | 확인 |
| --- | --- | --- |
| 원페이퍼가 계속 생성 중 | 백그라운드 Lambda 실패 또는 Bedrock 권한 문제 | CloudWatch log, DynamoDB status |
| 증상 매칭이 비어 있음 | 비공개 IR 데이터 누락 | `src/data/README.md`의 필수 파일 |
| CORS 오류 | Amplify URL과 `CORS_ALLOW_ORIGIN` 불일치 | Lambda 환경 변수, API Gateway CORS |
| 접근 코드 로그인 실패 | 환경 변수 값 또는 배포 stack 불일치 | Lambda 환경 변수, CloudFormation stack |
| SAM deploy parameter 오류 | 빈 문자열 parameter 형식 문제 | `sam deploy --guided` 사용 또는 해당 parameter 생략 |

---

## 14. 참고 문서

- [../../README.md](../../README.md)
- [../README.md](../README.md)
- [../../docs/DATA_SCHEMA.md](../../docs/DATA_SCHEMA.md)
- [../../docs/LANGGRAPH_PIPELINE.md](../../docs/LANGGRAPH_PIPELINE.md)
- [src/data/README.md](src/data/README.md)

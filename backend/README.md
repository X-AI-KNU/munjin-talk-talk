# 문진톡톡 백엔드

문진톡톡 백엔드는 환자 음성 문진 텍스트를 구조화하고, 의료진 원페이퍼와 환자 안내문으로 이어지는 서버 측 처리를 담당합니다. 현재 배포 대상은 `backend/serverless`이며, AWS API Gateway, Lambda, DynamoDB, S3 artifact bucket, Amazon Transcribe Streaming, Amazon Bedrock, Amazon Titan Text Embeddings를 사용합니다.

이 백엔드는 LLM 결과를 그대로 저장하지 않습니다. 모든 LLM 출력은 fixed schema, enum, 원문 quote 검증을 통과해야 하며, 증상 매칭은 원천 JSON 기반 Hybrid IR을 통과해야 합니다.

---

## 백엔드 책임 범위

| 영역 | 책임 |
| --- | --- |
| 세션 관리 | 접수처에서 생성한 문진 세션의 최소 상태와 S3 pointer를 DynamoDB에 저장하고 조회 |
| 음성 인식 연결 | 환자 음성 저장 없이 Transcribe Streaming presigned URL 발급 |
| RAG 참고 컨텍스트 | 원천 JSON과 제한 alias bridge에서 LLM 표준화 참고 문맥 검색 |
| LLM extraction | Bedrock Nova로 환자 발화의 의미 단위, 표준화, 질문, 단서 추출 |
| Schema validation | Pydantic으로 JSON 구조, enum, quote grounding 검증 |
| Hybrid IR | LLM 증상 후보를 BM25 + Titan Vector로 표준 증상명에 매칭 |
| 원페이퍼 생성 | 증상, 문맥, 환자 질문, 확인 항목, EMR 초안 조립 |
| 환자 안내문 | 의사 답변을 환자용 안내문 JSON으로 구성 |
| Artifact 저장 | 문진 답변, 원페이퍼, 의사 답변, 안내문, trace를 S3에 가명처리 JSON으로 저장 |

백엔드는 진단명 추천, 처방 결정, 질병 예측을 수행하지 않습니다.

---

## 폴더 구조

```text
backend/
├── README.md
└── serverless/
    ├── README.md
    ├── template.yaml
    └── src/
        ├── handler.py
        ├── settings.py
        ├── artifact_store.py
        ├── privacy.py
        ├── sessions.py
        ├── audio.py
        ├── orchestration.py
        ├── pipeline_graph.py
        ├── pipeline_nodes.py
        ├── pipeline_state.py
        ├── pipeline_trace.py
        ├── rag_context.py
        ├── extraction_prompts.py
        ├── extraction_schema.py
        ├── langchain_prompting.py
        ├── llm.py
        ├── retrieval.py
        ├── retrieval_documents.py
        ├── retrieval_embeddings.py
        ├── retrieval_scoring.py
        ├── clinical_terms.py
        ├── domain_config.py
        ├── onepager.py
        ├── onepager_sections.py
        ├── onepager_review.py
        ├── guide.py
        ├── schemas/
        └── data/
            ├── domain_pack_respiratory.json
            ├── diseases_cleaned.json
            ├── symptom_index.json
            └── symptom_embeddings_*.json
```

`backend/serverless/.aws-sam/`과 `samconfig.toml`은 로컬 배포 산출물이므로 저장소에 포함하지 않습니다.

---

## 답변 1개 처리 흐름

```text
POST /process-answer
  -> handler.py
  -> orchestration.py
  -> pipeline_graph.py
  -> pipeline_nodes.py
  -> rag_context.py
  -> langchain_prompting.py / llm.py
  -> schemas/extraction.py
  -> retrieval.py
  -> onepager.py
  -> sessions.py
  -> API response
```

상세 단계:

1. `handler.py`가 API Gateway 요청을 받습니다.
2. `/process-answer` 요청은 `orchestration.process_answer()`로 전달됩니다.
3. `orchestration.py`는 LangGraph 파이프라인을 실행합니다.
4. `pipeline_graph.py`는 노드 순서와 조건 분기를 정의합니다.
5. `pipeline_nodes.py`는 각 노드의 실제 처리 함수를 실행합니다.
6. `rag_context_retrieval_node`가 원천 JSON 기반 참고 문맥을 검색합니다.
7. `semantic_extraction_node`가 LangChain Runnable chain으로 Bedrock Nova를 호출합니다.
8. `schema_quote_validation_node`가 `schemas/extraction.py`의 Pydantic schema와 source_quote를 검증합니다.
9. 검증 실패 시 LangGraph가 `semantic_extraction_node`로 되돌려 repair prompt를 실행합니다.
10. 증상 문항이면 `retrieval.py`가 Hybrid IR 매칭을 수행합니다.
11. `onepager.py`가 문항 artifact를 바탕으로 원페이퍼 JSON을 갱신합니다.
12. `artifact_store.py`가 답변/원페이퍼/trace를 S3에 저장합니다.
13. `sessions.py`가 DynamoDB의 상태와 S3 pointer만 갱신합니다.

---

## LangGraph 사용 목적

문진 파이프라인은 단순 함수 호출보다 처리 경로와 분기 기록이 중요합니다. LangGraph는 다음을 명시합니다.

- 노드 실행 순서
- 검증 실패 시 중단 또는 safety branch 분기
- 위험 표현 감지 후 저장 경로
- 각 노드의 trace
- 프론트 응답과 S3 trace artifact에서 확인 가능한 active path

현재 노드:

```text
input_transcript
quick_safety_flag
rag_context_retrieval
semantic_extraction
schema_quote_validation
hybrid_ir_match
session_validation_save
safety_guardrail_save
onepaper_refresh
response_payload
```

관련 파일:

- `serverless/src/pipeline_graph.py`
- `serverless/src/pipeline_nodes.py`
- `serverless/src/pipeline_trace.py`

---

## LangChain 사용 위치

현재 LangChain은 agent framework가 아니라 Runnable chain으로 사용합니다. Bedrock에 전달할 prompt를 `ChatPromptTemplate`로 만들고, boto3 Bedrock 호출을 `RunnableLambda`로 감싼 뒤, `JsonOutputParser`로 JSON을 파싱합니다. 이 Runnable chain은 LangGraph의 `semantic_extraction` 노드 안에서 실행됩니다.

관련 파일:

```text
serverless/src/langchain_prompting.py
serverless/src/llm.py
```

역할:

- Bedrock `converse` API에 맞는 message 구성
- PromptTemplate, Bedrock Runnable, JSON parser를 한 체인으로 연결
- parser 종류와 raw 응답 hash를 운영 artifact가 아닌 최소 설명 trace에 기록
- 향후 dialect RAG, retriever, output parser 확장을 위한 연결 지점 제공

---

## LLM 사용 원칙

원칙:

- LLM extraction은 필수 경로입니다.
- LLM JSON은 fixed schema를 통과해야 합니다.
- `source_quote`와 `original_quote`는 환자 원문에 존재해야 합니다.
- enum 값은 미리 정의된 값만 허용합니다.
- schema에 없는 필드는 거부합니다.
- LLM이 생성한 `score`, `confidence`, `probability`, `risk percentage`는 허용하지 않습니다.
- 검증 실패 시 bounded retry loop를 실행합니다.
- retry 이후에도 실패하면 저장하지 않고 422 응답을 반환합니다.
- 안전 플래그가 있는 경우에는 LLM extraction 실패 중에도 safety-only 저장 경로로 위험 신호만 보존할 수 있습니다.

---

## Deterministic 코드의 위치와 의미

환자 발화 의미 추출은 rule-base로 대체하지 않습니다. 다만 안전 감지와 IR 문서 구성처럼 LLM 판단을 보조·검증하는 deterministic 코드는 남아 있습니다.

| 구분 | 사용 여부 | 설명 |
| --- | --- | --- |
| LLM extraction | 기본 사용 | 실제 문진 의미 추출 |
| Pydantic validation | 항상 사용 | LLM JSON 저장 전 검증 |
| RAG context retrieval | 사용 | 원천 JSON과 제한 alias bridge를 검색해 LLM 표준화 참고 문맥으로 제공. 환자 사실로 직접 채택하지 않음 |
| safety flag rule | 사용 | 객혈, 호흡곤란 등 즉시 직원/의료진 확인이 필요한 표현 감지 |
| IR document build rule | 사용 | 원천 JSON을 검색 문서로 접는 deterministic 변환. 환자 발화에서 증상을 추출하는 로직은 아님 |

위험 표현 감지는 진단 목적이 아니라 문진을 멈추고 직원 또는 의료진 확인을 유도하기 위한 guardrail입니다.

---

## Hybrid IR

증상 매칭은 LLM이 만든 증상 후보를 표준 증상 인덱스와 다시 비교하는 단계입니다.

원천 데이터:

```text
serverless/src/data/diseases_cleaned.json
serverless/src/data/symptom_index.json
```

사전 계산 embedding cache:

```text
serverless/src/data/symptom_embeddings_amazon.titan-embed-text-v2_0_512.json
```

처리:

1. LLM span의 `source_quote`, `normalized_text`, `name`, `slot_ref`를 query로 구성합니다.
2. `symptom_index.json`과 `diseases_cleaned.json`에서 검색 문서를 만듭니다.
3. BM25 lexical score를 계산합니다.
4. Titan embedding cosine similarity를 계산합니다.
5. 표준 증상명과 제한적 alias bridge를 label score로 반영합니다.
6. vector 중심 threshold를 통과한 후보만 운영용 `matched_slots`로 저장합니다.
7. 운영용 답변/원페이퍼 artifact에는 숫자 점수와 후보 목록을 제거합니다.
8. 최소 설명 trace에는 확정된 매칭의 BM25/vector/label/rank 근거 요약만 남깁니다.

의료진 UI에는 숫자 점수를 표시하지 않습니다. 숫자형 score는 내부 계산과 감사용 최소 trace에서만 제한적으로 사용합니다.

---

## 원페이퍼 생성

`onepager.py`는 S3 `answers.redacted.json`에 저장된 문항 결과를 읽어 원페이퍼 JSON을 구성합니다.

주요 섹션:

- `patient_summary`
- `symptom_slots`
- `clinical_clues`
- `agenda`
- `review_items`
- `transfer_text`
- `safety_flags`

`onepager_review.py`는 Q4까지 저장되었거나 safety flag가 있을 때 Nova Pro를 호출해 의료진 확인 항목과 EMR 초안을 다듬습니다. 출력은 `schemas/review.py` 검증을 통과해야 반영됩니다.

---

## 환자 안내문 생성

`guide.py`는 의사 답변과 강조사항을 S3 `doctor_review.redacted.json`에 저장하고, 생성된 환자 안내문을 S3 `patient_guide.redacted.json`에 저장합니다.

처리 원칙:

- 의사 답변은 Nova Lite를 통해 환자용 쉬운 문장으로 변환할 수 있습니다.
- 의사 강조사항은 LLM이 변형하지 않고 그대로 별도 카드에 표시합니다.
- guide LLM 출력은 `schemas/guide.py` 검증을 통과해야 합니다.
- guide LLM이 실패하면 빈 안내문과 실패 사유를 저장하고 validator 실패로 반환합니다.

---

## 데이터 저장

현재 백엔드는 DynamoDB와 S3 artifact bucket을 분리해서 사용합니다.

### DynamoDB에 남는 값

```text
session_id
patient.name
patient.age / patient.age_band
patient.gender
patient.department
patient.doctor
patient.receipt_id
visit_type
status
queue_number
risk
privacy_consent 요약
question_status
artifact.prefix / artifact key
onepager_ready
guide_ready
```

### S3 artifact로 저장되는 값

```text
sessions/YYYY-MM-DD/{session_id}/
  consent.json
  answers.redacted.json
  onepaper.redacted.json
  doctor_review.redacted.json
  patient_guide.redacted.json
  llm_trace.redacted.json
```

### 저장하지 않는 값

```text
환자 음성 원본 파일
환자 실명 원문
생년월일 원문
연락처 원문
```

S3 artifact는 `artifact_store.py`를 통해서만 읽고 씁니다. 저장 직전 `artifact_policy.py`가 운영에 필요한 필드만 남기고, `privacy.py`의 가명처리 helper가 연락처, 주민번호, 이메일, 생년월일 형태의 직접식별정보를 1차 마스킹합니다. 운영 환경에서는 S3 Block Public Access, Lifecycle, KMS, Macie 점검을 함께 적용해야 합니다.

---

## 개발자가 먼저 확인할 파일

| 목적 | 파일 |
| --- | --- |
| API endpoint | `serverless/src/handler.py` |
| 환경 변수와 모델 ID | `serverless/src/settings.py` |
| S3 artifact 저장 | `serverless/src/artifact_store.py` |
| artifact 최소화 정책 | `serverless/src/artifact_policy.py` |
| 개인정보 최소화 | `serverless/src/privacy.py` |
| 전체 파이프라인 | `serverless/src/pipeline_graph.py` |
| 노드별 처리 | `serverless/src/pipeline_nodes.py` |
| trace 구조 | `serverless/src/pipeline_trace.py` |
| RAG 참고 문맥 | `serverless/src/rag_context.py` |
| extraction prompt | `serverless/src/extraction_prompts.py` |
| extraction schema | `serverless/src/schemas/extraction.py` |
| 도메인팩 로딩 | `serverless/src/domain_config.py` |
| 호흡기 도메인팩 | `serverless/src/data/domain_pack_respiratory.json` |
| Hybrid IR | `serverless/src/retrieval.py` |
| IR 문서 생성 | `serverless/src/retrieval_documents.py` |
| IR score 계산 | `serverless/src/retrieval_scoring.py` |
| 원페이퍼 조립 | `serverless/src/onepager.py` |
| 원페이퍼 리뷰 | `serverless/src/onepager_review.py` |
| 환자 안내문 | `serverless/src/guide.py` |
| DynamoDB 상태 저장 | `serverless/src/sessions.py` |
| schema/artifact 회귀 테스트 | `serverless/tests/test_schema_and_artifact_policy.py` |

---

## 검증

Python syntax:

```powershell
py -3.12 -m compileall backend/serverless/src
```

SAM build:

```powershell
cd backend/serverless
sam build
```

Schema/artifact unit test:

```powershell
python -m pip install -r backend/serverless/src/requirements.txt --target .tmp-pydeps
$env:PYTHONPATH="backend/serverless/src;.tmp-pydeps"
python -m unittest discover -s backend/serverless/tests -p "test_*.py"
Remove-Item -LiteralPath .tmp-pydeps -Recurse -Force
```

SAM CLI가 Windows에서 Python runtime을 찾지 못하면 Python 3.12 설치 경로를 `PATH`에 추가해야 합니다.

---

## 관련 문서

- [serverless README](serverless/README.md)
- [프로젝트 구조](../docs/PROJECT_STRUCTURE.md)
- [LangGraph 파이프라인](../docs/LANGGRAPH_PIPELINE.md)
- [내부 JSON 스키마](../docs/DATA_SCHEMA.md)
- [데이터 전수조사 표](../docs/SECURITY_DATA_INVENTORY.md)
- [MVP 실행 가이드](../docs/MVP_SETUP.md)
- [AWS 배포 가이드](../docs/DEPLOYMENT.md)

---

## 보안 주의

현재 MVP 백엔드는 인증과 권한 분리가 없는 상태입니다. 공개 URL에 실제 환자 정보를 입력하면 안 됩니다.

공개 테스트 전 필요 항목:

- Cognito 또는 병원 내부 인증
- 직원/의사 권한 분리
- DynamoDB TTL 또는 삭제 정책
- CloudWatch Logs 보존 기간
- API Gateway throttling
- WAF 또는 IP 제한
- 환자 동의 절차
- 의료정보 처리 기준 검토

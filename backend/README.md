# 문진톡톡 백엔드

문진톡톡 백엔드는 환자가 확인한 Q1~Q4 문진 텍스트를 저장하고, 백그라운드에서 AI 파이프라인을 실행해 의료진 원페이퍼와 환자 안내문을 만드는 서버 측 구성입니다.

배포 대상은 [backend/serverless](serverless/README.md)이며 AWS API Gateway, Lambda, DynamoDB, S3, Amazon Bedrock, Amazon Titan Embeddings를 사용합니다.

관련 문서:

- [루트 README](../README.md)
- [Serverless 배포 가이드](serverless/README.md)
- [LangGraph 파이프라인](../docs/LANGGRAPH_PIPELINE.md)
- [데이터 schema](../docs/DATA_SCHEMA.md)

---

## 1. 책임 범위

| 영역 | 책임 |
| --- | --- |
| 세션 관리 | 접수 세션 상태, 대기 순번, S3 artifact pointer를 DynamoDB에 저장 |
| 음성 처리 | Transcribe Streaming presigned URL 발급. 음성 원본 저장 없음 |
| 답변 저장 | Q1~Q4 확인 텍스트를 일괄 저장하고 `analysis_pending`으로 전환 |
| 백그라운드 분석 | Lambda async invoke로 LangGraph 파이프라인 실행 |
| RAG 문맥 | 강원 방언팩과 도메인팩에서 표준화 참고 문맥 검색 |
| LLM extraction | Bedrock Nova로 표준화, 의미 span, 문진 단서, 환자 질문 추출 |
| Schema validation | Pydantic schema, enum, source_quote grounding 검증 |
| Hybrid IR | BM25, Titan Vector, label signal로 표준 증상 후보 검색 |
| 원페이퍼 | 증상, 원문, 문진 요약, 확인 항목, EMR 초안 생성 |
| 안내문 | 의사 답변과 강조사항을 환자 친화 안내문으로 구성 |
| 저장 정책 | DynamoDB에는 최소 상태, S3에는 redacted artifact 저장 |

백엔드는 진단명 추천, 처방 결정, 질병 예측을 수행하지 않습니다.

---

## 2. 최신 문진 처리 흐름

현재 기본 흐름은 “문항마다 즉시 분석”이 아니라 “Q1~Q4 일괄 저장 후 백그라운드 분석”입니다.

```text
POST /process-answers
  -> Q1~Q4 답변 정규화
  -> S3 answers.redacted.json 저장
  -> DynamoDB status = analysis_pending
  -> 같은 Lambda를 Event invocation으로 비동기 호출
  -> 프론트에는 즉시 patient_complete 응답

Internal background event
  -> Q1~Q4를 순서대로 LangGraph 파이프라인에 입력
  -> quick safety flag
  -> RAG context retrieval
  -> semantic extraction
  -> schema quote validation
  -> Hybrid IR + linker
  -> onepaper refresh
  -> S3 onepaper/trace 저장
  -> DynamoDB status = waiting_doctor 또는 needs_priority
```

환자 UX는 LLM 지연과 분리됩니다. 분석 실패가 발생해도 환자 완료 화면은 유지되고, 의료진 화면에서 재분석 또는 수동 확인을 진행합니다.

---

## 3. 주요 폴더 구조

```text
backend/
├── README.md
└── serverless/
    ├── template.yaml
    ├── README.md
    ├── src/
    │   ├── handler.py
    │   ├── auth.py
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
    │   ├── domain_config.py
    │   ├── question_sets.py
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

## 4. 핵심 파일

| 파일 | 설명 |
| --- | --- |
| `handler.py` | API Gateway route 분기 |
| `auth.py` | 직원/의사 접근 코드 로그인, 세션 토큰 검증 |
| `orchestration.py` | `/process-answers`, background analysis, 재분석 진입점 |
| `sessions.py` | DynamoDB 세션 상태 저장/조회 |
| `artifact_store.py` | S3 redacted artifact 저장/조회 |
| `artifact_policy.py` | 운영 artifact와 trace에서 보존할 최소 필드 정리 |
| `privacy.py` | 환자명 마스킹, 연락처 제거, 개인정보 최소화 |
| `audio.py` | Transcribe Streaming presigned URL 발급 |
| `pipeline_graph.py` | LangGraph 노드와 edge 정의 |
| `pipeline_nodes.py` | 각 노드의 실제 처리 코드 |
| `langchain_prompting.py` | LangChain Runnable prompt/parse chain |
| `llm.py` | Bedrock 호출 wrapper와 model routing |
| `rag_context.py` | 도메인/방언/RAG 참고 문맥 검색 |
| `dialect_rag.py` | 강원 방언팩 기반 표준어 후보 검색 |
| `retrieval*.py` | Hybrid IR 문서 구성, embedding, scoring |
| `onepager*.py` | 원페이퍼 섹션 조립과 review LLM |
| `guide.py` | 환자 안내문 생성 |
| `schemas/` | Pydantic fixed schema |

---

## 5. LangGraph와 LangChain 사용 방식

### LangGraph

LangGraph는 처리 순서와 실패 분기를 명시합니다.

```text
input_transcript
  -> quick_safety_flag
  -> rag_context_retrieval
  -> semantic_extraction
  -> schema_quote_validation
  -> hybrid_ir_match
  -> session_validation_save
  -> onepaper_refresh
  -> response_payload
```

검증 실패 시 bounded retry를 수행하고, 안전 플래그가 있으면 safety-only 저장 경로로 분기합니다.

### LangChain

LangChain은 agent가 아니라 Runnable 조립 도구로 사용합니다.

```text
ChatPromptTemplate
  -> Bedrock boto3 호출을 감싼 RunnableLambda
  -> JsonOutputParser
  -> Pydantic validator
```

즉 LangChain은 prompt와 Bedrock 호출, JSON 파싱을 일관된 chain으로 묶는 역할입니다.

---

## 6. LLM 사용 원칙

- LLM 출력은 fixed schema를 통과해야 저장됩니다.
- `source_quote`와 `original_quote`는 환자 원문에 실제로 존재해야 합니다.
- schema에 없는 필드, 정의되지 않은 enum은 거부합니다.
- LLM이 임의로 만든 `score`, `confidence`, `probability`는 사용하지 않습니다.
- 증상 매칭은 LLM 생성명만 신뢰하지 않고 Hybrid IR 후보와 linker validator를 거칩니다.
- `symptom_absent`, `progress_improved` 같은 비활성 상태는 active symptom으로 올리지 않습니다.

---

## 7. Hybrid IR

운영 IR은 공개 저장소에 포함되지 않는 원천 데이터 3개와 공개 도메인팩을 함께 사용합니다.

필수 비공개 파일:

- `backend/serverless/src/data/diseases_cleaned.json`
- `backend/serverless/src/data/symptom_index.json`
- `backend/serverless/src/data/symptom_embeddings_amazon.titan-embed-text-v2_0_512.json`

검색 흐름:

```text
LLM span
  -> normalized_text + symptom_hint query
  -> BM25 sparse score
  -> Titan vector score
  -> label signal
  -> RRF hybrid fusion
  -> top-k 표준 증상 후보
  -> linker / deterministic validator
```

IR은 확장성을 위해 원천 JSON에서 문서를 구성합니다. 특정 테스트 문장에 맞춘 rule-base alias를 추가하는 구조가 아닙니다.

---

## 8. 저장 구조

| 저장소 | 내용 |
| --- | --- |
| DynamoDB | `session_id`, 상태, 대기 순번, 마스킹 환자명, 연령대, 성별, 진료과, S3 key |
| S3 | `answers.redacted.json`, `onepaper.redacted.json`, `patient_guide.redacted.json`, `doctor_review.redacted.json`, 최소 `llm_trace.redacted.json` |

음성 원본 파일, prompt 전문, LLM raw response, 전체 IR 후보 목록은 저장하지 않습니다.

---

## 9. 보안 처리

- 직원/의사 접근 코드 로그인
- 만료 세션 토큰
- 환자별 세션 토큰
- 실명 마스킹
- 생년월일 원문 미저장, 연령대 저장
- 연락처 원문 미저장
- S3 artifact redaction
- DynamoDB TTL
- S3 lifecycle
- AWS AI Services opt-out 정책 전제

AWS 콘솔 설정은 [backend/serverless/README.md](serverless/README.md)에 정리되어 있습니다.

---

## 10. 검증

```bash
cd backend/serverless
python -m pytest tests/ -q
python -m compileall src
sam validate
```

주요 테스트:

| 파일 | 목적 |
| --- | --- |
| `test_schema_and_artifact_policy.py` | schema와 저장 artifact 정책 검증 |
| `test_schema_slots.py` | 증상 slot schema 검증 |
| `test_ir_noise_and_safety.py` | IR noise와 안전 플래그 검증 |
| `test_prompts_golden.py` | 핵심 프롬프트 회귀 검증 |
| `test_question_sets.py` | 질문셋 구조 검증 |
| `test_sessions_queue.py` | 대기열 상태 전환 검증 |

---

## 11. 개발자가 먼저 볼 곳

1. `orchestration.py`: 답변 일괄 저장과 백그라운드 분석 시작점
2. `pipeline_graph.py`: 전체 AI 처리 순서
3. `pipeline_nodes.py`: 각 단계의 실제 구현
4. `retrieval.py`: 표준 증상 매칭
5. `onepager.py`: 의료진 원페이퍼 구성
6. `guide.py`: 환자 안내문 구성

---

## 12. 주의

공개 GitHub에는 원천 의료 백과 데이터, 파생 증상 인덱스, embedding cache, 실제 평가 데이터, AWS 배포 산출물을 올리지 않습니다. 실행 또는 배포 전에는 팀 내부 비공개 저장소에서 필요한 런타임 데이터를 `src/data/`에 배치해야 합니다.

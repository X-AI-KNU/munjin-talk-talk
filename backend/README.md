# 문진톡톡 백엔드

이 폴더는 문진톡톡 MVP의 백엔드 영역입니다.

현재 실제 배포 대상은 `backend/serverless` 하나입니다. 로컬 IR 실험 코드, persona 평가 데이터, 과거 prototype script는 이 배포 저장소에 포함하지 않는 것을 원칙으로 합니다.

---

## 백엔드가 담당하는 일

백엔드는 환자 발화 텍스트를 받아 의료진 원페이퍼와 환자 안내문으로 이어지는 모든 서버 측 처리를 담당합니다.

| 영역 | 백엔드 책임 |
| --- | --- |
| 세션 관리 | 접수처에서 생성한 환자 문진 세션을 DynamoDB에 저장 |
| 음성 인식 연결 | 환자 음성 저장 없이 Transcribe Streaming URL 발급 |
| LLM extraction | Bedrock Nova로 환자 발화를 의미 단위로 분할, 표준화 |
| Schema validation | Pydantic으로 LLM JSON 구조, enum, source_quote 검증 |
| Hybrid IR | LLM 증상 후보를 표준 증상 인덱스와 BM25 + Titan Vector로 매칭 |
| 원페이퍼 생성 | 증상, 문맥, 환자 질문, 체크리스트, EMR 문장 조립 |
| 환자 안내문 | 의사 답변과 강조사항을 안내문 JSON으로 구성 |
| Trace 저장 | 각 처리 단계의 active_path, pipeline_trace, ir_trace 저장 |

---

## 폴더 구조

```text
backend/
├── README.md
└── serverless/
    ├── README.md
    ├── template.yaml
    ├── samconfig.toml
    ├── s3-cors.json
    └── src/
        ├── handler.py
        ├── common.py
        ├── settings.py
        ├── sessions.py
        ├── audio.py
        ├── orchestration.py
        ├── pipeline_graph.py
        ├── pipeline_nodes.py
        ├── pipeline_state.py
        ├── pipeline_trace.py
        ├── extraction.py
        ├── extraction_prompts.py
        ├── extraction_schema.py
        ├── extraction_fallback.py
        ├── langchain_prompting.py
        ├── llm.py
        ├── retrieval.py
        ├── retrieval_documents.py
        ├── retrieval_embeddings.py
        ├── retrieval_scoring.py
        ├── clinical_terms.py
        ├── onepager.py
        ├── onepager_sections.py
        ├── onepager_review.py
        ├── guide.py
        ├── schemas/
        └── data/
```

서버리스 배포와 endpoint 상세는 [serverless README](serverless/README.md)에 있습니다.

---

## 백엔드 처리 흐름

환자 답변 1개 기준:

```text
프론트 /process-answer 호출
  -> handler.py
  -> orchestration.py
  -> pipeline_graph.py
  -> pipeline_nodes.py
  -> extraction.py
  -> schemas/extraction.py
  -> retrieval.py
  -> onepager.py
  -> sessions.py
  -> API 응답
```

조금 더 풀면:

1. `handler.py`가 API Gateway 요청을 받습니다.
2. `/process-answer` 요청이면 `orchestration.process_answer()`로 넘깁니다.
3. `orchestration.py`는 LangGraph 파이프라인을 실행합니다.
4. `pipeline_graph.py`는 노드 순서와 조건 분기를 정의합니다.
5. `pipeline_nodes.py`는 실제 노드별 처리 로직을 실행합니다.
6. `semantic_extraction_node`가 `extraction.py`를 호출합니다.
7. `extraction.py`가 Q별 Bedrock 모델을 선택하고 LLM JSON을 요청합니다.
8. `extraction_schema.py`와 `schemas/extraction.py`가 fixed schema를 검증합니다.
9. 증상 문항이면 `retrieval.py`가 Hybrid IR 매칭을 수행합니다.
10. `onepager.py`가 세션 상태에 맞춰 원페이퍼 JSON을 갱신합니다.
11. `sessions.py`가 DynamoDB에 저장합니다.

---

## LangGraph를 쓰는 이유

이 프로젝트는 단순히 함수 여러 개를 순서대로 호출하는 방식보다, 파이프라인을 눈으로 확인할 수 있는 구조가 중요합니다.

LangGraph를 쓰면 다음을 명시할 수 있습니다.

- 어떤 노드가 먼저 실행되는지
- LLM 검증 실패 시 어디로 분기되는지
- safety flag가 있을 때 어떤 예외 경로로 저장되는지
- 각 노드가 어떤 trace를 남기는지
- 프론트와 DynamoDB에서 실제 처리 경로를 어떻게 확인하는지

현재 노드:

```text
input_transcript
quick_safety_flag
semantic_extraction
schema_quote_validation
hybrid_ir_match
session_validation_save
safety_guardrail_save
onepaper_refresh
response_payload
```

자세한 설명은 [LangGraph 파이프라인 문서](../docs/LANGGRAPH_PIPELINE.md)를 참고하세요.

---

## LangChain을 쓰는 위치

현재 LangChain은 전체 agent를 만들기 위해 쓰는 것이 아니라, Bedrock에 전달하는 prompt/message 계층을 안정적으로 구성하기 위해 사용합니다.

관련 파일:

```text
backend/serverless/src/langchain_prompting.py
backend/serverless/src/llm.py
```

역할:

- prompt 문자열을 Bedrock messages 형식으로 조립
- 향후 dialect RAG, retriever, output parser를 붙일 수 있는 확장 지점 제공
- LLM 호출부와 프롬프트 템플릿 관리를 분리

---

## LLM 사용 원칙

문진톡톡의 백엔드는 LLM이 만든 결과를 그대로 신뢰하지 않습니다.

반드시 지키는 원칙:

- LLM 출력은 fixed schema에 맞아야 합니다.
- Pydantic validator를 통과해야 합니다.
- `source_quote`는 환자 원문에 실제로 존재해야 합니다.
- enum 값은 미리 정의된 값만 허용합니다.
- 예상하지 않은 필드는 거부합니다.
- LLM이 만든 `score`, `confidence`, `probability`는 허용하지 않습니다.
- 검증 실패 시 bounded retry loop를 돌립니다.
- retry 후에도 실패하면 저장하지 않고 오류를 반환합니다.
- safety flag가 있는 경우에는 LLM 실패 중에도 안전 플래그만 별도 저장할 수 있습니다.

---

## rule-based 코드에 대한 원칙

프로젝트 안에는 `extraction_fallback.py`처럼 fallback 파일이 존재합니다. 그러나 기본 운영 경로는 rule-based extraction이 아닙니다.

운영 기본값:

```text
USE_BEDROCK_LLM=true
ALLOW_RULE_FALLBACK=false
```

의미:

- LLM extraction과 validator를 통과한 데이터만 저장하는 것이 기본입니다.
- rule-based fallback은 명시적으로 `ALLOW_RULE_FALLBACK=true`로 켠 경우에만 사용됩니다.
- fallback은 데모나 장애 대비용이지, 실제 MVP 검증의 기본 성능으로 보지 않습니다.

---

## Hybrid IR 데이터 원칙

증상 매칭은 `symptom_retrieval_dataset` 같은 LLM 가공 데이터에 의존하지 않는 방향으로 정리했습니다.

현재 runtime 원천 데이터:

```text
backend/serverless/src/data/diseases_cleaned.json
backend/serverless/src/data/symptom_index.json
```

그리고 사전 계산된 Titan embedding cache:

```text
backend/serverless/src/data/symptom_embeddings_amazon.titan-embed-text-v2_0_512.json
```

Hybrid IR 흐름:

1. LLM이 환자 발화에서 symptom span을 추출합니다.
2. span의 `normalized_text`, `name`, `slot_ref`, `source_quote`를 검색 query로 사용합니다.
3. `symptom_index.json`과 `diseases_cleaned.json`에서 deterministic rule로 검색 문서를 구성합니다.
4. BM25 lexical score를 계산합니다.
5. Titan embedding vector similarity를 계산합니다.
6. 표준 증상명/별칭 직접 포함 여부를 label score로 반영합니다.
7. threshold를 통과한 경우만 `matched_slots`로 확정합니다.
8. 채택 이유와 후보 점수는 `ir_trace`에 저장합니다.

중요한 점:

- IR은 LLM이 새 증상명을 창작하는 단계가 아닙니다.
- LLM이 낸 증상 후보가 표준 증상 인덱스와 맞아야 최종 증상 카드가 됩니다.
- score는 LLM 점수가 아니라 IR 계산 점수입니다.

---

## 데이터 저장 위치

모든 문진 결과는 DynamoDB 세션 item에 저장됩니다.

주요 필드:

```text
session_id
patient
visit_type
status
queue_number
responses
question_results
matched_symptoms
onepager
doctor_review
patient_guide
```

Transcribe 음성 파일은 S3에 저장하지 않습니다.

S3 bucket은 현재 다음 용도에만 남아 있습니다.

- SAM 배포 artifact
- CloudFormation/SAM 임시 산출물
- 향후 임시 파일이 필요할 경우의 제한적 저장소

실제 환자 음성 저장소로 사용하지 않습니다.

---

## 개발자가 먼저 봐야 하는 파일

| 알고 싶은 것 | 볼 파일 |
| --- | --- |
| API endpoint 목록 | `serverless/src/handler.py` |
| 환경 변수와 모델 ID | `serverless/src/settings.py` |
| 전체 문항 처리 흐름 | `serverless/src/pipeline_graph.py` |
| 각 파이프라인 노드 구현 | `serverless/src/pipeline_nodes.py` |
| trace 저장 로직 | `serverless/src/pipeline_trace.py` |
| Bedrock extraction | `serverless/src/extraction.py` |
| extraction prompt | `serverless/src/extraction_prompts.py` |
| extraction schema | `serverless/src/schemas/extraction.py` |
| 증상 IR | `serverless/src/retrieval.py` |
| IR 문서 생성 | `serverless/src/retrieval_documents.py` |
| IR score 계산 | `serverless/src/retrieval_scoring.py` |
| 원페이퍼 생성 | `serverless/src/onepager.py` |
| 원페이퍼 리뷰 LLM | `serverless/src/onepager_review.py` |
| 환자 안내문 | `serverless/src/guide.py` |
| DynamoDB 저장 | `serverless/src/sessions.py` |

---

## 배포 문서

서버리스 백엔드 배포:

- [serverless README](serverless/README.md)
- [AWS 배포 가이드](../docs/DEPLOYMENT.md)

전체 MVP 실행:

- [MVP 실행 가이드](../docs/MVP_SETUP.md)

내부 데이터 구조:

- [내부 JSON 스키마](../docs/DATA_SCHEMA.md)

---

## 주의해야 할 점

실제 환자 데이터로 테스트하기 전:

- 직원/의사 endpoint 인증 필요
- DynamoDB TTL 또는 보존 기간 정책 필요
- CloudWatch Logs 보존 기간 설정 필요
- Bedrock/Transcribe 비용 모니터링 필요
- 환자 동의 절차 필요
- 의료정보 처리 기준 검토 필요

현재 저장소는 MVP 검증용이며, 공개 운영용 보안 체계가 완성된 상태는 아닙니다.

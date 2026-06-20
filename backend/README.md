# ⚙️ 문진톡톡 · 백엔드

환자 음성 문진 텍스트를 구조화하고, 의료진 원페이퍼와 환자 안내문으로 이어지는 서버 측 처리를 담당합니다. 배포 대상은 [`backend/serverless`](serverless/README.md)이며 API Gateway · Lambda · DynamoDB · S3 · Transcribe Streaming · Bedrock · Titan Embeddings를 사용합니다.

> 📍 [루트 README](../README.md) · [serverless 배포 가이드](serverless/README.md) · [LangGraph 파이프라인](../docs/LANGGRAPH_PIPELINE.md)

이 백엔드는 LLM 결과를 그대로 저장하지 않습니다. 모든 LLM 출력은 fixed schema · enum · 원문 quote 검증을 통과해야 하고, 증상 매칭은 원천 JSON 기반 Hybrid IR을 통과해야 합니다. 진단명 추천 · 처방 결정 · 질병 예측은 수행하지 않습니다.

---

## 📋 책임 범위

| 영역 | 책임 |
| --- | --- |
| 세션 관리 | 접수 세션의 최소 상태와 S3 pointer를 DynamoDB에 저장·조회 |
| 음성 인식 연결 | 음성 저장 없이 Transcribe Streaming presigned URL 발급 |
| RAG 참고 컨텍스트 | 원천 JSON·제한 alias bridge에서 LLM 표준화 참고 문맥 검색 |
| LLM extraction | Bedrock Nova로 발화의 의미 단위·표준화·질문·단서 추출 |
| Schema validation | Pydantic으로 JSON 구조·enum·quote grounding 검증 |
| Hybrid IR | LLM 증상 후보를 BM25 + Titan Vector로 표준 증상명에 매칭 |
| 원페이퍼 생성 | 증상·문맥·환자 질문·확인 항목·EMR 초안 조립 |
| 환자 안내문 | 의사 답변을 환자용 안내문 JSON으로 구성 |
| Artifact 저장 | 답변·원페이퍼·의사 답변·안내문·trace를 S3에 가명처리 JSON으로 저장 |

---

## 🗂️ 폴더 구조

```text
backend/
├── README.md
└── serverless/
    ├── README.md
    ├── template.yaml            # SAM: API Gateway + Lambda
    ├── src/
    │   ├── handler.py           # API Gateway route 분기
    │   ├── orchestration.py     # /process-answer 진입점
    │   ├── settings.py          # AWS client, 환경 변수, 모델 ID
    │   ├── sessions.py          # DynamoDB 세션 상태
    │   ├── artifact_store.py    # S3 artifact 저장/조회
    │   ├── artifact_policy.py   # 운영 artifact·최소 trace 필드 정리
    │   ├── privacy.py           # 가명처리 helper
    │   ├── audio.py             # Transcribe presigned URL
    │   ├── pipeline_graph.py    # LangGraph 노드·edge 정의
    │   ├── pipeline_nodes.py    # 노드별 실제 처리
    │   ├── pipeline_state.py    # LangGraph state 구조
    │   ├── pipeline_trace.py    # active path·trace
    │   ├── rag_context.py       # RAG 참고 문맥 검색
    │   ├── langchain_prompting.py # Bedrock JSON chain
    │   ├── llm.py               # LLM 호출 wrapper + chain meta
    │   ├── extraction_prompts.py / extraction_schema.py
    │   ├── clinical_terms.py / clinical_state.py
    │   ├── domain_config.py     # 도메인팩 로딩·기본 질문 fallback
    │   ├── question_sets.py     # 질문셋 로딩
    │   ├── retrieval.py         # Hybrid IR 진입점
    │   ├── retrieval_documents.py / retrieval_embeddings.py / retrieval_scoring.py
    │   ├── onepager.py / onepager_sections.py / onepager_review.py
    │   ├── guide.py
    │   ├── utils.py
    │   ├── schemas/             # extraction.py, review.py, guide.py
    │   └── data/
    │       ├── README.md
    │       ├── domain_packs/respiratory.json   (+ respiratory_fewshot.txt)
    │       ├── question_sets/default.json
    │       └── (비공개 배치) diseases_cleaned / symptom_index / embedding cache
    └── tests/                   # pytest (6 파일, 25 케이스)
```

> ℹ️ 도메인팩과 질문셋은 각각 `data/domain_packs/`, `data/question_sets/` 폴더로 분리되어 있습니다. 원천 의료 백과 본문과 그 파생 증상 인덱스·embedding cache는 저작권/이용 범위 검토 대상이라 공개 저장소에 포함하지 않고, 배포 시 팀 내부 비공개 데이터로 주입합니다. `backend/serverless/.aws-sam/`과 `samconfig.toml`은 로컬 산출물이라 저장소에 포함하지 않습니다.

---

## 🔄 답변 1개 처리 흐름

```text
POST /process-answer
  → handler.py → orchestration.py → pipeline_graph.py → pipeline_nodes.py
  → rag_context.py → langchain_prompting.py / llm.py → schemas/extraction.py
  → retrieval.py → onepager.py → sessions.py → API response
```

1. `handler.py`가 API Gateway 요청 수신, `/process-answer`는 `orchestration.process_answer()`로 전달
2. `orchestration.py`가 LangGraph 파이프라인 실행
3. `pipeline_graph.py`가 노드 순서·조건 분기 정의, `pipeline_nodes.py`가 각 노드 처리
4. `rag_context_retrieval_node`가 원천 JSON 기반 참고 문맥 검색
5. `semantic_extraction_node`가 LangChain Runnable chain으로 Bedrock Nova 호출
6. `schema_quote_validation_node`가 Pydantic schema와 source_quote 검증
7. 검증 실패 시 LangGraph가 `semantic_extraction_node`로 되돌려 repair prompt 실행
8. 증상 문항이면 `retrieval.py`가 Hybrid IR 매칭
9. `onepager.py`가 원페이퍼 JSON 갱신
10. `artifact_store.py`가 답변·원페이퍼·trace를 S3에 저장
11. `sessions.py`가 DynamoDB 상태·S3 pointer만 갱신

---

## 🧠 LangGraph & LangChain

**LangGraph** — 처리 경로와 분기 기록을 명시합니다. 노드:

```text
input_transcript → quick_safety_flag → rag_context_retrieval
→ semantic_extraction → schema_quote_validation → hybrid_ir_match
→ session_validation_save → onepaper_refresh → response_payload
(safety 분기: schema_quote_validation → safety_guardrail_save → response_payload)
```

관련: `pipeline_graph.py`, `pipeline_nodes.py`, `pipeline_trace.py`

**LangChain** — agent framework가 아니라 Runnable chain으로 씁니다. `ChatPromptTemplate`로 prompt를 만들고 boto3 Bedrock 호출을 `RunnableLambda`로 감싼 뒤 `JsonOutputParser`로 파싱하는 체인을 `semantic_extraction` 노드 안에서 실행합니다.

관련: `langchain_prompting.py`, `llm.py`

---

## 🛡️ LLM 사용 원칙

- LLM extraction은 필수 경로입니다 (rule-based fallback으로 조용히 대체하지 않음).
- LLM JSON은 fixed schema를 통과해야 하고, `source_quote`·`original_quote`는 환자 원문에 존재해야 합니다.
- enum은 미리 정의된 값만, schema에 없는 필드는 거부합니다.
- LLM이 생성한 `score`·`confidence`·`probability`·`risk percentage`는 허용하지 않습니다.
- 검증 실패 시 bounded retry, 이후에도 실패하면 저장하지 않고 422 반환.
- 단, 안전 플래그가 있으면 extraction 실패 중에도 safety-only 저장 경로로 위험 신호만 보존할 수 있습니다.

### Deterministic 코드의 위치

| 구분 | 사용 | 설명 |
| --- | --- | --- |
| LLM extraction | 기본 | 실제 문진 의미 추출 |
| Pydantic validation | 항상 | 저장 전 검증 |
| RAG context | 사용 | 표준화 참고 문맥 (환자 사실로 직접 채택 안 함) |
| safety flag rule | 사용 | 객혈·호흡곤란 등 즉시 확인 표현 감지 (진단 아님, guardrail) |
| IR document build | 사용 | 원천 JSON을 검색 문서로 접는 변환 (발화 추출 로직 아님) |

---

## 🔍 Hybrid IR

원천 데이터는 내부 배포 환경의 `data/diseases_cleaned.json`, `data/symptom_index.json`과 사전계산 embedding cache를 사용합니다. 이 3개 파일은 공개 저장소에는 포함하지 않습니다.

1. LLM span의 `source_quote`·`normalized_text`·`name`·`slot_ref`를 query로 구성
2. `symptom_index.json`·`diseases_cleaned.json`에서 검색 문서 생성
3. BM25 lexical score → Titan embedding cosine similarity → 표준명·alias bridge label score
4. vector 중심 threshold 통과 후보만 `matched_slots`로 저장
5. 운영 artifact에는 숫자 점수·후보 목록 제거, 최소 trace에는 확정 매칭의 BM25/vector/label/rank 근거 요약만 남김

의료진 UI에는 숫자 점수를 표시하지 않습니다.

---

## 📄 원페이퍼 & 안내문

`onepager.py`는 S3 `answers.redacted.json`을 읽어 원페이퍼 JSON을 구성합니다 (`patient_summary`, `symptom_slots`, `clinical_clues`, `agenda`, `review_items`, `transfer_text`, `safety_flags`). `onepager_review.py`는 Q4 저장 후 또는 safety flag 시 Nova Pro로 확인 항목·EMR 초안을 다듬고 `schemas/review.py` 검증을 통과해야 반영됩니다.

`guide.py`는 의사 답변·강조사항을 S3 `doctor_review.redacted.json`에, 생성된 안내문을 `patient_guide.redacted.json`에 저장합니다. 의사 답변은 Nova Lite로 환자용 쉬운 문장으로 변환하되 **강조사항은 LLM이 변형하지 않고 그대로** 별도 카드에 표시합니다. `schemas/guide.py` 검증 실패 시 빈 안내문과 실패 사유를 저장하고 validator 실패로 반환합니다.

---

## 💾 데이터 저장

| 저장소 | 저장하는 값 | 저장하지 않는 값 |
| --- | --- | --- |
| DynamoDB | `session_id`, queue_number, status, visit_type, **마스킹 환자 표시정보**, age_band, gender, department, doctor, receipt_id, risk, privacy_consent 요약, question_status, artifact key, onepager_ready, guide_ready | 실명·생년월일·연락처 원문, 문항 원문, 원페이퍼/안내문 전체 |
| S3 | `sessions/YYYY-MM-DD/{session_id}/` 아래 consent·answers·onepaper·doctor_review·patient_guide·llm_trace 의 `.redacted.json` | 음성 원본, prompt 전문, LLM raw response, 전체 후보 목록 |

S3는 `artifact_store.py`로만 읽고 씁니다. 저장 직전 `artifact_policy.py`가 운영 필드만 남기고 `privacy.py`가 연락처·주민번호·이메일·생년월일 형태 직접식별정보를 1차 마스킹합니다. 운영에서는 S3 Block Public Access · Lifecycle · KMS · Macie를 함께 적용해야 합니다.

---

## 🧪 검증

```bash
# Python 문법
python -m compileall backend/serverless/src

# 테스트 (6 파일, 25 케이스)
cd backend/serverless
pip install -r src/requirements.txt pytest
python -m pytest tests/ -q
```

실제 테스트 파일: `test_schema_and_artifact_policy.py`, `test_schema_slots.py`, `test_ir_noise_and_safety.py`, `test_prompts_golden.py`, `test_question_sets.py`, `test_sessions_queue.py`

<details>
<summary>Windows PowerShell (unittest 방식)</summary>

```powershell
py -3.12 -m compileall backend/serverless/src
cd backend/serverless
sam validate
```
</details>

---

## 🧭 개발자가 먼저 볼 파일

| 목적 | 파일 |
| --- | --- |
| API endpoint | `handler.py` |
| 환경 변수·모델 ID | `settings.py` |
| 전체 파이프라인 / 노드 | `pipeline_graph.py` / `pipeline_nodes.py` |
| RAG 참고 문맥 | `rag_context.py` |
| extraction prompt / schema | `extraction_prompts.py` / `schemas/extraction.py` |
| 도메인팩 / 질문셋 로딩 | `domain_config.py` / `question_sets.py` |
| 도메인팩 데이터 | `data/domain_packs/respiratory.json` |
| Hybrid IR | `retrieval.py` (+ `_documents`/`_embeddings`/`_scoring`) |
| 원페이퍼 / 리뷰 | `onepager.py` / `onepager_review.py` |
| 환자 안내문 | `guide.py` |
| 개인정보 최소화 / artifact 정책 | `privacy.py` / `artifact_policy.py` |

---

## 🔒 보안 주의

현재 MVP 백엔드는 `security.py`에서 직원/의료진 접근 코드와 환자 세션 토큰을 검증합니다. 다만 이는 해커톤 MVP 수준의 1차 접근 제어이므로, 실제 의료기관 운영 전에는 Cognito 또는 병원 SSO, 사용자별 계정, 감사 로그, DynamoDB TTL 콘솔 활성화, S3 Lifecycle/KMS/Macie, CloudWatch Logs 보존, API Gateway throttling, WAF/IP 제한, 환자 동의 절차, 의료정보 처리 기준 검토가 필요합니다.

자세한 내용: [serverless README](serverless/README.md) · [데이터 전수조사](../docs/SECURITY_DATA_INVENTORY.md)

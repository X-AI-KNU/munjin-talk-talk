# 문진톡톡 백엔드

문진톡톡 백엔드는 환자가 답변한 음성 문진(Q1~Q4)을 텍스트로 저장하고, 백그라운드에서 AI 파이프라인을 실행하여 **의료진용 원페이퍼(One-paper)**와 **환자 맞춤형 안내문**을 생성하는 서버 사이드 핵심 아키텍처입니다.

완전 관리형 서버리스(Serverless) 환경으로 구축되었으며, 배포 대상은 `backend/serverless`입니다. 주요 인프라로 AWS API Gateway, Lambda, DynamoDB, S3, Amazon Bedrock(Nova), Amazon Titan Embeddings를 활용합니다.

**관련 문서**:
- [루트 README](../README.md)
- [Serverless 배포 가이드](serverless/README.md)
- [LangGraph 파이프라인](../docs/LANGGRAPH_PIPELINE.md)
- [데이터 Schema](../docs/DATA_SCHEMA.md)

---

## 1. 책임 범위

| 영역 | 핵심 책임 |
| --- | --- |
| **세션 관리** | 접수 세션 상태, 대기 순번 관리 및 S3 Artifact 참조 포인터를 DynamoDB에 저장 |
| **음성 처리** | Amazon Transcribe Streaming 연동용 Presigned URL 발급 (음성 원본은 절대 저장하지 않음) |
| **답변 저장** | 확정된 Q1~Q4 텍스트를 일괄 저장 후 즉시 상태를 `analysis_pending`으로 전환 |
| **백그라운드 분석** | 환자의 대기 시간 최소화를 위해 Lambda 비동기(Async) 호출로 LangGraph 파이프라인 실행 |
| **RAG 문맥** | 강원 방언팩 및 호흡기 도메인팩 기반으로 환자 발화의 표준어/의학적 의미 맥락 검색 |
| **LLM 추론** | Bedrock Nova 모델을 통해 텍스트 표준화, 의미 단위 추출, 증상 단서(Hint) 및 환자 질문 구조화 |
| **스키마 검증** | 추출된 데이터가 Pydantic 스키마 형식을 엄격히 준수하고 `source_quote`가 원문에 존재하는지 검증 |
| **Hybrid IR 검색** | 추출된 키워드를 BM25, Titan Vector, Label Signal로 다각도 검색하여 표준 증상 후보 도출 |
| **원페이퍼 생성** | 검증된 증상, 원문, 요약, 필수 확인 항목 및 EMR 초안 데이터 조립 |
| **안내문 생성** | 의사의 코멘트와 주의사항을 고령 환자의 눈높이에 맞춘 친화적인 안내문 텍스트로 변환 |
| **저장 정책** | 최소한의 상태값만 DynamoDB에 남기고, 민감 정보가 비식별(Redaction) 처리된 결과물만 S3에 보관 |

> ⚠️ **주의:** 본 백엔드 시스템은 환자의 증상을 정제하고 매핑할 뿐, 어떠한 형태의 **진단명 추천, 처방 결정, 질병 예측도 자체적으로 수행하지 않습니다.**

---

## 2. 비동기 문진 처리 파이프라인

문진톡톡은 환자의 UX(사용자 경험)를 쾌적하게 유지하기 위해 "문항별 즉시 분석"이 아닌 **"Q1~Q4 답변 일괄 저장 후 백그라운드 비동기 분석"** 방식을 채택했습니다.

```text
POST /process-answers
  -> 환자의 Q1~Q4 텍스트 답변 정규화 및 수합
  -> 개인정보를 마스킹하여 S3 (answers.redacted.json)에 저장
  -> DynamoDB 상태를 `analysis_pending`으로 변경
  -> 자신(Lambda)을 Event Invocation 방식으로 비동기 호출 트리거
  -> 환자 태블릿(프론트엔드)에는 지연 없이 즉시 `patient_complete` 응답 반환

Internal Background Event (비동기 Lambda 실행)
  -> 수합된 Q1~Q4 데이터를 LangGraph 파이프라인에 주입
  -> Quick Safety Flag (응급/위험 징후 1차 감지)
  -> RAG Context Retrieval (방언 및 의학 맥락 검색)
  -> Semantic Extraction (증상/단서/질문 의미 추출)
  -> Schema Quote Validation (Pydantic 형식 및 원문 근거 검증)
  -> Hybrid IR + Linker (검증된 표준 의학 용어로 매칭)
  -> Onepaper Refresh (의료진 화면용 데이터 최종 조립)
  -> S3에 Onepaper 및 Trace 로그(비식별화) 저장
  -> DynamoDB 상태를 `waiting_doctor` 또는 `needs_priority`로 변경
```
이 구조 덕분에 백엔드의 복잡한 LLM 추론 시간(Latency)이 환자의 대기 시간으로 이어지지 않으며, 분석 중 오류가 발생하더라도 환자 측 흐름은 중단 없이 정상 완료되고 의료진 화면에서만 재분석 플래그가 켜집니다.

---

## 3. 백엔드 폴더 구조

서버리스 배포에 최적화된 아키텍처로 모듈을 분리했습니다.

```text
backend/
├── README.md
└── serverless/
    ├── template.yaml            # AWS SAM 배포 템플릿
    ├── README.md
    ├── src/
    │   ├── handler.py           # API Gateway 라우팅 진입점
    │   ├── security.py          # 권한 및 세션 토큰 검증
    │   ├── orchestration.py     # 비동기 분석 및 재시도 제어 오케스트레이션
    │   ├── sessions.py          # DynamoDB 상태 CRUD
    │   ├── artifact_store.py    # S3 결과물 저장 인터페이스
    │   ├── artifact_policy.py   # 운영 로그 최소화/비식별 정책 정의
    │   ├── privacy.py           # PII(개인식별정보) 마스킹 유틸리티
    │   ├── audio.py             # STT Presigned URL 발급
    │   ├── pipeline_graph.py    # LangGraph 노드 및 엣지(흐름) 정의
    │   ├── pipeline_nodes.py    # LangGraph 개별 노드 비즈니스 로직
    │   ├── langchain_prompting.py # LLM 프롬프트 및 파서(Chain) 구성
    │   ├── llm.py               # Amazon Bedrock Boto3 Wrapper
    │   ├── rag_context.py       # 통합 RAG 검색 제어
    │   ├── dialect_rag.py       # 강원 사투리 -> 표준어 RAG 모듈
    │   ├── retrieval.py         # Hybrid IR 메인 모듈
    │   ├── retrieval_embeddings.py # Titan 임베딩 처리
    │   ├── retrieval_scoring.py # BM25 및 벡터 스코어링/퓨전
    │   ├── onepager.py          # 최종 원페이퍼 데이터 조립
    │   ├── guide.py             # 환자 안내문 텍스트 생성
    │   ├── schemas/             # 데이터 검증용 Pydantic 모델
    │   └── data/                # 도메인팩 및 IR 인덱스 데이터 배치 경로
    └── tests/                   # Pytest 검증 스크립트
```

---

## 4. LangGraph와 LangChain 활용 전략

### 1) LangGraph (파이프라인 제어)

전체 분석 과정은 상태를 지닌 노드들의 방향성 그래프(Graph)로 구성되어 있습니다. 에러 발생 시 조건부 재시도(Bounded Retry)를 수행하며, 위험 징후 감지 시 안전 최우선(Safety-only) 분기로 즉각 우회합니다.

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

### 2) LangChain (추론 체인 조립)

자율적 Agent 형태가 아닌, 프롬프트-모델-파싱을 하나로 묶는 견고한 인터페이스(Runnable)로 제한하여 사용합니다.

```text
ChatPromptTemplate
  -> Bedrock boto3 호출 (RunnableLambda 래핑)
  -> JsonOutputParser
  -> Pydantic Validator (스키마 엄격 검증)
```

---

## 5. 의료 안전을 위한 LLM 제어 원칙

의료 보조 시스템으로서 LLM의 환각을 철저히 차단합니다.

- **Schema Strictness:** 모든 LLM 출력은 미리 정의된 Pydantic 고정 스키마를 100% 통과해야만 저장됩니다. 스키마에 없는 필드나 열거형(enum)에 없는 값은 즉시 거부(Reject)합니다.
- Grounding 검증: 추출된 `source_quote`는 반드시 환자가 실제로 발화한 원문 텍스트 내에 정확히 존재해야만 인정됩니다.
- schema에 없는 필드, 정의되지 않은 enum은 거부합니다.
- 불확실성 배제: LLM이 자체적으로 생성한 진단 확률(`probability`), 확신도(`confidence`), 점수(`score`) 필드는 혼선을 유발하므로 시스템 단에서 원천 차단 및 폐기합니다.
- 상태 필터링: `symptom_absent`(증상 없음), `progress_improved`(상태 호전) 등의 비활성(Inactive) 맥락은 현재 나타나는 '활성 증상(Active Symptom)' 리스트에 포함하지 않습니다.

---

## 6. Hybrid IR (Information Retrieval)

단순한 키워드 매칭의 한계를 넘기 위해 복합 검색(Hybrid IR) 아키텍처를 구현했습니다.

검색 소스:
공개 도메인팩 외에 3개의 비공개 핵심 데이터(원천 데이터 저작권 보호)를 런타임에 참조합니다.

- `diseases_cleaned.json` (질병 백과 정제 데이터)
- `symptom_index.json` (파생 증상 인덱스)
- `symptom_embeddings_amazon.titan-embed-text-v2.json` (벡터 캐시)

매칭 알고리즘 흐름:

```text
LLM Extract Span (예: normalized_text + symptom_hint)
  -> BM25 Sparse Score (키워드 정확도 계산)
  -> Titan Vector Score (의미론적 유사도 계산)
  -> Label Signal (직접적인 증상명 매칭 보정)
  -> RRF (Reciprocal Rank Fusion) 스코어 융합
  -> Top-K 표준 증상 후보 선별
  -> Validator 검증 및 최종 병명 확정
```

특정 테스트 케이스 통과만을 위한 하드코딩된 규칙(Rule-base alias)이 아닌, 실제 원천 문서 기반의 확장 가능한 범용 IR 엔진으로 구축되었습니다.

---

## 7. 저장소 및 데이터 보안 정책

민감한 환자 의료 정보를 다루기 위해 저장 최소화 및 비식별화(Redaction) 정책을 강제합니다.

| 저장소 | 저장하는 데이터 | 절대로 저장하지 않는 데이터 |
| --- | --- | --- |
| **DynamoDB** | `session_id`, 현재 상태, 대기 순번, 마스킹된 환자명(`김*진`), 연령대(`70대`), 성별, 진료과, S3 포인터 | 환자 실명, 정확한 생년월일, 원본 연락처 |
| **S3** | 개인정보가 마스킹 처리된 `*.redacted.json` 결과물 (답변, 원페이퍼, 안내문, 추론 Trace) | 음성 파일 원본, LLM Raw Response, Prompt 전문, 필터링 전 IR 후보 리스트 |

**적용된 인프라 보안 조치:**
* 직원/의사 접근 코드 기반 인증 및 단기 세션 토큰 발행
* DynamoDB TTL 설정 및 S3 Lifecycle Policy(단기 보존 후 영구 삭제)
* AWS AI Services Opt-out 정책 활성화 (입력 데이터가 AI 학습에 사용되지 않음)

---

## 8. 로컬 검증 및 테스트

안전한 배포를 위해 촘촘한 테스트 코드를 작성했습니다.

```bash
cd backend/serverless
python -m pytest tests/ -q
python -m compileall src
sam validate
```

**핵심 테스트 케이스 목록:**
* `test_schema_and_artifact_policy.py`: 스키마 정합성 및 저장 로그의 비식별화 정책 검증
* `test_schema_slots.py`: 증상 Slot 추출의 정확도 검증
* `test_ir_noise_and_safety.py`: IR 검색 시 노이즈 대응 및 위험 징후(Safety Flag) 감지력 검증
* `test_prompts_golden.py`: 핵심 프롬프트의 회귀(Regression) 테스트
* `test_question_sets.py`: 문진 질문셋의 논리적 흐름 검증
* `test_sessions_queue.py`: 대기열 상태(Status) 전환 로직 검증

---

## 9. 코드 네비게이션 가이드

백엔드 로직 파악을 위해 다음 파일들을 순서대로 살펴보시길 권장합니다.

1. `orchestration.py`: 전체 흐름의 시작점이자 비동기 람다 호출 제어
2. `pipeline_graph.py`: LangGraph 기반의 전체 AI 워크플로우 정의
3. `pipeline_nodes.py`: 파이프라인의 각 단계를 수행하는 비즈니스 로직
4. `retrieval.py`: Hybrid IR (BM25 + Vector) 표준 증상 검색 로직
5. `onepager.py`: 의료진에게 제공될 최종 원페이퍼 데이터 조립
6. `guide.py`: 의사 코멘트 기반 환자 맞춤형 안내문 생성

> ⚠️ **배포 시 주의사항:** > 본 저장소에는 의학 백과 원천 데이터, 파생 증상 인덱스, 임베딩 캐시 및 실제 평가 데이터셋이 포함되어 있지 않습니다. 로컬 실행 및 AWS 배포 전, 내부 비공개 저장소에서 해당 런타임 데이터를 복사하여 `backend/serverless/src/data/` 경로에 수동으로 배치해야 Hybrid IR 검색 기능이 정상 작동합니다.

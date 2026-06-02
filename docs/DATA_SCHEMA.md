# 문진톡톡 내부 JSON 스키마

이 문서는 문진톡톡 MVP에서 오가는 핵심 JSON 구조를 설명합니다.

가장 중요한 원칙은 다음과 같습니다.

```text
JSON 형식은 코드에 미리 정의되어 있고,
LLM은 그 틀 안의 값만 채워야 합니다.
```

LLM이 매번 새로운 형식을 마음대로 만드는 구조가 아닙니다. 백엔드는 Pydantic schema로 필드, 타입, enum, extra field, source_quote를 검증합니다.

---

## 전체 데이터 흐름

```text
POST /sessions
  -> DynamoDB session item 생성

POST /process-answer
  -> responses.Qx.text 저장
  -> LLM extraction JSON 생성
  -> Pydantic schema 검증
  -> Hybrid IR matched_slots 생성
  -> onepager 갱신
  -> pipeline_trace 저장

POST /doctor-response
  -> 의사 답변 저장
  -> patient_guide 생성

GET /guide/{session_id}
  -> 환자 안내문 조회
```

---

## 1. DynamoDB Session Item

DynamoDB `MunjinSessions` 테이블의 기본 item입니다.

Partition key:

```text
session_id (String)
```

예시:

```json
{
  "session_id": "s_1780379760_45542aeb",
  "created_at": "2026-06-02T14:56:00+09:00",
  "updated_at": "2026-06-02T14:58:10+09:00",
  "status": "doctor_ready",
  "queue_number": 3,
  "visit_type": "initial",
  "patient": {
    "full_name": "김영자",
    "name": "김*자",
    "birth_date": "1950-09-17",
    "age": 75,
    "gender": "여성",
    "department": "이비인후과",
    "doctor": "이민우",
    "phone": "010-0000-0000",
    "receipt_id": "A-0427"
  },
  "responses": {},
  "question_results": {},
  "matched_symptoms": [],
  "onepager": {},
  "doctor_review": {},
  "patient_guide": {}
}
```

### 주요 필드

| 필드 | 설명 |
| --- | --- |
| `session_id` | 모든 화면과 API를 연결하는 공통 키 |
| `status` | 접수, 문진 중, 완료, 우선 확인, 의사 확인 등 상태 |
| `queue_number` | 오늘 접수 기준 대기 번호 |
| `visit_type` | `initial` 또는 `followup` |
| `patient` | 환자 기본 정보 |
| `responses` | 문항별 환자 원문과 처리 결과 |
| `question_results` | 문항별 결과 사본 또는 호환 저장 영역 |
| `matched_symptoms` | 전체 세션 기준 표준 증상 매칭 결과 |
| `onepager` | 의사 원페이퍼 JSON |
| `doctor_review` | 의사 답변과 강조사항 |
| `patient_guide` | 환자 안내문 JSON |

---

## 2. Response Record

문항별 원문과 처리 결과입니다.

위치:

```text
session.responses.Q1
session.responses.Q2
session.responses.Q3
session.responses.Q4
```

예시:

```json
{
  "text": "어제부터 목이 칼칼하고 코가 막혀요.",
  "confirmed": true,
  "input_method": "transcribe_streaming",
  "created_at": "2026-06-02T14:57:00+09:00",
  "spans": [],
  "structured": {},
  "matched_slots": [],
  "unmatched_spans": [],
  "llm_meta": {},
  "orchestration": {},
  "pipeline_trace": []
}
```

원칙:

- `text`에는 환자 발화 원문을 보존합니다.
- LLM이 표준화한 문장은 `structured.standardized_text`에 들어갑니다.
- 증상 매칭 결과는 `matched_slots`에 들어갑니다.
- 처리 과정은 `pipeline_trace`에 남습니다.

---

## 3. LLM Extraction Output

Bedrock Nova가 생성해야 하는 fixed JSON입니다.

Pydantic schema:

```text
backend/serverless/src/schemas/extraction.py
```

Runtime adapter:

```text
backend/serverless/src/extraction_schema.py
```

예시:

```json
{
  "spans": [
    {
      "source_quote": "목이 칼칼하고",
      "type": "symptom",
      "slot_ref": "throat_irritation",
      "name": "목 자극감",
      "normalized_text": "목 자극감",
      "status": "있음",
      "alert": false,
      "explain": "환자가 목의 칼칼함을 직접 호소했습니다."
    },
    {
      "source_quote": "코가 막혀요",
      "type": "symptom",
      "slot_ref": "nasal_obstruction",
      "name": "코막힘",
      "normalized_text": "코막힘",
      "status": "있음",
      "alert": false,
      "explain": "환자가 코막힘을 직접 호소했습니다."
    }
  ],
  "structured": {
    "standardized_text": "어제부터 목이 칼칼하고 코가 막힙니다.",
    "clinical_clues": [
      {
        "category": "증상맥락",
        "label": "시작시점",
        "summary": "어제부터 증상 시작",
        "source_quote": "어제부터",
        "source_question": "Q1",
        "priority": "일반",
        "related_symptoms": ["목 자극감", "코막힘"]
      }
    ],
    "questions": [],
    "unresolved_items": []
  }
}
```

### `spans`

환자 발화에서 뽑힌 의미 단위입니다.

| 필드 | 설명 |
| --- | --- |
| `source_quote` | 환자 원문에 실제 존재하는 연속 문자열 |
| `type` | 의미 단위 유형 |
| `slot_ref` | 증상 후보일 경우 표준 slot 후보 |
| `name` | 화면에 보여줄 한국어 이름 |
| `normalized_text` | 표준화된 한국어 의미 |
| `status` | `있음`, `없음`, `확인필요` |
| `alert` | 안전상 우선 확인 여부 |
| `explain` | 왜 이렇게 분리했는지 설명 |

허용되는 `type`:

```text
symptom
new
progress_improved
progress_worsened
progress_unchanged
medication
medication_denial
adherence_gap
context
```

허용되는 `slot_ref`:

```text
hemoptysis
cough
throat_irritation
nasal_obstruction
rhinorrhea
fever
sputum
dyspnea
chest_pain
headache
other
```

복약, 무복약, 순응도, 문맥 span은 `slot_ref: "other"`를 사용합니다.

### `structured`

LLM이 정리한 문항별 구조화 정보입니다.

| 필드 | 설명 |
| --- | --- |
| `standardized_text` | 환자 발화를 표준 한국어 문장으로 정리 |
| `clinical_clues` | 의사가 증상과 함께 보면 좋은 단서 |
| `questions` | Q4에서 분리한 환자 질문 |
| `unresolved_items` | 구조화하기 애매하지만 버리면 안 되는 표현 |

### `clinical_clues`

허용되는 category:

```text
증상맥락
복약정보
복약순응도
재진경과
```

허용되는 label:

```text
시작시점
기간
현재양상
악화요인
완화요인
복용중
처방약 없음
건강보조제
누락
악화
호전
새 증상
```

### `questions`

Q4 환자 질문입니다.

예시:

```json
{
  "category": "supplement_drug_interaction",
  "summary": "처방약과 영양제 병용 가능 여부 문의",
  "original_quote": "처방받은 약이랑 영양제 같이 먹어도 되는지"
}
```

허용 category:

```text
drug_drug_interaction
supplement_drug_interaction
food_drug_interaction
treatment_duration
followup_visit
test_question
lifestyle
other
```

“따로 없어요”, “별로 없어요”, “궁금한 건 없어요” 같은 부정 답변은 question으로 저장하지 않습니다.

---

## 4. Validation Error

Pydantic 검증 실패 시 retry prompt로 들어가는 오류입니다.

예시:

```json
[
  {
    "field": "spans.0.source_quote",
    "type": "value_error",
    "message": "quote must be an exact substring of the patient answer"
  },
  {
    "field": "spans.0.score",
    "type": "extra_forbidden",
    "message": "Extra inputs are not permitted"
  }
]
```

검증 실패 조건:

- 필수 필드 누락
- enum 값 오류
- 예상하지 않은 필드 존재
- `source_quote`가 원문에 없음
- `original_quote`가 원문에 없음
- LLM 임의 score/confidence/probability 출력
- 증상 문항인데 span이 비어 있음

---

## 5. Matched Symptom

LLM span을 Hybrid IR로 표준 증상명에 매칭한 결과입니다.

예시:

```json
{
  "slot_id": "throat_irritation",
  "name": "목의 통증",
  "score": 0.9,
  "source_quote": "목이 칼칼하고",
  "normalized_text": "목 자극감",
  "status": "있음",
  "alert": false,
  "ir_method": "bm25_titan_hybrid",
  "ir_trace": {
    "bm25_score": 0.28,
    "vector_score": 0.67,
    "label_score": 0.9,
    "final_score": 0.9,
    "accept_reason": "vector_plus_lexical_or_label",
    "top_candidates": []
  }
}
```

중요:

- `score`는 LLM이 만든 값이 아닙니다.
- BM25, Titan vector similarity, label/alias 직접 일치 신호를 계산한 IR 점수입니다.
- 표준 증상으로 확정되지 않은 span은 `unmatched_spans`에 남습니다.

---

## 6. Onepaper JSON

의사 화면이 읽는 최종 문진 요약 JSON입니다.

예시:

```json
{
  "patient_summary": {
    "display_name": "김*자",
    "age_text": "75세",
    "sex": "여성",
    "department": "이비인후과",
    "visit_type": "initial",
    "received_at": "15:04",
    "audio_duration_text": "음성 0초"
  },
  "symptom_slots": [
    {
      "slot_id": "throat_irritation",
      "name": "목의 통증",
      "score": 0.9,
      "source_quote": "목이 칼칼하고",
      "source_question": "Q1",
      "normalized_text": "목 자극감",
      "status": "있음",
      "explain": "환자가 목의 칼칼함을 직접 호소했습니다."
    }
  ],
  "clinical_clues": [
    {
      "category": "증상맥락",
      "label": "시작시점",
      "summary": "어제부터 증상 시작",
      "source_quote": "어제부터",
      "source_question": "Q1",
      "priority": "일반",
      "related_symptoms": ["목 자극감"]
    }
  ],
  "agenda": [
    {
      "category": "supplement_drug_interaction",
      "type_label": "영양제 병용",
      "summary": "처방약과 영양제 병용 가능 여부 문의",
      "original_quote": "영양제 같이 먹어도 되는지",
      "source_question": "Q4"
    }
  ],
  "doctor_brief": {
    "headline": "목 불편감과 코막힘 호소, 복약 관련 질문 있음",
    "priority": "일반",
    "sections": []
  },
  "review_items": [
    {
      "text": "발열 여부와 실제 체온 확인",
      "priority": "일반",
      "evidence": "목이 칼칼하고 코가 막힘"
    }
  ],
  "transfer_text": "75세 여성 초진 환자. 어제부터 목 불편감과 코막힘 호소.",
  "safety_flags": [],
  "unresolved_items": []
}
```

### 원페이퍼 생성 주체

| 영역 | 생성 방식 |
| --- | --- |
| `patient_summary` | 세션 기본 정보 기반 deterministic 조립 |
| `symptom_slots` | LLM span + Hybrid IR 결과 |
| `clinical_clues` | LLM extraction 결과 중 검증 통과한 clue |
| `agenda` | Q4 LLM extraction questions |
| `doctor_brief` | 원페이퍼 review LLM 또는 fallback |
| `review_items` | Nova Pro review LLM |
| `transfer_text` | 원페이퍼 JSON 기반 Nova Pro review LLM |
| `safety_flags` | quick safety flag와 저장 결과 |

---

## 7. Doctor Response

의사가 원페이퍼에서 환자 질문에 답변하거나 안내 강조사항을 입력한 결과입니다.

예시:

```json
{
  "session_id": "s_...",
  "answers": [
    {
      "category": "supplement_drug_interaction",
      "question": "처방약과 영양제 병용 가능 여부 문의",
      "answer": "진료실에서 안내받은 약과 영양제는 함께 복용 가능합니다."
    }
  ],
  "patient_instruction": "약이랑 영양제 같이 꼭 아침 저녁으로 드세요.",
  "updated_at": "2026-06-02T15:10:00+09:00"
}
```

의사 강조사항은 환자 안내문에서 원문 그대로 보여주는 것이 기본입니다.

---

## 8. Patient Guide JSON

환자 안내문 화면이 읽는 JSON입니다.

예시:

```json
{
  "patient_name": "김*자",
  "date": "2026. 6. 2.",
  "items": [
    {
      "question": "처방약과 영양제 병용 가능 여부 문의",
      "answer": "문제 없이 복용 가능합니다.",
      "tts_text": "문제 없이 복용 가능합니다."
    }
  ],
  "doctor_instruction": "약이랑 영양제 같이 꼭 아침 저녁으로 드세요."
}
```

환자 안내문 LLM은 의학적 내용을 새로 판단하는 것이 아니라, 의사가 입력한 답변을 환자가 읽기 쉬운 문장으로 정리합니다.

---

## 9. Orchestration Trace

LangGraph 처리 경로입니다.

예시:

```json
{
  "graph": "munjin_langgraph_answer_pipeline",
  "version": "v1",
  "nodes": [
    "input_transcript",
    "quick_safety_flag",
    "semantic_extraction",
    "schema_quote_validation",
    "hybrid_ir_match",
    "session_validation_save",
    "safety_guardrail_save",
    "onepaper_refresh",
    "response_payload"
  ],
  "active_path": [
    "input_transcript",
    "quick_safety_flag",
    "semantic_extraction",
    "schema_quote_validation",
    "hybrid_ir_match",
    "session_validation_save",
    "onepaper_refresh",
    "response_payload"
  ],
  "trace": [
    {
      "node": "semantic_extraction",
      "status": "passed",
      "details": {
        "model_id": "apac.amazon.nova-pro-v1:0",
        "attempts": 1,
        "span_count": 2
      }
    }
  ]
}
```

---

## 데이터 원칙 요약

- 환자 원문은 반드시 보존합니다.
- LLM은 미리 정의된 JSON 틀 안의 값만 채웁니다.
- LLM 출력은 schema validator를 통과해야 합니다.
- quote는 원문 substring이어야 합니다.
- LLM 임의 score는 금지합니다.
- 증상 score는 IR 계산 점수입니다.
- rule-based fallback은 기본 운영 경로가 아닙니다.
- 환자 음성 파일은 S3에 저장하지 않습니다.
- 의사 강조사항은 환자 안내문에서 원문 그대로 표시합니다.

---

## 관련 문서

- [LangGraph 파이프라인](LANGGRAPH_PIPELINE.md)
- [프로젝트 구조](PROJECT_STRUCTURE.md)
- [서버리스 백엔드 README](../backend/serverless/README.md)

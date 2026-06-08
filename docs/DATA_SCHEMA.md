# 문진톡톡 내부 JSON 스키마

이 문서는 문진톡톡 MVP에서 오가는 핵심 JSON 구조를 설명합니다.

가장 중요한 원칙은 다음과 같습니다.

```text
JSON 형식은 코드에 미리 정의되어 있고,
LLM은 그 틀 안의 값만 채워야 합니다.
```

LLM이 매번 새로운 형식을 마음대로 만드는 구조가 아닙니다. 백엔드는 Pydantic schema로 필드, 타입, enum, extra field, source_quote를 검증합니다.

또한 현재 구조에서는 DynamoDB와 S3의 역할을 분리합니다.

```text
DynamoDB = 대기열, 상태, 최소 환자 표시 정보, S3 artifact pointer
S3 = 가명처리된 운영 artifact + 최소 설명 trace
```

---

## 전체 데이터 흐름

```text
POST /sessions
  -> DynamoDB minimal session item 생성

POST /process-answer
  -> STT 확정 텍스트 수신
  -> 원천 JSON 기반 RAG 참고 컨텍스트 검색
  -> LLM extraction JSON 생성
  -> Pydantic schema 검증
  -> source_quote 원문 포함 여부 검증
  -> 검증 실패 시 LangGraph retry loop
  -> 증상 문항이면 Hybrid IR matched_slots 생성
  -> S3 answers.redacted.json 저장
  -> S3 onepaper.redacted.json 저장
  -> DynamoDB question_status, risk, status, artifact key 갱신

POST /doctor-response
  -> S3 doctor_review.redacted.json 저장
  -> 환자 안내문 생성
  -> S3 patient_guide.redacted.json 저장
  -> DynamoDB reviewed 상태와 guide key 갱신

GET /onepager/{session_id}
  -> S3 onepaper.redacted.json 조회

GET /guide/{session_id}
  -> S3 patient_guide.redacted.json 조회
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
  "created_at": "2026-06-08T01:20:00+00:00",
  "updated_at": "2026-06-08T01:25:10+00:00",
  "expires_at": 1781000000,
  "status": "completed",
  "queue_number": 3,
  "visit_type": "initial",
  "risk": "none",
  "patient": {
    "name": "김*자",
    "age": 75,
    "age_band": "70대",
    "gender": "여성",
    "department": "이비인후과",
    "doctor": "이민우",
    "receipt_id": "A-0427",
    "honorific": "어르신"
  },
  "artifact": {
    "bucket": "<artifact-bucket-name>",
    "prefix": "sessions/2026-06-08/s_1780379760_45542aeb/",
    "answers_key": "sessions/2026-06-08/s_1780379760_45542aeb/answers.redacted.json",
    "onepaper_key": "sessions/2026-06-08/s_1780379760_45542aeb/onepaper.redacted.json",
    "guide_key": "sessions/2026-06-08/s_1780379760_45542aeb/patient_guide.redacted.json",
    "consent_key": "sessions/2026-06-08/s_1780379760_45542aeb/consent.json",
    "trace_key": "sessions/2026-06-08/s_1780379760_45542aeb/llm_trace.redacted.json"
  },
  "question_status": {
    "Q1": {
      "answered": true,
      "span_count": 2,
      "matched_count": 2,
      "method": "bedrock_nova_pro",
      "has_safety_flag": false
    }
  },
  "onepager_ready": true,
  "guide_ready": false,
  "privacy_consent": {
    "accepted": true,
    "version": "munjin-privacy-consent-v1",
    "method": "patient_tablet_modal",
    "accepted_at": "2026-06-08T01:21:00+00:00",
    "recorded_at": "2026-06-08T01:21:00+00:00"
  }
}
```

### DynamoDB에 저장하지 않는 필드

다음 값은 DynamoDB session item에 저장하지 않습니다.

| 저장하지 않는 값 | 처리 방식 |
| --- | --- |
| 환자 실명 | 마스킹 이름으로만 변환 후 폐기 |
| 생년월일 | 나이/연령대 계산 후 폐기 |
| 연락처 | MVP 저장 대상에서 제외 |
| 문항별 원문 발화 | S3 `answers.redacted.json`에 저장 |
| LLM spans/structured/matched_slots | S3 `answers.redacted.json`에 저장 |
| 원페이퍼 전체 JSON | S3 `onepaper.redacted.json`에 저장 |
| 의사 답변 전문 | S3 `doctor_review.redacted.json`에 저장 |
| 환자 안내문 | S3 `patient_guide.redacted.json`에 저장 |
| LangGraph trace 전문 | 저장하지 않음. 최소 node event와 확정 근거 요약만 S3 `llm_trace.redacted.json`에 저장 |

---

## 2. S3 Artifact Layout

세션별 산출물은 다음 prefix 아래에 저장됩니다.

```text
sessions/YYYY-MM-DD/{session_id}/
  consent.json
  answers.redacted.json
  onepaper.redacted.json
  doctor_review.redacted.json
  patient_guide.redacted.json
  llm_trace.redacted.json
```

S3 artifact는 `artifact_store.py`에서만 직접 읽고 씁니다. 프론트엔드는 S3 URL을 직접 받지 않습니다.

S3 객체 공통 wrapper:

```json
{
  "stored_at": "2026-06-08T01:25:10+00:00",
  "schema_version": "munjin-artifact-v1",
  "payload": {}
}
```

`payload` 안에는 저장 전 `privacy.redact_payload()`가 적용됩니다. 연락처, 주민번호, 이메일, 생년월일 형태의 직접식별정보는 저장 전 1차 마스킹됩니다.

---

## 3. answers.redacted.json

문항별 환자 답변과 운영 화면 조립에 필요한 LLM/IR 결과입니다. 내부 메타데이터,
prompt/response 전문, 후보 목록, 숫자 점수는 이 파일에 저장하지 않습니다.

예시:

```json
{
  "Q1": {
    "text": "어제부터 목이 칼칼하고 코가 막혀요.",
    "confirmed": true,
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
      }
    ],
    "structured": {
      "standardized_text": "어제부터 목이 칼칼하고 코가 막힙니다.",
      "clinical_clues": [],
      "questions": [],
      "unresolved_items": []
    },
    "matched_slots": [
      {
        "slot_id": "throat_irritation",
        "name": "목의 통증",
        "source_quote": "목이 칼칼하고",
        "span_type": "symptom",
        "alert": false,
        "normalized_text": "목 자극감",
        "status": "있음",
        "explain": "환자 표현을 아산백과 기반 증상 인덱스와 비교했고, 어휘 근거와 Titan 의미 벡터 근거가 함께 충족되어 표준 증상으로 매칭했습니다.",
        "ir_method": "bm25_titan_hybrid"
      }
    ]
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

LLM은 score/confidence를 만들 수 없습니다. IR 숫자 점수는 운영 artifact가 아니라
최소 설명 trace 안의 확정 근거 요약으로만 제한 저장됩니다.

### 증상 상태 정책

`type`과 `status`는 함께 해석합니다. 단순히 증상 단어가 등장했다고 해서 모두
현재 불편함 카드로 올라가지 않습니다.

| 상황 | `type` | `status` | 원페이퍼 표시 |
| --- | --- | --- | --- |
| 현재 호소하는 증상 | `symptom`, `new` | `있음` | 오늘 말한 불편함 카드 |
| 이전보다 악화된 증상 | `progress_worsened` | `있음` | 오늘 말한 불편함 카드 + 맥락 단서 |
| 이전과 비슷하게 지속되는 증상 | `progress_unchanged` | `있음` | 오늘 말한 불편함 카드 |
| 현재 명시적으로 없다고 한 증상 | `symptom_absent` | `없음` | clinical_clues 현재양상/부재 단서 |
| 이전 증상이 호전되어 현재 불편함 카드로 올리지 않을 상태 | `progress_improved` | `없음` | clinical_clues 재진경과/호전 단서 |

`symptom_absent`와 `progress_improved`는 Hybrid IR 매칭 대상에서 제외됩니다.
즉, “열은 안 나요”, “두통은 없어졌어요”는 중요한 문진 맥락으로 남지만
“오늘 말한 불편함” 증상 카드로 표시되지 않습니다.
여기서 `progress_improved`의 `status="없음"`은 “현재 불편함 카드 대상이 아님”을
뜻하는 파이프라인 상태입니다. 원문이 완전 소실을 말하지 않았다면 시스템은
“완전히 없어졌다”는 새 사실을 만들지 않고, 호전 맥락 단서로만 보존합니다.

---

## 4. onepaper.redacted.json

의사가 보는 원페이퍼 JSON입니다.

```json
{
  "patient_summary": {
    "display_name": "김*자",
    "age_text": "75세",
    "sex": "여성",
    "department": "이비인후과",
    "received_at": "10:30",
    "audio_duration_text": "확인중",
    "visit_type": "initial"
  },
  "symptom_slots": [],
  "clinical_clues": [],
  "agenda": [],
  "doctor_brief": {
    "headline": "",
    "sections": []
  },
  "review_items": [],
  "transfer_text": "",
  "safety_flags": [],
  "unresolved_items": []
}
```

`review_items`, `doctor_brief`, `transfer_text`는 Nova Pro review가 생성할 수 있지만, schema 검증과 근거 검증을 통과한 경우에만 반영됩니다.

---

## 5. doctor_review.redacted.json

의사가 환자 질문에 답변하거나 강조사항을 적으면 S3에 저장됩니다.

```json
{
  "answers": [
    {
      "question_id": "Q4-1",
      "question_summary": "처방약과 영양제를 같이 먹어도 되는지 궁금함",
      "answer_text": "현재 영양제는 같이 드셔도 됩니다. 새 약이 추가되면 다시 확인해 주세요."
    }
  ],
  "patient_instruction": "증상이 심해지면 즉시 병원에 다시 와주세요.",
  "additional_notes": "증상이 심해지면 즉시 병원에 다시 와주세요.",
  "reviewed_at": "2026-06-08T01:30:00+00:00"
}
```

의사 강조사항은 LLM이 변형하지 않고 환자 안내문에서 별도 카드로 표시합니다.

---

## 6. patient_guide.redacted.json

환자 안내문 JSON입니다.

```json
{
  "generated_at": "2026-06-08T01:31:00+00:00",
  "items": [
    {
      "question": "처방약과 영양제를 같이 먹어도 되는지 궁금함",
      "answer_simple": [
        "현재 드시는 영양제는 이번 약과 같이 드셔도 됩니다.",
        "나중에 다른 약이 추가되면 병원이나 약국에 다시 확인해 주세요."
      ],
      "tts_emphasis_words": ["다른 약", "다시 확인"]
    }
  ],
  "delivery_options": ["screen", "tts", "print"],
  "generation_method": "bedrock_nova_lite_grounded"
}
```

---

## 7. llm_trace.redacted.json

LLM black-box 해소와 의료·법적 이슈 대응을 위한 최소 설명 trace입니다.
운영 화면을 만들기 위한 파일이 아니며, prompt 전문, LLM raw response, 전체 graph
정의, IR top candidate 목록은 저장하지 않습니다.

```json
{
  "Q1": {
    "graph": "munjin_langgraph_answer_pipeline",
    "version": "v2",
    "question_type": "chief_complaint",
    "active_path": [
      "input_transcript",
      "quick_safety_flag",
      "rag_context_retrieval",
      "semantic_extraction",
      "schema_quote_validation",
      "hybrid_ir_match",
      "session_validation_save",
      "onepaper_refresh",
      "response_payload"
    ],
    "events": [
      {
        "node": "semantic_extraction",
        "status": "generated",
        "at": "2026-06-08T01:25:00+00:00",
        "details": {
          "attempt": 1,
          "model_id": "apac.amazon.nova-pro-v1:0",
          "langchain_chain": "langchain_core_prompt_bedrock_json",
          "output_parser": "langchain_json_output_parser",
          "raw_sha256": "..."
        }
      },
      {
        "node": "hybrid_ir_match",
        "status": "matched",
        "details": {
          "method": "bm25_titan_hybrid",
          "matched_count": 1,
          "accepted_matches": [
            {
              "slot_id": "throat_irritation",
              "name": "목의 통증",
              "source_quote": "목이 칼칼하고",
              "ir_method": "bm25_titan_hybrid",
              "accept_reason": "vector_plus_lexical_or_label",
              "bm25_score": 1,
              "vector_score": 0.46,
              "label_score": 1,
              "rank_score": 1.07
            }
          ]
        }
      }
    ],
    "matched_count": 1,
    "span_count": 1
  }
}
```

이 파일의 숫자는 환자에게 보여주는 confidence가 아닙니다. IR 내부 계산이 왜 특정
표준 증상을 채택했는지 사후 검토하기 위한 근거 요약입니다.

---

## 8. Pydantic Validation Error

LLM이 schema나 quote 검증을 끝까지 통과하지 못하면 저장하지 않고 422를 반환합니다.

```json
{
  "error": "semantic_extraction_failed",
  "message": "LLM schema/quote validation failed after retries.",
  "details": {
    "attempts": 3,
    "retry_loop": "langgraph_schema_quote_repair",
    "validation_error_count": 1
  }
}
```

안전 플래그가 있는 경우에는 LLM extraction 실패 중에도 `safety_guardrail_save` 경로로 위험 요약만 저장할 수 있습니다.

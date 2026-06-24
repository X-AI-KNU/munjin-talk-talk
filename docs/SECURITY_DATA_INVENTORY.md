# 문진톡톡 데이터 전수조사 표

## 1. 전수조사 표가 필요한 이유

전수조사 표는 서비스 안에서 생성, 저장, 전달되는 모든 데이터를 한 번에 확인하기 위한 보안 설계 문서입니다.

문진톡톡은 음성 문진, STT, LLM 추출, 증상 매칭, 원페이퍼, 환자 안내문을 다루기 때문에 단순히 "DynamoDB를 쓴다" 또는 "S3를 쓴다" 수준으로는 보안 상태를 판단하기 어렵습니다. 어떤 필드가 개인정보인지, 어떤 필드가 건강정보인지, 어떤 데이터가 LLM으로 전달되는지, 어떤 데이터가 영구 저장되는지를 필드 단위로 나누어야 합니다.

이 문서의 목적은 다음과 같습니다.

- 기존 코드와 현재 코드가 어떤 데이터를 생성하고 저장하는지 확인한다.
- DynamoDB에 남겨도 되는 최소 인덱스 데이터와 S3에 보관할 문진 산출물을 분리한다.
- 음성 원본, 실명, 생년월일, 연락처처럼 저장하면 위험한 데이터를 식별한다.
- Macie, S3 Lifecycle, KMS, IAM, CloudWatch 로그 정책을 어디에 적용해야 하는지 결정한다.
- 코드 변경 시 삭제, 이동, 가명처리 대상이 되는 필드를 명확히 한다.

## 1-1. 2026-06-11 코드 반영 상태

이 문서를 기준으로 다음 변경이 현재 코드에 반영되었습니다.

| 항목 | 반영 상태 | 관련 코드 |
| --- | --- | --- |
| DynamoDB에 실명, 생년월일, 연락처 원문 저장 제거 | 완료 | `backend/serverless/src/sessions.py`, `privacy.py` |
| DynamoDB에 `responses`, `question_results`, `onepager`, `doctor_review`, `patient_guide` 직접 저장 제거 | 완료 | `onepager.py`, `guide.py`, `pipeline_trace.py` |
| S3 artifact 저장소 추가 | 완료 | `artifact_store.py` |
| 동의 상세 S3 저장, DynamoDB 동의 요약 저장 | 완료 | `sessions.py` |
| 답변/LLM/IR 결과 S3 `answers.redacted.json` 저장 | 완료 | `onepager.py` |
| 원페이퍼 S3 `onepaper.redacted.json` 저장 | 완료 | `onepager.py` |
| 의사 답변/환자 안내문 S3 저장 | 완료 | `guide.py` |
| 저장 전 1차 가명처리 helper 추가 | 완료 | `privacy.py` |
| SAM `ArtifactsBucketName` 파라미터 추가 | 완료 | `backend/serverless/template.yaml` |
| API CORS origin 제한 파라미터 추가 | 완료 | `backend/serverless/template.yaml`, `utils.py` |
| 직원/의료진 접근 코드 로그인과 만료 세션 토큰 검증 | 완료 | `security.py`, `handler.py`, `frontend/src/components/auth/RoleLoginModal.jsx` |
| 환자 세션별 접근 토큰 발급·검증 | 완료 | `sessions.py`, `security.py`, `frontend/src/services/api/client.js` |
| S3 artifact 객체 단위 암호화 명시 | 완료 | `artifact_store.py`, `template.yaml` |
| 환자 화면 질문 문구를 백엔드 extraction에 전달 | 완료 | `frontend/src/services/api/transcripts.js`, `pipeline_nodes.py`, `extraction_prompts.py` |
| 증상 slot, alias, safety flag를 도메인팩으로 분리 | 완료 | `domain_config.py`, `data/domain_packs/respiratory.json`, `clinical_terms.py` |
| LLM 임의 confidence/score 필드 차단 회귀 검증 | 완료 | `backend/serverless/tests/test_schema_and_artifact_policy.py` |

제출용 AWS 환경에서 확인한 운영 설정은 다음과 같습니다. 이 항목은 코드에 포함되는 설정이 아니라 AWS 콘솔/계정 정책으로 적용되는 보안 장치입니다.

- S3 Block Public Access
- S3 기본 암호화
- S3 `sessions/` prefix Lifecycle 3일 삭제
- Macie 민감정보 탐지
- DynamoDB TTL(`expires_at`)과 삭제 방지
- CloudWatch Logs 3일 보존
- API Gateway throttling
- Amplify WAF
- CloudTrail, GuardDuty, Security Hub
- AWS Organizations AI Services opt-out 정책

상용화 단계에서는 Lambda IAM role의 S3/DynamoDB/Bedrock 권한을 리소스 ARN 단위로 더 좁히고, Cognito 또는 병원 SSO 기반 사용자별 계정과 감사 로그를 추가해야 합니다.

## 2. 저장소 분리 원칙

문진톡톡 MVP의 목표 구조는 DynamoDB와 S3를 함께 사용하는 하이브리드 구조입니다.

| 구분 | 역할 | 저장 예시 | 이유 |
| --- | --- | --- | --- |
| DynamoDB | 세션 목록, 대기열, 상태 조회용 최소 데이터 | session_id, status, queue_number, patient_display, age_band, gender, risk, s3_prefix | 화면 목록과 빠른 조회에 필요합니다. 민감 원문은 저장하지 않습니다. |
| S3 | 가명처리된 문진 산출물 보관 | answers.redacted.json, onepaper.redacted.json, patient_guide.redacted.json, llm_trace.redacted.json | 구조화된 큰 JSON 산출물을 분리 보관하고 Lifecycle, Macie, KMS를 적용합니다. |
| 메모리 | 처리 중 임시 데이터 | 실시간 STT 원문, LLM 입력 직전 원문 | 처리 후 가명처리 산출물만 남기고 원문은 폐기합니다. |
| 저장 금지 | 원칙적으로 저장하지 않는 데이터 | 음성 원본 파일, 불필요한 실명, 생년월일, 연락처 원문 | 의료 데이터 및 식별정보 위험을 줄이기 위해 저장하지 않습니다. |

## 3. 단계별 전수조사 표

아래 표의 "기존" 항목은 보안 구조를 정리하기 전 MVP 코드에서 확인된 저장 방식을 의미합니다. 현재 제출 기준 코드는 1-1절에 적은 목표 저장 위치 기준으로 정리되어 있습니다.

| 단계 | 관련 코드 | 기존 생성 또는 저장 데이터 | 기존 저장 위치 | 민감도 | 기존 문제 | 목표 저장 위치 | 조치 방향 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 직원 접수 세션 생성 | `backend/serverless/src/sessions.py` `create_session` | 환자명, full_name, 생년월일, 나이, 성별, 접수번호, 진료과, 담당의, 연락처, 초진/재진 | DynamoDB | 개인정보 | full_name, birth_date, phone이 DynamoDB에 직접 저장됨 | DynamoDB 최소값 + 필요 시 S3 가명 산출물 | full_name, birth_date, phone 원문 저장 제거. 환자 표시명, 연령대, 성별, 접수용 무작위 ID만 유지 |
| 환자 동의 기록 | `backend/serverless/src/sessions.py` `save_patient_consent` | 동의 여부, 동의 버전, 동의 항목, 민감정보 동의 항목, 동의 시각 | DynamoDB | 개인정보 처리 기록 | 상세 동의 문구와 항목이 세션 레코드에 그대로 누적됨 | DynamoDB 요약 + S3 `consent.json` | DynamoDB에는 accepted, version, accepted_at만 유지. 상세 내용은 S3에 보관 |
| 음성 인식 준비 | `backend/serverless/src/audio.py` | Transcribe Streaming URL, audio_policy 요약 | DynamoDB | 낮음 | 문항별 STT 세부 상태를 누적하면 불필요한 상태가 늘어남 | DynamoDB | provider, mode, audio_storage=not_stored, last_question_id만 유지 |
| 음성 원본 | 현재 스트리밍 구조에서는 저장하지 않음 | 환자 음성 파일 | 저장하지 않음 | 고위험 건강정보 | S3 업로드 방식으로 되돌아가면 위험 | 저장 금지 | 실시간 스트리밍 유지. 음성 파일 S3 저장 금지 |
| STT 결과 텍스트 | `frontend/src/hooks/useStreamingTranscribe.js`, `backend/serverless/src/pipeline_nodes.py` | 환자 발화 원문 텍스트 | DynamoDB `responses.Qx.text` | 건강정보 | 문진 원문이 DynamoDB에 누적됨 | 메모리 처리 후 S3 `answers.redacted.json` | 저장 전 가명처리. DynamoDB에는 완료 여부와 S3 key만 저장 |
| Q별 의미 추출 | `backend/serverless/src/onepager.py`, `pipeline_graph.py`, `pipeline_nodes.py` | spans, source_quote, normalized_text, structured, clinical_clues, patient_questions | DynamoDB `question_results` | 건강정보 | LLM 추출 산출물이 DynamoDB에 직접 저장됨 | S3 `answers.redacted.json`, `llm_trace.redacted.json` | 운영 답변은 S3로 이동. trace는 최소 node event만 유지 |
| 증상 IR 매칭 | `backend/serverless/src/retrieval.py` | matched_slots, symptom label, alias, rank_score, 근거 문구 | S3 `answers.redacted.json`, `onepaper.redacted.json`, `llm_trace.redacted.json` | 건강정보 | 운영 artifact와 UI에 숫자 점수나 후보 목록이 노출되면 과신을 유발할 수 있음 | S3 운영 artifact + 최소 trace | 운영 onepaper에는 점수 제거. 확정 IR 근거 요약은 최소 trace에만 저장 |
| Safety Flag | `backend/serverless/src/clinical_terms.py`, `onepager.py`, `pipeline_nodes.py` | 객혈, 피 표현 등 위험 플래그, risk | DynamoDB | 건강정보 요약 | 상세 원문이 함께 묶일 수 있음 | DynamoDB 요약 + S3 상세 | DynamoDB에는 risk level, flag code만 유지. 상세 근거는 S3 |
| 원페이퍼 생성 | `backend/serverless/src/onepager.py` `build_onepager` | 환자 요약, 증상 목록, 문진 맥락, 의료진 확인 항목, EMR 문장 | DynamoDB `onepager` | 건강정보 | 원페이퍼 전체가 DynamoDB에 저장됨 | S3 `onepaper.redacted.json` | DynamoDB에는 s3 key, ready status, risk 요약만 저장 |
| 의사 답변 저장 | `backend/serverless/src/guide.py` `save_doctor_response` | 의사 답변, 환자 안내 강조사항, 추가 메모 | DynamoDB `doctor_review` | 건강정보 | 의사 입력 전문이 DynamoDB에 저장됨 | S3 `doctor_review.redacted.json` | DynamoDB에는 reviewed_at, guide_ready만 유지 |
| 환자 안내문 생성 | `backend/serverless/src/guide.py` | patient_guide, 안내문 문장, 말로 재생할 문장 | DynamoDB `patient_guide` | 건강정보 | 환자 안내문 전체가 DynamoDB에 저장됨 | S3 `patient_guide.redacted.json` | DynamoDB에는 guide_ready, guide_s3_key만 유지 |
| API 응답 | `backend/serverless/src/sessions.py` `public_session` | fullName, birthDate, phone, responses, onepager, privacyConsent | Frontend 응답 | 개인정보 + 건강정보 | 목록 조회 API가 많은 민감 데이터를 반환할 가능성 | 최소 응답 + 필요 시 권한별 artifact 조회 | public_session에서 직접식별자와 원문 응답 제거 |
| CloudWatch 로그 | Lambda 전체 | 오류 메시지, payload 일부 가능성 | CloudWatch Logs | 잠재적 민감정보 | 예외 로그에 환자 발화가 섞이면 위험 | 로그 최소화 | session_id, route, error code 중심으로 로깅. 원문 텍스트 로그 금지 |
| Bedrock 호출 | `llm.py`, `langchain_prompting.py`, `guide.py`, `pipeline_nodes.py` | 환자 발화, 구조화 JSON, 원페이퍼, 의사 답변 | 외부 AWS AI 서비스 호출 | 건강정보 | LLM 입력에 식별정보가 포함되면 위험 | 가명처리 payload만 전달 | 이름, 생년월일, 연락처 제거 후 호출. 모델 학습 opt-out 정책 별도 확인 |
| Macie 점검 | AWS 콘솔 설정 예정 | S3 객체의 민감정보 탐지 결과 | Macie | 보안 점검 데이터 | DynamoDB 직접 점검 도구가 아님 | S3 artifact bucket | S3로 이동된 문진 산출물에 Macie scan 적용 |

## 4. 필드별 전수조사 표

아래 표의 "기존 위치"는 수정 전 저장 위치입니다. 현재 코드는 DynamoDB 직접 저장 제거 대상 필드를 S3 artifact 또는 메모리 처리로 이동했습니다.

| 필드 | 기존 위치 | 기존 용도 | 민감도 | 목표 처리 |
| --- | --- | --- | --- | --- |
| `session_id` | DynamoDB | 세션 식별 | 낮음 | DynamoDB 유지 |
| `queue_number` | DynamoDB | 대기 순번 | 낮음 | DynamoDB 유지 |
| `status` | DynamoDB | 진행 상태 | 낮음 | DynamoDB 유지 |
| `visit_type` | DynamoDB | 초진/재진 구분 | 낮음 | DynamoDB 유지 |
| `created_at`, `updated_at`, `expires_at` | DynamoDB | 생성, 수정, TTL | 낮음 | DynamoDB 유지 |
| `patient.name` | DynamoDB | 화면 표시용 마스킹 이름 | 개인정보 | `patient_display`로 이름 변경 후 유지 |
| `patient.full_name` | DynamoDB | 접수 환자 실명 | 고위험 개인정보 | 저장 금지. 직원 화면에서 입력 후 세션 생성 시 마스킹값만 저장 |
| `patient.birth_date` | DynamoDB | 나이 계산 및 본인 확인 | 고위험 개인정보 | 저장 금지. age 또는 age_band만 저장 |
| `patient.phone` | DynamoDB | 연락처 | 고위험 개인정보 | 저장 금지. MVP에서는 사용하지 않음 |
| `patient.receipt_id` | DynamoDB | 접수번호 | 조건부 개인정보 | 비식별 난수이면 DynamoDB 유지. 병원 실접수번호이면 가명 ID로 대체 |
| `patient.department` | DynamoDB | 진료과 표시 | 낮음 | DynamoDB 유지 |
| `patient.doctor` | DynamoDB | 담당의 표시 | 낮음 | DynamoDB 유지 |
| `patient.gender` | DynamoDB | 진료 문맥 | 준민감 | DynamoDB 유지 가능 |
| `patient.age` | DynamoDB | 진료 문맥 | 준민감 | `age_band` 우선. 필요 시 age 유지 여부 검토 |
| `privacy_consent.accepted` | DynamoDB | 동의 여부 | 개인정보 처리 기록 | DynamoDB 유지 |
| `privacy_consent.version` | DynamoDB | 동의 문구 버전 | 낮음 | DynamoDB 유지 |
| `privacy_consent.accepted_at` | DynamoDB | 동의 시각 | 개인정보 처리 기록 | DynamoDB 유지 |
| `privacy_consent.privacy_items` | DynamoDB | 상세 동의 항목 | 개인정보 처리 기록 | S3 `consent.json` 이동 |
| `responses.Qx.text` | DynamoDB | 환자 발화 원문 | 건강정보 | S3 `answers.redacted.json` 이동. 원문은 저장 전 가명처리 |
| `responses.Qx.spans` | DynamoDB | LLM 추출 단위 | 건강정보 | S3 `answers.redacted.json` 이동 |
| `source_quote` | DynamoDB | 원문 근거 | 건강정보 | S3 이동. 직접식별정보 제거 후 저장 |
| `normalized_text` | DynamoDB | 표준화 문장 | 건강정보 | S3 이동 |
| `structured` | DynamoDB | Q별 구조화 결과 | 건강정보 | S3 이동 |
| `clinical_clues` | DynamoDB | 문진 맥락 | 건강정보 | S3 이동 |
| `patient_questions` | DynamoDB | 환자 질문 | 건강정보 | S3 이동 |
| `matched_slots` | DynamoDB | 증상 매칭 결과 | 건강정보 | S3 이동. DDB에는 count/status만 유지 |
| `rank_score` | S3 최소 trace | IR 내부 계산값 | 낮음 | 운영 artifact와 UI 응답에서 제거. 확정 매칭의 감사용 trace에만 제한 저장 |
| `onepager` | DynamoDB | 의사용 원페이퍼 | 건강정보 | S3 `onepaper.redacted.json` 이동 |
| `review_items` | DynamoDB | 의료진 확인 항목 | 건강정보 | S3 이동 |
| `transfer_text` | DynamoDB | EMR 초안 | 건강정보 | S3 이동 |
| `doctor_review.answers` | DynamoDB | 의사 답변 | 건강정보 | S3 `doctor_review.redacted.json` 이동 |
| `doctor_review.patient_instruction` | DynamoDB | 환자 강조사항 | 건강정보 | S3 이동 |
| `patient_guide` | DynamoDB | 환자 안내문 | 건강정보 | S3 `patient_guide.redacted.json` 이동 |
| `pipeline_trace` | DynamoDB | LLM/검증 추적 | 건강정보 가능 | 원문 없는 최소 node event만 S3 `llm_trace.redacted.json`에 저장 |
| `llm_meta` | DynamoDB | 모델 호출 메타데이터 | 낮음 또는 건강정보 가능 | 운영 artifact에서 제거. 모델 ID, parser, raw hash 등 최소값만 trace에 저장 |
| `risk` | DynamoDB | 위험도 요약 | 건강정보 요약 | DynamoDB 유지 가능 |
| `safety_flag` | DynamoDB | 위험 플래그 상세 | 건강정보 | DDB에는 flag code만, 상세 근거는 S3 |

## 5. 목표 S3 객체 구조

```text
sessions/YYYY-MM-DD/{session_id}/
  consent.json
  answers.redacted.json
  onepaper.redacted.json
  doctor_review.redacted.json
  patient_guide.redacted.json
  llm_trace.redacted.json
```

각 파일은 다음 원칙을 지킵니다.

- 실명, 생년월일, 연락처 원문을 포함하지 않습니다.
- 원문 발화는 의료진 확인에 필요한 범위로만 보관합니다.
- `source_quote`는 LLM 근거 검증을 위해 보관하되, 직접식별정보가 있으면 마스킹합니다.
- S3 bucket은 Block Public Access, SSE-KMS, Lifecycle 3일 삭제, Macie 민감정보 탐지를 적용합니다.
- Frontend는 S3에 직접 접근하지 않습니다. Lambda가 필요한 산출물만 읽어 API로 반환합니다.

## 6. 목표 DynamoDB 세션 예시

```json
{
  "session_id": "s_1781000000000_ab12cd",
  "queue_number": 3,
  "status": "waiting_doctor",
  "visit_type": "initial",
  "patient": {
    "name": "김*동",
    "age": 75,
    "age_band": "70대",
    "gender": "여성",
    "receipt_id": "R-0427",
    "department": "이비인후과",
    "doctor": "이민우",
    "honorific": "어르신"
  },
  "risk": "none",
  "privacy_consent": {
    "accepted": true,
    "version": "munjin-privacy-consent-2026-06-07",
    "accepted_at": "2026-06-08T10:20:30+09:00"
  },
  "artifact": {
    "bucket": "<artifact-bucket-name>",
    "prefix": "sessions/2026-06-08/s_1781000000000_ab12cd/",
    "answers_key": "sessions/2026-06-08/s_1781000000000_ab12cd/answers.redacted.json",
    "onepaper_key": "sessions/2026-06-08/s_1781000000000_ab12cd/onepaper.redacted.json",
    "guide_key": "sessions/2026-06-08/s_1781000000000_ab12cd/patient_guide.redacted.json",
    "trace_key": "sessions/2026-06-08/s_1781000000000_ab12cd/llm_trace.redacted.json"
  },
  "created_at": "2026-06-08T10:10:00+09:00",
  "updated_at": "2026-06-08T10:20:30+09:00",
  "expires_at": 1781000000
}
```

## 7. Macie 적용 위치

Macie는 DynamoDB 내부 필드를 직접 가명처리하는 도구가 아닙니다. Macie는 S3 객체에 저장된 데이터에서 민감정보를 탐지하고 경고하는 보안 점검 도구입니다.

따라서 문진톡톡에서 Macie를 쓰려면 다음 흐름이 적절합니다.

1. Lambda가 STT/LLM 산출물을 가명처리합니다.
2. 가명처리된 JSON artifact를 S3에 저장합니다.
3. Macie가 S3 bucket을 스캔합니다.
4. 주민번호, 연락처, 이메일, 이름 패턴 등 민감정보가 남아 있으면 finding을 발생시킵니다.
5. 운영자는 finding을 보고 가명처리 규칙 또는 코드 버그를 수정합니다.

즉, Macie는 "저장 전 필터"가 아니라 "저장 후 감사 장치"입니다. 저장 전 차단은 Lambda 내부 가명처리 코드와 schema validator가 담당해야 합니다.

## 8. 현재 구현 기준 점검

2026-06-08 기준 현재 코드는 이 전수조사 표의 핵심 저장 경계를 반영한 상태입니다. 즉, 이전 MVP처럼 DynamoDB 한 item에 환자 식별정보, 문항별 원문, LLM 추출 결과, 원페이퍼, 환자 안내문을 모두 직접 저장하는 구조가 아닙니다.

현재 코드에서 적용된 기준은 다음과 같습니다.

- DynamoDB는 "누가 대기 중인지, 어떤 상태인지, 어디 S3 artifact를 보면 되는지"를 확인하기 위한 최소 세션 상태만 가집니다.
- 문진 답변, LLM extraction 결과, LangGraph trace, Hybrid IR 결과, 원페이퍼, 의사 답변, 환자 안내문은 가명처리 후 S3 artifact로 저장합니다.
- 음성 원본 파일은 S3에 저장하지 않습니다. 환자 음성은 Transcribe Streaming을 거쳐 텍스트만 문진 처리 흐름에 들어갑니다.
- 실명, 생년월일, 연락처 원문은 세션 생성 시 마스킹 또는 요약 정보로 변환하며 DynamoDB에 그대로 남기지 않습니다.
- Macie는 S3에 남은 민감정보를 찾아내는 사후 감사 장치로 둡니다. 저장 전 차단은 Lambda의 `privacy.py`, schema validator, 저장 경계 코드가 담당합니다.

다만 다음 항목은 코드만으로 끝나는 문제가 아니라 AWS 운영 설정이 필요합니다.

| 항목 | 현재 코드 상태 | AWS에서 추가 확인할 것 |
| --- | --- | --- |
| S3 공개 차단 | 프론트는 S3에 직접 접근하지 않고 Lambda만 artifact를 읽음 | bucket Block Public Access 활성화 |
| S3 암호화 | 저장 코드에서 SSE-S3 또는 SSE-KMS 헤더 명시 | 필요 시 `S3KmsKeyId`에 KMS key 지정 |
| S3 보존 기간 | artifact key가 세션별 prefix로 분리됨 | `sessions/` prefix Lifecycle 3일 삭제 |
| Macie | S3 artifact 구조로 민감정보 감사 가능 | artifact bucket에 Macie sensitive data discovery 적용 |
| DynamoDB 보존 기간 | `expires_at` 필드 구조 사용 | TTL 속성 이름을 `expires_at`으로 활성화 |
| CloudWatch 로그 | 코드에서 원문 로그를 남기지 않는 방향으로 정리 | 로그 그룹 보존 기간 3~7일 설정 |
| Bedrock/Transcribe 데이터 정책 | 코드상 음성 원본 저장 없음 | AWS Organizations AI services opt-out 정책 확인 |
| API 접근 제어 | 직원/의료진 접근 코드 로그인, HMAC 서명 만료 세션 토큰, 환자 세션 토큰 검증 | 상용화 시 Cognito/SSO와 사용자별 감사 로그로 확장 |

따라서 이 문서는 현재 코드가 지키는 저장 경계와 AWS 콘솔에서 확인할 운영 설정을 함께 정리한 기준 문서입니다.

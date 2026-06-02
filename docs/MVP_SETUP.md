# 문진톡톡 MVP 실행 가이드

이 문서는 문진톡톡 MVP를 로컬에서 실행하거나 AWS test 환경과 연결해 확인하는 방법을 설명합니다.

---

## 먼저 알아야 할 실행 방식

문진톡톡은 프론트엔드와 백엔드가 분리되어 있습니다.

```text
frontend/
  React + Vite 화면

backend/serverless/
  AWS API Gateway + Lambda + DynamoDB + Bedrock + Transcribe
```

실행 방식은 두 가지입니다.

| 방식 | 용도 | 백엔드 필요 여부 |
| --- | --- | --- |
| UI 목업 모드 | 화면 레이아웃만 확인 | 필요 없음 |
| 실제 MVP 모드 | STT, LLM, IR, DynamoDB까지 확인 | AWS 백엔드 필요 |

실제 기능 검증은 반드시 실제 MVP 모드로 해야 합니다.

---

## 준비물

로컬:

- Node.js 20.19 이상 또는 22.12 이상
- npm
- Git
- Chrome 또는 Edge

백엔드 배포:

- AWS CLI
- AWS SAM CLI
- Python 3.12
- AWS 계정 권한
- Bedrock model access

AWS 서비스:

- API Gateway
- Lambda
- DynamoDB
- Amazon Transcribe Streaming
- Amazon Bedrock
- Amazon Titan Text Embeddings
- S3 artifact bucket

---

## 1. 저장소 확인

```powershell
cd C:\Users\CGB\munjin-talk-talk-mvp
git status --short --branch
```

test 브랜치에서 작업 중인지 확인:

```text
## test...origin/test
```

---

## 2. 프론트엔드 로컬 실행

```powershell
cd C:\Users\CGB\munjin-talk-talk-mvp\frontend
npm install
Copy-Item .env.example .env.local
```

실제 AWS test 백엔드와 연결하려면 `frontend/.env.local`을 수정합니다.

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
VITE_ENABLE_MOCKS=false
```

실행:

```powershell
npm run dev -- --host 127.0.0.1 --port 5173
```

브라우저:

```text
http://127.0.0.1:5173/staff
```

---

## 3. UI 목업 모드

AWS 없이 화면만 보고 싶을 때:

```text
VITE_API_BASE_URL=
VITE_ENABLE_MOCKS=true
```

주의:

- 이 모드는 실제 Bedrock, Transcribe, DynamoDB를 쓰지 않습니다.
- 성능 검증이나 LLM 파이프라인 검증으로 보면 안 됩니다.
- 발표 전 화면 레이아웃 확인용입니다.

---

## 4. 실제 MVP 모드

실제 AWS backend endpoint를 넣습니다.

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
VITE_ENABLE_MOCKS=false
```

이때 동작:

- 접수처 세션 생성: DynamoDB 저장
- 환자 음성 인식: Transcribe Streaming
- 답변 처리: Lambda LangGraph 파이프라인
- LLM extraction: Bedrock Nova
- 증상 매칭: BM25 + Titan Vector
- 원페이퍼 조회: DynamoDB + review LLM
- 안내문 조회: guide LLM 또는 저장된 guide

---

## 5. 백엔드 배포

자세한 배포는 [AWS 배포 가이드](DEPLOYMENT.md)와 [서버리스 README](../backend/serverless/README.md)를 참고하세요.

기본 명령:

```powershell
cd C:\Users\CGB\munjin-talk-talk-mvp\backend\serverless
sam build
sam deploy --guided
```

test 배포 예시:

```powershell
cd C:\Users\CGB\munjin-talk-talk-mvp\backend\serverless

$env:SAM_CLI_TELEMETRY='0'
$env:APPDATA='C:\Users\CGB\AppData\Local\Temp'
$env:Path='C:\Users\CGB\AppData\Local\Programs\Python\Python312;C:\Users\CGB\AppData\Local\Programs\Python\Python312\Scripts;' + $env:Path

& 'C:\Program Files\Amazon\AWSSAMCLI\bin\sam.cmd' build

& 'C:\Program Files\Amazon\AWSSAMCLI\bin\sam.cmd' deploy `
  --stack-name munjin-mvp-backend-test `
  --region ap-northeast-2 `
  --resolve-s3 `
  --capabilities CAPABILITY_IAM `
  --no-confirm-changeset `
  --no-fail-on-empty-changeset `
  --parameter-overrides "SessionsTableName=MunjinSessionsTest ArtifactsBucketName=<bucket-name> LambdaRoleArn=<lambda-role-arn> CustomVocabularyName=unused"
```

---

## 6. 프론트엔드 빌드

```powershell
cd C:\Users\CGB\munjin-talk-talk-mvp\frontend
npm run build
```

결과:

```text
frontend/dist/index.html
frontend/dist/assets/
```

---

## 7. 기본 화면 확인 순서

### 1단계: 접수처

URL:

```text
/staff
```

확인:

- 이름 입력
- 생년월일 입력
- 성별 선택
- 연락처 자동 형식
- 초진/재진 선택
- 문진 세션 생성
- 오늘 접수 목록에 환자 표시

### 2단계: 환자 태블릿

URL:

```text
/patient/{sessionId}
```

확인:

- 환자 이름과 초진/재진 표시
- 질문 화면 표시
- 마이크 권한 요청
- 실시간 인식 문구 표시
- 확인 화면에서 “맞아요” 또는 “다시 말할게요”
- 위험 표현 시 직원 호출 화면

### 3단계: 의사 대기열

URL:

```text
/doctor/queue
```

확인:

- 문진 완료 환자 표시
- 우선 확인 환자 표시
- 원페이퍼 이동

### 4단계: 원페이퍼

URL:

```text
/doctor/{sessionId}
```

확인:

- 오늘 말한 불편함
- 원문 quote
- 표준 증상명
- IR score
- 문진 맥락 chip
- 의료진 확인 항목
- Q4 환자 질문과 답변 입력
- 환자 안내 강조사항

### 5단계: 안내문

URL:

```text
/guide/{sessionId}
```

확인:

- 의사 답변 표시
- 의사 강조사항 원문 표시
- 말로 재생하기
- 종이 출력 화면

---

## 8. API 스모크 테스트

PowerShell에서 API endpoint가 실제 동작하는지 확인합니다.

```powershell
@'
const API = 'https://<api-id>.execute-api.ap-northeast-2.amazonaws.com';
const transcript = '\uC5B4\uC81C\uBD80\uD130 \uBAA9\uC774 \uCE7C\uCE7C\uD558\uACE0 \uCF54\uAC00 \uB9C9\uD600\uC694.';

const sessionRes = await fetch(`${API}/sessions`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
  body: JSON.stringify({
    visit_type: 'initial',
    patient: {
      full_name: '\uD14C\uC2A4\uD2B8\uD658\uC790',
      birth_date: '1950-09-17',
      gender: '\uC5EC\uC131',
      receipt_id: `T-${Date.now()}`,
      department: '\uC774\uBE44\uC778\uD6C4\uACFC',
      doctor: '\uD14C\uC2A4\uD2B8\uC758\uC0AC',
      phone: '010-0000-0000'
    }
  })
});
const session = await sessionRes.json();
const sessionId = session.session_id || session.sessionId;

const answerRes = await fetch(`${API}/process-answer`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
  body: JSON.stringify({
    session_id: sessionId,
    question_id: 'Q1',
    question_type: 'chief_complaint',
    visit_type: 'initial',
    transcript
  })
});
const answer = await answerRes.json();
console.log(JSON.stringify({
  status: answerRes.status,
  validator_passed: answer.validator_passed,
  spans: answer.spans,
  matched_slots: answer.matched_slots,
  active_path: answer.orchestration?.active_path
}, null, 2));
'@ | node --input-type=module -
```

정상 확인:

- status 200
- `validator_passed: true`
- `spans`에 원문 quote 존재
- `matched_slots`에 표준 증상 존재
- `active_path` 마지막이 `response_payload`

---

## 9. 자주 나는 문제

### 세션 생성 버튼을 눌러도 반응이 없음

확인:

- `VITE_API_BASE_URL`이 비어 있지 않은지
- Amplify 환경 변수에 test backend URL이 들어갔는지
- Lambda `/sessions` 로그에 오류가 있는지
- DynamoDB table name이 SAM parameter와 맞는지

### 마이크가 작동하지 않음

확인:

- localhost 또는 HTTPS인지
- 브라우저 마이크 권한이 허용되었는지
- `/transcribe-stream-url` API가 200인지
- Lambda role에 Transcribe Streaming 권한이 있는지

### Q3 이후 오류가 발생함

확인:

- CloudWatch에서 `/process-answer` 오류 확인
- Bedrock model access 확인
- Pydantic validation error 확인
- `ALLOW_RULE_FALLBACK=false` 상태에서는 LLM 검증 실패 시 오류가 정상적으로 반환됨

### 원페이퍼에 증상이 안 보임

확인:

- `responses.Qx.spans`가 비어 있는지
- `matched_slots`가 비어 있는지
- `ir_trace`에 reject reason이 있는지
- Q type이 증상 문항인지

### 안내문에 의사 강조사항이 이상함

확인:

- `doctor_review.patient_instruction` 또는 관련 저장 필드 확인
- 의사 강조사항은 원문 그대로 표시되어야 함
- guide LLM이 강조사항을 새로 바꾸지 않도록 프론트 표시 경로 확인

---

## 10. 테스트 후 정리

테스트 데이터는 비용과 개인정보 관점에서 오래 남기지 않는 것이 좋습니다.

정리 대상:

- DynamoDB `MunjinSessionsTest` item
- CloudWatch Lambda log stream
- SAM artifact bucket 오래된 객체
- Transcribe 작업 기록

현재 streaming STT는 환자 음성 파일을 S3에 저장하지 않는 구조입니다.

---

## 관련 문서

- [프론트엔드 README](../frontend/README.md)
- [서버리스 백엔드 README](../backend/serverless/README.md)
- [AWS 배포 가이드](DEPLOYMENT.md)
- [LangGraph 파이프라인](LANGGRAPH_PIPELINE.md)

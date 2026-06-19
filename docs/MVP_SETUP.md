# 문진톡톡 MVP 실행 및 점검 가이드

이 문서는 개발자와 시연 준비자가 문진톡톡 MVP를 로컬 또는 AWS test 환경에서 실행하고 점검하는 방법을 설명합니다.

문진톡톡은 프론트엔드만으로 완전한 기능을 수행하지 않습니다. 음성 인식, LLM extraction, Hybrid IR, 원페이퍼 생성, 환자 안내문 저장은 AWS 백엔드와 연결되어야 실제로 동작합니다.

---

## 1. 실행 모드

| 모드 | 설명 | 사용 상황 |
| --- | --- | --- |
| 프론트 로컬 실행 | `localhost:5173`에서 React 앱 실행 | UI 수정, 화면 확인 |
| AWS test 연결 | 로컬 프론트가 API Gateway test backend를 호출 | 실제 STT, Bedrock, DynamoDB, S3 artifact 테스트 |
| Amplify test 배포 | GitHub `test` 브랜치 기준 Amplify 배포 | 팀 공유 테스트 |
| Amplify main 배포 | GitHub `main` 브랜치 기준 Amplify 배포 | 발표 또는 외부 공유 |

---

## 2. 현재 MVP 아키텍처 요약

```text
React/Vite Frontend
  -> API Gateway
  -> Lambda Python 3.12
  -> DynamoDB minimal session state
  -> S3 redacted artifact bucket
  -> Amazon Bedrock Nova/Titan
  -> Amazon Transcribe Streaming
```

중요한 저장 규칙:

- 음성 원본 파일은 저장하지 않습니다.
- DynamoDB에는 세션 상태와 S3 key만 저장합니다.
- 문진 답변, 원페이퍼, trace, 의사 답변, 안내문은 S3 artifact로 저장합니다.
- S3 artifact는 저장 전 `privacy.py`에서 1차 가명처리를 거칩니다.

---

## 3. 필수 준비물

로컬 개발:

- Node.js 20.19 이상 또는 22.12 이상
- npm
- Python 3.12
- AWS SAM CLI

AWS 테스트:

- AWS CLI 로그인 또는 콘솔 권한
- DynamoDB table
- S3 artifact bucket
- Lambda execution role
- Bedrock model access
- Amplify app
- HTTPS 접속 가능한 프론트 URL

---

## 4. 프론트엔드 로컬 실행

```powershell
cd C:\Users\CGB\munjin-talk-talk-mvp\frontend
npm install
Copy-Item .env.example .env.local
npm run dev -- --host 127.0.0.1 --port 5173
```

PowerShell 실행 정책 때문에 `npm`이 막히면 다음처럼 실행합니다.

```powershell
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

접속:

```text
http://127.0.0.1:5173/staff
```

---

## 5. AWS 백엔드 연결

`frontend/.env.local`에 API Gateway URL을 입력합니다.

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
```

저장 후 dev server를 재시작합니다.

```powershell
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

---

## 6. 백엔드 빌드와 배포

공개 저장소에는 원천 의료 백과 본문과 파생 증상 인덱스·embedding cache가 포함되지 않습니다. Hybrid IR까지 포함해 배포하려면 `sam build` 전에 팀 내부 비공개 데이터 저장소에서 아래 파일을 `backend/serverless/src/data/`에 배치합니다.

- `diseases_cleaned.json`
- `symptom_index.json`
- `symptom_embeddings_amazon.titan-embed-text-v2_0_512.json`

```powershell
cd C:\Users\CGB\munjin-talk-talk-mvp\backend\serverless
sam build
sam deploy --guided
```

test 환경 예시:

```text
Stack Name: munjin-mvp-backend-test
AWS Region: ap-northeast-2
Parameter SessionsTableName: MunjinSessionsTest
Parameter ArtifactsBucketName: <s3-artifact-bucket-name>
Parameter LambdaRoleArn: <lambda-role-arn>
Parameter CustomVocabularyName:
Confirm changes before deploy: y
Allow SAM CLI IAM role creation: n
MunjinApiFunction has no authentication. Is this okay?: y
```

배포 완료 후 출력되는 `ApiEndpoint`를 Amplify 또는 `.env.local`의 `VITE_API_BASE_URL`에 입력합니다.

---

## 7. Amplify 브랜치/환경 점검

Amplify에서 `main`, `test`, 별도 스테이징 앱 중 어떤 환경을 사용하더라도 다음 값은 반드시 확인합니다.

```text
Branch: main 또는 test
Monorepo app root: frontend
Build command: npm run build
Build output directory: dist
Environment variable:
  VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
```

주의:

- `main`과 `test`가 다른 백엔드를 바라보려면 브랜치별 환경 변수를 별도로 설정해야 합니다.
- Amplify UI에서 브랜치별 환경 변수 선택이 어려우면 운영 앱과 검증 앱을 별도로 생성하는 방식이 더 안전합니다.

---

## 8. Smoke Test 절차

### 8-1. 접수처

1. `/staff` 접속
2. 환자 이름, 생년월일, 성별, 진료과, 담당의 입력
3. 초진 또는 재진 선택
4. `문진 세션 생성` 클릭
5. 오늘 접수 목록에 환자가 나타나는지 확인

확인할 점:

- DynamoDB에 `patient.full_name`, `patient.birth_date`, `patient.phone`이 저장되지 않아야 합니다.
- `patient.name`은 마스킹된 표시명이어야 합니다.
- `artifact.prefix`와 S3 key들이 생성되어야 합니다.

### 8-2. 동의 모달

1. 환자 태블릿 화면으로 이동
2. 서비스 이용 동의 모달 확인
3. 개인정보 수집·이용 안내 체크
4. 건강 관련 문진 정보 처리 동의 체크
5. 동의 후 문진 시작

확인할 점:

- S3에 `consent.json`이 생성되어야 합니다.
- DynamoDB에는 동의 요약만 저장되어야 합니다.

### 8-3. 환자 문진

1. Q1부터 Q4까지 음성 입력
2. STT 결과 확인 화면에서 `맞아요` 선택
3. 각 문항 처리 후 다음 문항으로 이동
4. 마지막 문항 후 완료 화면 확인

확인할 점:

- 음성 원본 파일이 S3에 생성되지 않아야 합니다.
- S3 `answers.redacted.json`이 생성되어야 합니다.
- S3 `llm_trace.redacted.json`이 생성되어야 합니다.
- DynamoDB에는 `responses`, `question_results`가 없어야 합니다.

### 8-4. 원페이퍼

1. `/doctor/:sessionId` 접속
2. 오늘 말한 불편함 확인
3. 원문 quote 확인
4. 문진 맥락 chip 확인
5. 의료진 확인 항목 확인
6. 환자 질문에 답변 입력
7. 환자 안내 강조사항 입력
8. 환자 안내문 생성 버튼 클릭

확인할 점:

- S3 `onepaper.redacted.json`이 생성되어야 합니다.
- 증상 카드에 숫자 점수가 표시되지 않아야 합니다.
- 환자 질문이 Q4 agenda로 분리되어야 합니다.

### 8-5. 안내문

1. `/guide/:sessionId` 접속
2. 의사 답변 기반 안내문 확인
3. 선생님 강조사항이 원문 그대로 표시되는지 확인
4. 말로 재생하기 버튼 확인
5. 종이 출력 화면 확인

확인할 점:

- S3 `doctor_review.redacted.json`이 생성되어야 합니다.
- S3 `patient_guide.redacted.json`이 생성되어야 합니다.
- 의사가 적은 강조사항은 LLM이 바꾸지 않아야 합니다.

---

## 9. 운영 API 확인 예시

세션 생성:

```powershell
$base = "https://<api-id>.execute-api.ap-northeast-2.amazonaws.com"

$body = @{
  visit_type = "initial"
  patient = @{
    full_name = "테스트환자"
    birth_date = "1950-09-17"
    gender = "여성"
    receipt_id = "R-0001"
    department = "이비인후과"
    doctor = "이민우"
    phone = "010-0000-0000"
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post -Uri "$base/sessions" -ContentType "application/json" -Body $body
```

이 예시는 입력 payload입니다. 백엔드는 이 값을 그대로 DynamoDB에 저장하지 않습니다.

문항 처리:

```powershell
$answer = @{
  session_id = "<session_id>"
  question_id = "Q1"
  transcript = "어제부터 목이 칼칼하고 코가 막혀요"
  visit_type = "initial"
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Method Post -Uri "$base/process-answer" -ContentType "application/json" -Body $answer
```

원페이퍼 조회:

```powershell
Invoke-RestMethod -Method Get -Uri "$base/onepager/<session_id>"
```

---

## 10. 자주 발생하는 문제

| 문제 | 원인 | 해결 |
| --- | --- | --- |
| 문진 세션 생성이 안 됨 | `VITE_API_BASE_URL`이 비었거나 잘못됨 | `.env.local` 또는 Amplify 환경 변수 확인 |
| 환자 태블릿에서 마이크가 안 됨 | HTTPS가 아니거나 브라우저 권한 거부 | Amplify URL 또는 localhost 사용, 마이크 권한 허용 |
| STT 결과가 비어 있음 | 마이크 입력 없음, Transcribe 연결 실패 | 브라우저 console, `/transcribe-stream-url` 응답 확인 |
| Q 처리 후 validator 오류 | LLM 출력이 schema/source_quote 검증 실패 | CloudWatch, S3 trace 확인 |
| 원페이퍼가 비어 있음 | `/process-answer` 실패 또는 S3 artifact 없음 | S3 `answers.redacted.json` 확인 |
| 안내문이 안 나옴 | 의사 답변 저장 실패 또는 guide generation 실패 | S3 `doctor_review.redacted.json`, `patient_guide.redacted.json` 확인 |
| S3 AccessDenied | Lambda role 권한 부족 | Lambda role에 artifact bucket `GetObject`, `PutObject` 권한 추가 |

---

## 11. 검증 명령

프론트엔드:

```powershell
cd frontend
npm.cmd run build
```

백엔드:

```powershell
python -m compileall backend/serverless/src
```

SAM:

```powershell
cd backend/serverless
sam validate
sam build
```

---

## 12. 테스트 후 정리

테스트 후 삭제 또는 보존 정책을 확인할 항목:

- S3 artifact bucket의 `sessions/` 객체
- DynamoDB test table item
- CloudWatch Logs 보존 기간
- Transcribe job이 생성되지 않았는지 확인

현재 구조에서는 Transcribe batch job을 만들지 않으므로 Transcribe 작업 목록에 새 job이 쌓이지 않는 것이 정상입니다.

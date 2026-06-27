# 문진톡톡 MVP 로컬 구동 및 클라우드 검증 매뉴얼 (Smoke Test)

본 매뉴얼은 개발 팀원의 프로젝트 온보딩 및 해커톤 현장 시연 직전, 문진톡톡 MVP의 로컬 구동 상태와 AWS 클라우드 스테이징 환경 간의 End-to-End 연결 무결성을 점검하기 위한 표준 스모크 테스트 가이드입니다.

문진톡톡은 프론트엔드 단독으로 작동하지 않습니다. 음성 스트리밍 인식(STT), LLM 의미 구조화, Hybrid IR 증상 매칭, 원페이퍼 렌더링, 안내문 생성 로직은 반드시 AWS 서버리스 백엔드 인프라와 결합되어야 완료됩니다.

---

## 1. 검증 및 구동 모드

| 구동 모드 | 목표 인프라 | 적용 및 검증 시나리오 |
| --- | --- | --- |
| **프론트 로컬 독립 구동** | `http://localhost:5173` | UI 레이아웃 퍼블리싱, 컴포넌트 상태 제어 확인 |
| **클라우드 하이브리드 연결** | Local Frontend $\rightarrow$ AWS API Gateway | 실제 브라우저 마이크 연동, Bedrock 추론, S3 적재 무결성 검증 |
| **Amplify 완전 호스팅 구동**| `https://main.*.amplifyapp.com` | 공식 해커톤 피칭, 심사위원 시연, 대외 서비스 배포 |

---

## 2. MVP End-to-End 아키텍처 요약

```text
[React / Vite SPA] 
  ──> AWS API Gateway (HTTP API) 
        ──> AWS Lambda (Python 3.12 오케스트레이터)
              ├──> Amazon DynamoDB (경량 세션 메타데이터 저장)
              ├──> Amazon S3 (PII 비식별 아티팩트 보관소)
              ├──> Amazon Bedrock (Nova Pro/Lite 추론 + Titan 임베딩)
              └──> Amazon Transcribe Streaming (실시간 웹소켓 STT)
```

### 🛡️ 핵심 데이터 보안 준수 원칙
* **Zero-Storage 음성 통제:** 마이크 입력 오디오 스트림은 STT 텍스트 변환 즉시 소멸하며 서버 스토리지에 원본(`.wav` 등)을 남기지 않습니다.
* **상태와 원문의 격리:** DynamoDB에는 세션 진행 상태와 인덱스 키만 남기며, 발화 원문 및 추론 결과는 `privacy.py`의 정규식 마스킹을 거쳐 S3 아티팩트에 격리합니다.

---

## 3. 사전 요구 환경

**로컬 개발 환경**
* Node.js v20.19 이상 (또는 v22.12 이상) 및 npm
* Python 3.12
* AWS SAM CLI 및 AWS CLI (인증 프로필 구성 완료)

**AWS 클라우드 인프라 자산**
* 프로비저닝 완료된 DynamoDB 세션 테이블 (`MunjinSessions`)
* 산출물 적재용 S3 아티팩트 버킷
* 권한 바인딩 완료된 Lambda Execution Role 및 Bedrock 모델 액세스 승인

---

## 4. 프론트엔드 로컬 온보딩

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev -- --host 127.0.0.1 --port 5173
```
*(Windows PowerShell 실행 정책에 의해 스크립트 실행이 차단될 경우 `npm.cmd run dev -- --host 127.0.0.1 --port 5173`으로 실행하십시오.)*

* 브라우저 검증 주소: `http://127.0.0.1:5173/staff`

---

## 5. AWS 백엔드 하이브리드 바인딩

`frontend/.env.local` 파일에 배포된 백엔드 엔드포인트를 주입합니다.

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
```
환경 변수 저장 후 개발 서버를 강제 재시작합니다.

---

## 6. 백엔드 빌드 및 클라우드 배포

> ⚠️ **선행 필수 작업:** 저작권 보호로 공개 레포지토리에서 제외된 **의학 백과 런타임 데이터 3종**을 `backend/serverless/src/data/` 경로에 수동 배치해야 Hybrid IR 엔진이 구동됩니다.
> (`diseases_cleaned.json`, `symptom_index.json`, `symptom_embeddings_*.json`)

```powershell
cd backend/serverless
sam build
sam deploy --guided
```

**SAM 대화형 입력 규격 기준:**
```text
Stack Name: munjin-mvp-backend
AWS Region: ap-northeast-2
Parameter SessionsTableName: MunjinSessions
Parameter ArtifactsBucketName: <생성된_S3_버킷명>
Parameter LambdaRoleArn: <실행_Role_ARN>
Parameter CustomVocabularyName:              <-- (공백 통과 시 Enter)
Confirm changes before deploy: y
Allow SAM CLI IAM role creation: n
MunjinApiFunction has no authentication. Is this okay?: y
```

---

## 7. 현장 시연 직전 인수 검증 체크리스트 (Smoke Test)

해커톤 시연 전 아래의 5단계 흐름을 순차 검증하여 인프라 병목을 차단합니다.

### Step 01. 접수처 파트 (`/staff`)
1. 접근 코드 로그인 통과 후 신규 환자 정보(이름, 생년월일, 진료과) 입력 및 세션 생성
2. 당일 대기열 목록에 정상 등록 확인
* **`검증 체크포인트`**: DynamoDB 레코드 확인 시 `patient.full_name`, `phone`이 평문 저장되지 않고 `patient.name("김*자")` 형태의 마스킹 표기로 적재되었는가?

### Step 02. 환자 동의 파트 (태블릿 모달)
1. 생성된 문진 세션 클릭 $\rightarrow$ 개인정보 및 민감 건강정보 처리 동의 체결
* **`검증 체크포인트`**: S3 아티팩트 버킷 내 `sessions/.../consent.json` 파일이 정상 빌드되었는가?

### Step 03. 음성 문진 파트 (`/patient/:sessionId`)
1. Q1~Q4 문항 순차 실시간 발화 및 STT 전사 확인 문자열 확정 제출
* **`검증 체크포인트`**: S3 버킷 내에 음성 파일(`.wav`)이 생성되지 않았으며, `answers.redacted.json`과 `llm_trace.redacted.json`만 비식별 상태로 생성되었는가?

### Step 04. 의료진 원페이퍼 파트 (`/doctor/:sessionId`)
1. 의료진 대기열에서 '분석 완료' 확인 후 원페이퍼 진입
2. 환자 발화 인용 원문(Quote) 하이라이트 및 Hybrid IR 표준 증상 매칭 결과 대조
* **`검증 체크포인트`**: LLM의 임의 추론 확신도 점수(`score`, `confidence`)가 화면 UI에 노출되지 않고 격리되었는가?

### Step 05. 환자 안내문 발급 파트 (`/guide/:sessionId`)
1. 원페이퍼 아젠다 패널에 의사 답변 및 강조 키워드 작성 후 `안내문 생성` 트리거
2. 큰 글씨 렌더링, 음성 재생(TTS), 인쇄 레이아웃(Print 모드) 정상 작동 확인
* **`검증 체크포인트`**: 의사가 입력한 지시 강조사항을 LLM이 임의 왜곡하지 않고 원문 그대로 안내문 본문에 출력하는가?

---

## 8. 백엔드 API 모의 호출 스펙 (PowerShell)

클라이언트 단에서의 API 주입 정합성을 터미널에서 직접 검증하는 페이로드 예시입니다.

### 세션 생성 호출
```powershell
$base = "https://<api-id>.execute-api.ap-northeast-2.amazonaws.com"

$body = @{
  visit_type = "initial"
  patient = @{
    full_name = "홍길동"
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
*(주의: 본 예시는 프론트엔드가 전송하는 Raw Request입니다. 백엔드는 수신 즉시 식별자를 마스킹하고 원본 연락처를 파기한 뒤 DB에 적재합니다.)*

### 답변 일괄 제출 호출
```powershell
$answers = @{
  session_id = "<session_id>"
  visit_type = "initial"
  question_set_id = "default"
  answers = @(
    @{ question_id = "Q1"; question_type = "chief_complaint"; transcript = "어제부터 목이 칼칼하고 코가 막혀요" },
    @{ question_id = "Q2"; question_type = "onset"; transcript = "어제부터 그랬어요" },
    @{ question_id = "Q3"; question_type = "medication"; transcript = "먹는 약은 없습니다" },
    @{ question_id = "Q4"; question_type = "patient_question"; transcript = "감기약을 먹어도 되는지 궁금해요" }
  )
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Method Post -Uri "$base/process-answers" -ContentType "application/json" -Body $answers
```

---

## 9. 트러블슈팅 매뉴얼

| 발생 증상 | 핵심 원인 분석 | 조치 방안 |
| --- | --- | --- |
| **세션 생성이 먹통임** | `VITE_API_BASE_URL` 환경 변수 미주입 | `.env.local` 문자열 확인 후 빌드 서버 재시작 |
| **태블릿 마이크 비활성화**| 비보안 프로토콜(`http://`) 접근 차단 | 로컬 `127.0.0.1` 혹은 정식 `https://` 도메인 접속 확인 |
| **STT 인식 텍스트 누락** | Transcribe 웹소켓 바인딩 실패 | 네트워크 방화벽 및 `/transcribe/stream-url` 발급 확인 |
| **원페이퍼 생성 지연** | 비동기 Lambda 호출 큐 대기 중 | 3~5초 대기 후 새로고침 (정상 비동기 흐름) |
| **원페이퍼 본문이 빈 값**| 백그라운드 추론 에러 혹은 IR 인덱스 부재 | S3 `answers.redacted.json` 생성 여부 및 `src/data/` 파일 대조 |
| **S3 AccessDenied** | Lambda 실행 역할의 버킷 권한 누락 | IAM Policy 내 아티팩트 버킷 `GetObject`, `PutObject` 확인 |

---

## 10. 무결성 검증 표준 명령어

**[Frontend 빌드 검증]**
```powershell
cd frontend
npm.cmd run build
```

**[Backend 문법 검증]**
```powershell
python -m compileall backend/serverless/src
```

**[SAM 인프라 규격 검증]**
```powershell
cd backend/serverless
sam validate
sam build
```

---

## 11. 시연 종료 후 인프라 Teardown 가이드

해커톤 심사 종료 후 불필요한 클라우드 과금 및 데이터 잔류를 막기 위해 다음 자산을 확인합니다.

1. **S3 아티팩트 버킷:** 테스트 간 생성된 `sessions/` 하위 객체 전체 수동 파기 (혹은 Lifecycle 3일 규칙 동작 확인)
2. **DynamoDB 테이블:** 시연용 임시 세션 아이템 스캔 후 정리
3. **Amazon Transcribe:** 실시간 스트리밍 아키텍처 특성상 Batch Job 리스트에 작업 이력이 남지 않는 것이 정상 규격임을 최종 확인

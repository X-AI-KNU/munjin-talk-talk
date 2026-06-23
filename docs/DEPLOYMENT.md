# 문진톡톡 AWS 배포 가이드

이 문서는 문진톡톡 MVP를 AWS에 배포하는 절차를 설명합니다. 대상 독자는 배포 담당자, 팀 개발자, 평가 환경을 검토하는 사람입니다.

현재 구조는 프론트엔드와 백엔드를 분리해서 배포합니다.

```text
Frontend: AWS Amplify Hosting
Backend: AWS SAM + API Gateway + Lambda
Storage: DynamoDB minimal state + S3 redacted artifact bucket
AI: Amazon Transcribe Streaming + Amazon Bedrock + Amazon Titan Embeddings
```

---

## 1. 배포 전 확인 사항

필수 준비:

- AWS 계정과 콘솔 접근 권한
- GitHub repository 접근 권한
- AWS CLI 또는 SAM CLI 로그인
- Bedrock model access 승인
- DynamoDB table
- S3 artifact bucket
- Lambda execution role
- Amplify app

권장 region:

```text
ap-northeast-2
```

프로젝트 문서에서는 서울 리전을 기준으로 설명합니다.

---

## 2. 전체 배포 순서

```text
1. S3 artifact bucket 생성
2. DynamoDB table 생성
3. Lambda execution role 준비
4. Bedrock model access 확인
5. SAM backend 배포
6. API Gateway endpoint 확인
7. Amplify frontend 앱 연결
8. Amplify 환경 변수 VITE_API_BASE_URL 설정
9. SPA rewrite 설정
10. 최종 동작 확인
```

백엔드 보안 파라미터:

- `StaffAccessToken`: 직원이 로그인 모달에 입력하는 접근 코드. 파라미터 이름은 기존 배포 호환을 위해 유지합니다.
- `DoctorAccessToken`: 의료진이 로그인 모달에 입력하는 접근 코드. 파라미터 이름은 기존 배포 호환을 위해 유지합니다.
- `AuthSigningSecret`: 로그인 성공 후 발급되는 직원/의료진 세션 토큰의 HMAC 서명 비밀값
- `AuthTokenTtlMinutes`: 직원/의료진 세션 토큰 유효 시간. 기본값은 240분입니다.
- `CorsAllowOrigin`: 해당 백엔드를 호출할 Amplify HTTPS origin
- `S3KmsKeyId`: S3 artifact를 SSE-KMS로 암호화할 때 사용하는 KMS key id 또는 ARN. 비워두면 코드에서 SSE-S3(AES256)를 명시합니다.

접근 코드와 서명 비밀값은 GitHub, README, Amplify 환경 변수에 올리지 않습니다. 배포 담당자가 SAM/CloudFormation 파라미터 또는 Lambda 환경 변수로만 관리합니다. 프론트엔드는 접근 코드를 저장하지 않고, 백엔드가 발급한 만료 세션 토큰만 브라우저 `sessionStorage`에 보관합니다.

---

## 3. S3 artifact bucket

S3 bucket은 환자 문진 산출물을 보관합니다. 음성 원본 파일을 저장하는 bucket이 아닙니다.

저장되는 파일 예시:

```text
sessions/YYYY-MM-DD/{session_id}/
  consent.json
  answers.redacted.json
  onepaper.redacted.json
  doctor_review.redacted.json
  patient_guide.redacted.json
  llm_trace.redacted.json
```

필수 설정:

- Block Public Access 활성화
- 기본 암호화 활성화
- Lifecycle 3일 삭제 규칙 설정
- bucket policy 또는 IAM으로 Lambda role만 접근 허용

권장 설정:

- SSE-KMS
- Macie 민감정보 탐지
- CloudTrail data event 검토

주의:

- 이 bucket은 Amplify 배포 산출물 bucket이 아닙니다.
- SAM CLI가 내부적으로 쓰는 deployment bucket과도 다릅니다.
- 문진 산출물을 저장하는 별도 application artifact bucket입니다.

---

## 4. DynamoDB table

제출용 table name:

```text
MunjinSessions
```

Primary key:

```text
partition key: session_id (String)
```

권장 설정:

- On-demand capacity
- TTL 활성화
- TTL attribute: `expires_at`

DynamoDB에는 다음 값만 저장해야 합니다.

- `session_id`
- `queue_number`
- `status`
- `visit_type`
- `patient.name` 마스킹 표시명
- `patient.age`, `patient.age_band`
- `patient.gender`
- `patient.department`
- `patient.doctor`
- `risk`
- `privacy_consent` 요약
- `artifact` S3 key 정보
- `question_status`
- `onepager_ready`
- `guide_ready`

DynamoDB에 저장하면 안 되는 값:

- `patient.full_name`
- `patient.birth_date`
- `patient.phone`
- `responses`
- `question_results`
- `onepager`
- `doctor_review`
- `patient_guide`

---

## 5. Lambda execution role

Lambda role에는 다음 권한이 필요합니다.

### DynamoDB

```text
dynamodb:GetItem
dynamodb:PutItem
dynamodb:UpdateItem
dynamodb:Scan
```

대상 resource는 문진 세션 table ARN으로 제한합니다.

### S3 artifact bucket

```text
s3:GetObject
s3:PutObject
```

대상 resource는 artifact bucket의 `sessions/*` prefix로 제한하는 것을 권장합니다.

### Bedrock

```text
bedrock:InvokeModel
bedrock:InvokeModelWithResponseStream
```

사용 모델 ARN 또는 region 범위로 제한합니다.

### Transcribe

Transcribe Streaming presigned URL 발급에 필요한 권한을 부여합니다.

### CloudWatch Logs

```text
logs:CreateLogGroup
logs:CreateLogStream
logs:PutLogEvents
```

운영 환경에서는 CloudWatch Logs 보존 기간을 짧게 설정하고, 원문 발화와 LLM payload를 로그에 남기지 않는 원칙을 지켜야 합니다.

---

## 6. Bedrock model access

AWS Console에서 Bedrock model access를 확인합니다.

필요 모델:

- Amazon Nova Pro
- Amazon Nova Lite
- Amazon Titan Text Embeddings

환경 변수에서 model id를 바꿀 수 있지만, 코드 기본값은 현재 MVP 기준으로 설정되어 있습니다.

---

## 7. SAM backend 배포

공개 저장소에는 저작권/이용 범위 검토가 필요한 원천 의료 백과 본문과 파생 인덱스·embedding cache가 포함되지 않습니다. `sam build` 전에 팀 내부 비공개 데이터 저장소에서 아래 파일을 `backend/serverless/src/data/`에 배치합니다.

- `diseases_cleaned.json`
- `symptom_index.json`
- `symptom_embeddings_amazon.titan-embed-text-v2_0_512.json`

```powershell
cd C:\Users\CGB\munjin-talk-talk-mvp\backend\serverless
sam build
sam deploy --guided
```

입력 예시:

```text
Stack Name: munjin-mvp-backend
AWS Region: ap-northeast-2
Parameter SessionsTableName: MunjinSessions
Parameter ArtifactsBucketName: <s3-artifact-bucket-name>
Parameter LambdaRoleArn: <lambda-role-arn>
Parameter CustomVocabularyName:
Parameter CorsAllowOrigin: https://<amplify-branch-domain>
Parameter StaffAccessToken: <staff-access-code>
Parameter DoctorAccessToken: <doctor-access-code>
Parameter AuthSigningSecret: <random-signing-secret>
Parameter AuthTokenTtlMinutes: 240
Parameter S3KmsKeyId: <empty-or-kms-key-id>
Confirm changes before deploy: y
Allow SAM CLI IAM role creation: n
MunjinApiFunction has no authentication. Is this okay?: y
```

배포 완료 후 output:

```text
ApiEndpoint = https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
```

이 값을 Amplify 환경 변수 `VITE_API_BASE_URL`에 넣습니다.

`CorsAllowOrigin`은 해당 백엔드를 호출할 프론트엔드 HTTPS origin입니다. 제출용 운영은 Amplify `main` 브랜치 기본 도메인을 넣습니다. 개발 중에는 `*`로 둘 수 있지만, 공개 시연 또는 제출용 환경에서는 실제 Amplify domain으로 좁히는 것을 권장합니다.

주의:

- `samconfig.toml`에는 계정 ID, role ARN, bucket 이름이 들어갈 수 있으므로 Git에 올리지 않습니다.
- `.aws-sam/`도 build 산출물이므로 Git에 올리지 않습니다.

---

## 8. Amplify frontend 배포

Amplify Console에서 앱을 생성합니다.

### Repository 선택

```text
Repository: CHOIGIBUM/munjin-talk-talk-mvp
Branch: main
```

### Monorepo 설정

```text
Monorepo app root: frontend
```

### Build 설정

```text
Build command: npm run build
Build output directory: dist
```

루트에 `amplify.yml`이 있으면 자동으로 해당 설정을 사용할 수 있습니다.

### 환경 변수

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
AMPLIFY_MONOREPO_APP_ROOT=frontend
AMPLIFY_DIFF_DEPLOY=false
```

제출용 Amplify 앱은 `main` 브랜치 하나만 운영합니다. 기능 개발은 Git 브랜치에서 진행하되, Amplify 배포와 AWS 리소스는 `main` 기준으로 단일화해 DynamoDB/S3/API endpoint 혼선을 줄입니다.

직원/의료진 접근 코드와 `AuthSigningSecret`은 Amplify 환경 변수로 넣지 않습니다. 프론트 빌드 산출물에 secret이 포함되지 않도록, 화면에서 처음 내부 API 호출 시 로그인 모달로 접근 코드를 입력받고 `/auth/login`에서 짧은 시간 유효한 세션 토큰을 발급받습니다. 이후 API 요청은 `Authorization: Bearer <token>`만 사용합니다.

---

## 9. SPA rewrite 설정

React Router를 사용하므로 직접 URL 접근 시 404가 나지 않게 rewrite를 설정합니다.

Amplify Console:

```text
Hosting
  -> Rewrites and redirects
```

설정:

```json
[
  {
    "source": "/<*>",
    "status": "404-200",
    "target": "/index.html"
  }
]
```

---

## 10. 배포 후 확인

### 프론트 접속

```text
https://<branch>.<amplify-app-id>.amplifyapp.com/staff
```

확인:

- 직원 접수 화면이 열리는가
- 상단 메뉴가 표시되는가
- 세션이 없을 때 환자 태블릿, 원페이퍼, 안내문 메뉴가 비활성화되는가

### 세션 생성

1. 환자 정보를 입력합니다.
2. 문진 세션을 생성합니다.
3. 오늘 접수 목록에 표시되는지 확인합니다.

AWS 확인:

- DynamoDB item 생성
- 실명, 생년월일, 연락처 원문 미저장
- artifact key 생성

### 환자 문진

1. 환자 태블릿으로 이동합니다.
2. 서비스 이용 동의 모달을 확인합니다.
3. 마이크 권한을 허용합니다.
4. Q1 답변을 말합니다.
5. STT 결과 확인 후 다음으로 이동합니다.

AWS 확인:

- S3 `consent.json`
- S3 `answers.redacted.json`
- S3 `llm_trace.redacted.json`
- S3 `onepaper.redacted.json`
- DynamoDB에는 `responses`, `onepager` 직접 저장 없음

### 원페이퍼와 안내문

1. 원페이퍼에서 증상, quote, 문진 맥락을 확인합니다.
2. 의사 답변을 입력합니다.
3. 환자 안내 강조사항을 입력합니다.
4. 환자 안내문 생성 버튼을 클릭합니다.
5. 안내문 화면에서 결과를 확인합니다.

AWS 확인:

- S3 `doctor_review.redacted.json`
- S3 `patient_guide.redacted.json`
- DynamoDB `guide_ready = true`

---

## 11. 운영 보안 체크리스트

| 항목 | 상태 확인 위치 |
| --- | --- |
| S3 Block Public Access | S3 bucket permissions |
| S3 Lifecycle 3일 삭제 | S3 lifecycle rules |
| S3 기본 암호화 또는 KMS | S3 default encryption |
| Macie 민감정보 탐지 | Amazon Macie |
| DynamoDB TTL | DynamoDB table settings |
| Lambda role 최소 권한 | IAM role policy |
| CloudWatch Logs 보존 기간 | CloudWatch log group retention |
| API Gateway throttling | API Gateway stage settings |
| Amplify 환경 변수 | Amplify hosting environment variables |
| Bedrock model access | Bedrock model access |
| 직원/의료진 접근 코드 | CloudFormation parameter 또는 Lambda env |
| CORS origin 제한 | SAM `CorsAllowOrigin`, Lambda `ALLOWED_ORIGINS` |

---

## 12. 비용 주의

MVP 시연과 검증에서 큰 비용을 만들 수 있는 항목:

- Bedrock LLM 호출
- Titan embedding 호출
- Transcribe Streaming
- CloudWatch Logs 누적
- S3 object 누적
- DynamoDB scan 반복

비용을 줄이는 방법:

- S3 Lifecycle 3일 삭제
- CloudWatch Logs 보존 기간 단축
- 시연 후 생성된 세션 데이터 삭제 또는 보존 기간 확인
- 불필요한 반복 문진 실행 제한
- Bedrock 호출 실패 retry 횟수 제한 유지

---

## 13. 배포 문제 해결

| 문제 | 원인 | 해결 |
| --- | --- | --- |
| Amplify build 실패 | `package-lock.json` 불일치 | 로컬에서 `npm install` 후 lockfile 갱신 |
| Amplify에서 API 호출 실패 | `VITE_API_BASE_URL` 누락 | 환경 변수 저장 후 redeploy |
| 라우트 직접 접속 404 | SPA rewrite 없음 | `/<*> -> /index.html` 404-200 추가 |
| SAM deploy parameter 오류 | 빈 문자열 parameter 형식 문제 | `CustomVocabularyName`은 guided 입력에서 Enter |
| S3 AccessDenied | Lambda role 권한 부족 | artifact bucket ARN에 `GetObject`, `PutObject` 추가 |
| Bedrock AccessDenied | 모델 access 미승인 | Bedrock console에서 모델 사용 승인 |
| Transcribe 안 됨 | HTTPS/마이크/URL 문제 | Amplify HTTPS URL, browser permission, API 응답 확인 |

---

## 14. GitHub 반영 기준

브랜치 운영:

- `main`: 제출·시연용 안정 배포 브랜치
- 기능 검증 브랜치: 로컬 또는 GitHub 작업용으로만 사용하고, Amplify와 AWS 리소스는 별도로 늘리지 않는 것을 기본 원칙으로 합니다.

커밋 전 확인:

```powershell
git status --short
git diff --check
npm.cmd run build
python -m compileall backend/serverless/src
```

Git에 올리지 않을 것:

- `backend/serverless/samconfig.toml`
- `backend/serverless/.aws-sam/`
- `frontend/dist/`
- `frontend/node_modules/`
- `.env`
- `.env.local`
- 실제 환자 데이터
- 실제 AWS access key

---

## 15. 관련 문서

- [../README.md](../README.md)
- [../backend/serverless/README.md](../backend/serverless/README.md)
- [DATA_SCHEMA.md](DATA_SCHEMA.md)
- [SECURITY_DATA_INVENTORY.md](SECURITY_DATA_INVENTORY.md)
- [LANGGRAPH_PIPELINE.md](LANGGRAPH_PIPELINE.md)

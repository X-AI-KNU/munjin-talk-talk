# 문진톡톡 AWS 배포 가이드

이 문서는 문진톡톡 MVP를 AWS에 배포하는 절차를 설명합니다.

프론트엔드는 AWS Amplify Hosting을 사용하고, 백엔드는 AWS SAM으로 API Gateway + Lambda를 배포합니다.

---

## 전체 배포 구조

```text
GitHub repository
  -> Amplify Hosting
  -> React/Vite frontend
  -> API Gateway HTTP API
  -> Lambda Python backend
  -> DynamoDB
  -> Amazon Transcribe Streaming
  -> Amazon Bedrock
```

---

## 배포 전에 결정할 것

| 항목 | 예시 | 설명 |
| --- | --- | --- |
| AWS Region | `ap-northeast-2` | 서울 리전 |
| 프론트 브랜치 | `test` 또는 `main` | Amplify가 자동 배포할 브랜치 |
| 백엔드 stack name | `munjin-mvp-backend-test` | CloudFormation stack 이름 |
| DynamoDB table | `MunjinSessionsTest` | 세션 저장 테이블 |
| Lambda role | `munjin-lambda-role` | Lambda 실행 role |
| Artifact bucket | `munjin-mvp-test-artifacts-...` | SAM/임시 artifact bucket |

---

## 1. AWS 리소스 준비

### DynamoDB

콘솔 경로:

```text
DynamoDB
  -> Tables
  -> Create table
```

설정:

```text
Table name: MunjinSessionsTest
Partition key: session_id
Partition key type: String
Billing mode: On-demand
```

운영 전 권장:

- TTL 필드 추가 검토
- 테스트 데이터 삭제 정책
- 실제 환자 데이터 보존 기간 정의

### S3 artifact bucket

콘솔 경로:

```text
S3
  -> Create bucket
```

용도:

- SAM 배포 artifact
- CloudFormation 임시 산출물

중요:

```text
이 bucket은 환자 음성 저장소가 아닙니다.
현재 MVP는 환자 음성을 S3에 업로드하지 않습니다.
```

수명 주기 규칙:

- 테스트 artifact는 3일 또는 짧은 기간 후 삭제 권장

### IAM Role

Lambda execution role에 필요한 권한:

- CloudWatch Logs
- DynamoDB read/write
- Bedrock `InvokeModel`
- Transcribe Streaming
- S3 artifact bucket 접근

개발 편의상 넓은 권한으로 시작했더라도, 공개 테스트 전에는 resource ARN을 좁히는 것이 좋습니다.

### Bedrock model access

콘솔 경로:

```text
Amazon Bedrock
  -> Model access
```

확인할 모델:

```text
apac.amazon.nova-pro-v1:0
apac.amazon.nova-lite-v1:0
amazon.titan-embed-text-v2:0
```

---

## 2. 백엔드 배포

PowerShell:

```powershell
cd C:\Users\CGB\munjin-talk-talk-mvp\backend\serverless
sam build
sam deploy --guided
```

입력 예시:

```text
Stack Name: munjin-mvp-backend-test
AWS Region: ap-northeast-2
Parameter SessionsTableName: MunjinSessionsTest
Parameter ArtifactsBucketName: <artifact-bucket-name>
Parameter LambdaRoleArn: arn:aws:iam::<account-id>:role/<lambda-role-name>
Parameter CustomVocabularyName:
Confirm changes before deploy: y
Allow SAM CLI IAM role creation: n
Capabilities: CAPABILITY_IAM
MunjinApiFunction has no authentication. Is this okay?: y
```

배포 완료 후 output:

```text
ApiEndpoint
https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
```

이 값을 프론트 환경 변수에 넣어야 합니다.

---

## 3. Amplify 앱 생성

콘솔 경로:

```text
AWS Amplify
  -> Create new app
  -> Host web app
  -> GitHub 선택
```

GitHub 권한:

- 개인 repo이면 본인 GitHub 계정 repo 선택
- 팀 repo이면 GitHub App 권한이 repo에 부여되어 있어야 함
- repo가 목록에 안 보이면 GitHub 권한 업데이트 필요

Repository/branch:

```text
Repository: CHOIGIBUM/munjin-talk-talk-mvp 또는 팀 repo
Branch: test 또는 main
```

Monorepo 설정:

```text
My app is a monorepo: checked
Monorepo root directory: frontend
```

Build settings:

```text
Frontend build command: npm run build
Build output directory: dist
```

현재 저장소에는 root의 `amplify.yml`이 있습니다.

```yaml
version: 1
applications:
  - appRoot: frontend
    frontend:
      phases:
        preBuild:
          commands:
            - nvm install 22
            - nvm use 22
            - npm install
        build:
          commands:
            - npm run build
      artifacts:
        baseDirectory: dist
        files:
          - '**/*'
      cache:
        paths:
          - node_modules/**/*
```

---

## 4. Amplify 환경 변수 설정

콘솔 경로:

```text
Amplify
  -> App 선택
  -> Hosting
  -> Environment variables
```

설정:

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
AMPLIFY_MONOREPO_APP_ROOT=frontend
AMPLIFY_DIFF_DEPLOY=false
```

목업 모드를 명시적으로 끄고 싶으면:

```text
VITE_ENABLE_MOCKS=false
```

주의:

- Amplify 환경 변수는 빌드 시점에 Vite bundle에 들어갑니다.
- 값을 바꾼 뒤에는 반드시 재배포해야 합니다.
- branch별 환경 변수를 따로 설정할 수 있으면 test/main을 분리하는 것이 좋습니다.

---

## 5. SPA rewrite 설정

React single-page app은 직접 URL 접속 시 `/index.html`로 rewrite되어야 합니다.

콘솔 경로:

```text
Amplify
  -> Hosting
  -> Rewrites and redirects
```

권장 규칙:

```json
[
  {
    "source": "/<*>",
    "status": "404-200",
    "target": "/index.html"
  }
]
```

이 규칙이 없으면 아래 경로를 새로고침할 때 404가 날 수 있습니다.

```text
/staff
/patient/{sessionId}
/doctor/queue
/doctor/{sessionId}
/guide/{sessionId}
```

---

## 6. Amplify 배포 확인

배포 성공 후 Amplify domain이 생성됩니다.

예:

```text
https://test.<app-id>.amplifyapp.com
```

확인 순서:

1. `/staff` 접속
2. 세션 생성
3. `/patient/{sessionId}` 이동
4. 마이크 권한 허용
5. 음성 인식 확인
6. `/doctor/{sessionId}` 원페이퍼 확인
7. `/guide/{sessionId}` 안내문 확인

---

## 7. 백엔드 스모크 테스트

API endpoint만 먼저 확인하고 싶을 때:

```powershell
@'
const API = 'https://<api-id>.execute-api.ap-northeast-2.amazonaws.com';
const res = await fetch(`${API}/doctor/queue`);
console.log(res.status);
console.log(await res.text());
'@ | node --input-type=module -
```

문항 처리까지 확인하려면 [MVP 실행 가이드](MVP_SETUP.md)의 스모크 테스트를 사용합니다.

---

## 8. CloudWatch 로그 확인

콘솔 경로:

```text
CloudWatch
  -> Log groups
  -> /aws/lambda/<stack-name>-MunjinApiFunction-...
```

확인할 오류:

| 오류 | 가능 원인 |
| --- | --- |
| `AccessDeniedException` | IAM role 권한 부족 |
| `ResourceNotFoundException` | DynamoDB table 이름 불일치 |
| Bedrock model access error | Bedrock 모델 권한 미활성화 |
| Transcribe stream error | Transcribe 권한 또는 WebSocket URL 문제 |
| `semantic_extraction_failed` | LLM output schema/quote 검증 실패 |
| Lambda timeout | Bedrock 응답 지연 또는 cold start |

---

## 9. 비용 관리

테스트 중 비용이 발생할 수 있는 서비스:

- Amplify Hosting
- API Gateway
- Lambda
- DynamoDB
- CloudWatch Logs
- Amazon Transcribe Streaming
- Amazon Bedrock Nova
- Amazon Titan Embeddings
- S3 artifact storage

비용 줄이는 방법:

- 테스트 후 DynamoDB item 삭제
- CloudWatch Logs retention 3일 또는 7일 설정
- S3 artifact lifecycle 3일 설정
- 불필요한 Amplify preview branch 삭제
- 대량 음성 테스트 자제
- Bedrock 호출 로그와 횟수 확인

---

## 10. 공개 테스트 전 필수 보완

현재 MVP는 기능 검증용이며, 인증이 완성되어 있지 않습니다.

공개 테스트 전 필요한 것:

- 직원/의사 화면 인증
- API Gateway authorizer 또는 Cognito
- 역할별 접근 제어
- 환자 개인정보 동의 화면
- DynamoDB TTL/삭제 정책
- CloudWatch Logs 보존 기간
- 실제 환자 데이터 마스킹 정책
- HTTPS 배포 확인
- WAF 또는 접근 제한
- 병원 내부망 또는 제한된 테스트 URL 정책

---

## 관련 문서

- [MVP 실행 가이드](MVP_SETUP.md)
- [서버리스 백엔드 README](../backend/serverless/README.md)
- [프론트엔드 README](../frontend/README.md)
- [프로젝트 구조](PROJECT_STRUCTURE.md)

# MVP Setup

이 문서는 문진톡톡 MVP를 로컬에서 확인하고 AWS 배포로 연결하기 위한 운영 메모입니다.

## Prerequisites

- Node.js `20.19+` or `22.12+`
- AWS CLI
- AWS SAM CLI
- AWS account with access to:
  - API Gateway
  - Lambda
  - DynamoDB
  - S3
  - Amazon Transcribe
  - Amazon Bedrock

## Environment

Frontend environment file:

```powershell
cd frontend
Copy-Item .env.example .env.local
```

`frontend/.env.local`:

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
```

Do not commit `.env.local`.

## Local Frontend

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

If `VITE_API_BASE_URL` is empty, the frontend falls back to mock data for UI-only review.

## Backend Deploy

```powershell
cd backend/serverless
sam build
sam deploy --guided
```

Required SAM parameters:

```text
SessionsTableName
ArtifactsBucketName
LambdaRoleArn
CustomVocabularyName
```

The deployed API endpoint is used as `VITE_API_BASE_URL`.

## Frontend Build

```powershell
cd frontend
npm install
npm run build
```

Deploy the contents of `frontend/dist` to Amplify Hosting.

For GitHub-connected Amplify deployments, set:

```text
App root: frontend
Build output: dist
Environment variable: VITE_API_BASE_URL
```

## Smoke Test

1. Open `/staff` and create a session.
2. Open the generated `/patient/{sessionId}` route.
3. Complete the voice questionnaire.
4. Open `/doctor/queue`.
5. Open `/doctor/{sessionId}` and review the onepaper.
6. Submit doctor responses and optional patient instructions.
7. Open `/guide/{sessionId}` and check the patient guide.

## Release Checklist

- Amplify URL is HTTPS.
- S3 CORS includes the Amplify domain.
- Bedrock model access is enabled in the target region.
- Staff and doctor routes are protected before public testing.
- Real patient information is not entered during open demos.

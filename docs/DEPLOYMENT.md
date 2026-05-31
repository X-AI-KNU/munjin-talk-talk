# Deployment

Deployment guide for the 문진톡톡 MVP.

## Backend

Deploy from `backend/serverless`.

```powershell
cd backend/serverless
sam build
sam deploy --guided
```

Required parameters:

```text
SessionsTableName
ArtifactsBucketName
LambdaRoleArn
CustomVocabularyName
```

After deployment, copy the `ApiEndpoint` output.

## Frontend Environment

Create `frontend/.env.local` for local builds:

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
```

For Amplify GitHub-connected deployment, set the same value in Amplify environment variables.

## Amplify From GitHub

Use this when the repository is connected to Amplify.

```text
Repository: BANG-JEONGHO/munjin-talk-talk
Branch: main
App root: frontend
Build output: dist
```

Build settings:

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
            - npm ci
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

Environment variable:

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
```

## Amplify Manual Deploy

Use this when GitHub App authorization is not available.

```powershell
cd frontend
npm install
npm run build
```

Zip the contents of `frontend/dist`, not the folder itself. The zip root should contain:

```text
index.html
assets/
```

Upload the zip through Amplify `Deploy without Git`.

## SPA Rewrite

Add a rewrite rule so direct routes such as `/doctor/queue` work after refresh.

```text
Source: </^[^.]+$/>
Target: /index.html
Type: 200 (Rewrite)
```

## S3 CORS

Add the final Amplify HTTPS domain to the S3 artifact bucket CORS.

```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["PUT", "GET"],
    "AllowedOrigins": [
      "http://localhost:5173",
      "http://127.0.0.1:5173",
      "https://<amplify-domain>.amplifyapp.com"
    ],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3000
  }
]
```

## Smoke Test

1. `/staff`: create a session.
2. `/patient/{sessionId}`: complete voice intake.
3. `/doctor/queue`: verify queue status.
4. `/doctor/{sessionId}`: review symptoms, quotes, context, questions, and checklist items.
5. Submit doctor responses and patient instructions.
6. `/guide/{sessionId}`: verify patient-facing guide and print view.

## Before Public Testing

- Protect staff and doctor routes.
- Confirm Bedrock model access in `ap-northeast-2`.
- Confirm S3 CORS includes the deployed frontend URL.
- Check Lambda logs during a full questionnaire run.
- Do not enter real patient information without privacy and consent handling.

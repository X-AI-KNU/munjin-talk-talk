# Serverless Backend

AWS SAM backend for the 문진톡톡 MVP.

## Endpoints

```text
POST /sessions
POST /upload-url
GET  /transcribe-result
POST /extract
POST /match
POST /validate
GET  /doctor/queue
GET  /onepager/{session_id}
POST /doctor-response
GET  /guide/{session_id}
```

## Runtime

- Python 3.12 Lambda
- API Gateway HTTP API
- DynamoDB session table
- S3 artifact bucket for audio and transcript files
- Amazon Transcribe
- Amazon Bedrock Nova Pro/Lite
- Amazon Titan Text Embeddings for symptom IR

## Required AWS Resources

Create or prepare these before `sam deploy`:

- DynamoDB table with partition key `session_id` as string
- S3 bucket for audio/transcript artifacts
- Lambda execution role with:
  - CloudWatch Logs
  - DynamoDB read/write
  - S3 read/write
  - Transcribe start/get
  - Bedrock invoke

## Deploy

```powershell
sam build
sam deploy --guided
```

SAM parameters:

```text
Stack Name: munjin-mvp-backend
AWS Region: ap-northeast-2
SessionsTableName: <DynamoDB table name>
ArtifactsBucketName: <S3 bucket name>
LambdaRoleArn: <Lambda execution role ARN>
CustomVocabularyName: <optional>
Allow SAM CLI IAM role creation: N
```

Copy the CloudFormation output `ApiEndpoint` into the frontend environment:

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
```

## S3 CORS

The browser uploads audio directly to S3 through presigned URLs. Add local and deployed frontend origins to the artifact bucket CORS.

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

Apply with AWS CLI:

```powershell
aws s3api put-bucket-cors `
  --bucket <S3 bucket name> `
  --cors-configuration file://s3-cors.json `
  --region ap-northeast-2
```

## Model Routing

Default Bedrock model routing:

- Q1 symptom/new-vs-follow-up extraction: `apac.amazon.nova-pro-v1:0`
- Q2/Q3/Q4 structured extraction: `apac.amazon.nova-lite-v1:0`
- Symptom matching: BM25 over `diseases_cleaned.json` + `symptom_index.json`, reranked with `amazon.titan-embed-text-v2:0`
- Onepaper review: `apac.amazon.nova-pro-v1:0`
- Patient guide rewriting: `apac.amazon.nova-lite-v1:0`

## Symptom IR Data

Runtime symptom search uses only these source files under `src/data/`:

- `diseases_cleaned.json`
- `symptom_index.json`

At cold-start, Lambda builds concise symptom search documents from those two files by deterministic rules. The packaged `symptom_embeddings_*.json` file is a numeric Titan vector index for those generated documents, so `/match` can run full hybrid retrieval without waiting for 87 document embeddings on the first request. No LLM-written `symptom_retrieval_dataset.json` is required.

Production-like testing should use:

```text
USE_BEDROCK_LLM=true
ALLOW_RULE_FALLBACK=false
```

## Notes

- Staff and doctor routes are not protected by this backend yet.
- Do not use real patient data before access control and retention policies are defined.

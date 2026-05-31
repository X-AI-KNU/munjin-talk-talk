# Project Structure

```text
munjin-talk-talk/
├── backend/
│   └── serverless/
│       ├── src/
│       │   ├── common.py
│       │   └── handler.py
│       ├── template.yaml
│       ├── s3-cors.json
│       └── README.md
├── frontend/
│   ├── src/
│   │   ├── assets/
│   │   ├── components/
│   │   │   ├── doctor/
│   │   │   ├── patient/
│   │   │   ├── staff/
│   │   │   └── tablet/
│   │   ├── config/
│   │   ├── hooks/
│   │   ├── services/
│   │   └── styles/
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── docs/
│   ├── DEPLOYMENT.md
│   ├── MVP_SETUP.md
│   └── PROJECT_STRUCTURE.md
└── README.md
```

## Responsibilities

`frontend/`

- Staff reception
- Patient tablet intake
- Doctor queue
- Doctor onepaper
- Patient guide

`backend/serverless/`

- Session creation and queue numbering
- S3 upload URL generation
- Transcribe polling
- Bedrock extraction, matching, validation, and guide generation
- DynamoDB session persistence

`docs/`

- Setup notes
- Deployment instructions
- Repository structure

## Excluded Artifacts

The deployment repository intentionally excludes:

- local IR experiments
- persona/evaluation datasets
- source crawling data
- embedding cache
- generated outputs
- `node_modules`
- `dist`

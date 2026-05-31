# 문진톡톡

고령 환자가 태블릿에서 음성으로 문진을 남기면, 의료진이 진료 전에 확인할 수 있는 원페이퍼와 환자 안내문으로 정리하는 문진 MVP입니다.

문진톡톡은 진단이나 처방을 대신하지 않습니다. 환자의 발화, 증상 단서, 진료 질문을 의료진이 빠르게 확인하도록 정리하는 보조 도구입니다.

## 주요 기능

- 직원이 환자를 확인하고 문진 세션을 생성합니다.
- 환자는 태블릿에서 초진/재진 흐름에 맞춰 음성으로 답변합니다.
- 음성은 Amazon Transcribe로 전사되고, Bedrock 기반 파이프라인에서 증상과 질문으로 구조화됩니다.
- 의료진은 원페이퍼에서 증상, 원문 근거, 문진 맥락, 확인 항목을 검토합니다.
- 의료진 답변과 강조사항을 바탕으로 환자 안내문을 생성합니다.

## MVP 범위

현재 저장소는 실제 시연과 배포 테스트를 위한 MVP 코드만 포함합니다.

구현 완료:

- 직원 접수 화면
- 환자 태블릿 음성 문진
- 위험 표현 감지 시 직원 호출
- 직원 대리 입력
- 의사 대기열
- 원페이퍼
- 환자 안내문/출력 화면
- AWS 서버리스 백엔드

이번 MVP에서 제외한 범위:

- EMR 연동
- 로그인/역할별 권한 분리
- 보호자 공유 URL
- 운영 모니터링 대시보드
- 실제 환자 개인정보 기반 운영

## 아키텍처

```text
frontend/
  React + Vite
  staff / patient tablet / doctor / guide screens

backend/serverless/
  API Gateway
  Lambda Python 3.12
  DynamoDB
  S3 presigned upload
  Amazon Transcribe
  Amazon Bedrock Nova Pro/Lite
```

주요 흐름:

```text
Staff reception
  -> Patient tablet voice intake
  -> Transcribe
  -> Bedrock extraction / matching / validation
  -> Doctor onepaper
  -> Patient guide
```

## 저장소 구조

```text
munjin-talk-talk/
├── frontend/             # React + Vite web app
├── backend/
│   └── serverless/       # AWS SAM backend
├── docs/                 # deployment and structure notes
├── .gitignore
└── README.md
```

로컬 IR 데이터셋, persona 테스트 데이터, 평가 산출물, embedding cache, build output, `node_modules`는 저장소에 포함하지 않습니다.

## 로컬 실행

Node.js `20.19+` 또는 `22.12+`가 필요합니다.

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
```

배포된 API endpoint를 설정합니다.

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
```

개발 서버를 실행합니다.

```powershell
npm run dev -- --host 127.0.0.1 --port 5173
```

주요 경로:

```text
/staff                 staff reception
/patient/{sessionId}   patient tablet
/doctor/queue          doctor queue
/doctor/{sessionId}    doctor onepaper
/guide/{sessionId}     patient guide
```

## 배포

Backend:

```powershell
cd backend/serverless
sam build
sam deploy --guided
```

Frontend:

```powershell
cd frontend
npm install
npm run build
```

`frontend/dist`를 AWS Amplify Hosting에 배포합니다. 태블릿 마이크 권한 때문에 배포 URL은 HTTPS여야 합니다.

상세 문서:

- [MVP setup](docs/MVP_SETUP.md)
- [Deployment guide](docs/DEPLOYMENT.md)
- [Project structure](docs/PROJECT_STRUCTURE.md)
- [Frontend README](frontend/README.md)
- [Backend README](backend/serverless/README.md)

## 안전 및 보안

- 이 MVP는 의료진 검토 없이 진단이나 처방 판단에 사용하면 안 됩니다.
- 외부 공개 테스트 전에는 직원/의사 화면에 인증 또는 네트워크 접근 제한을 추가해야 합니다.
- 개인정보 처리, 동의, 보관, 접근 권한 정책이 정해지기 전에는 실제 환자 정보를 입력하지 않습니다.

## 팀

DLC

- 최기범
- 김원재
- 방정호
- 서지민
- 박나현

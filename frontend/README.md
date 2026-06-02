# 문진톡톡 프론트엔드

이 폴더는 문진톡톡 MVP의 웹 화면을 담당합니다.

프론트엔드는 React + Vite로 만들어졌고, AWS Amplify Hosting에 배포하는 것을 기준으로 구성되어 있습니다. 하나의 웹앱 안에서 접수처, 환자 태블릿, 의사 대기열, 의사용 원페이퍼, 환자 안내문 화면을 모두 제공합니다.

---

## 프론트엔드가 하는 일

프론트엔드는 의료 AI 판단을 직접 하지 않습니다. 화면 상태를 관리하고, 환자 음성을 실시간 STT로 변환한 뒤, 백엔드 API가 만든 JSON을 사용자가 읽기 쉬운 화면으로 보여주는 역할을 합니다.

| 화면 | URL | 사용자 | 역할 |
| --- | --- | --- | --- |
| 직원 접수 | `/staff` | 접수처 직원 | 환자 기본 정보 입력, 문진 세션 생성, 오늘 접수 목록 확인 |
| 환자 태블릿 | `/patient/:sessionId` | 환자 | 초진/재진 문진, 음성 입력, 발화 확인, 직원 도움 요청 |
| 의사 대기열 | `/doctor/queue` | 의료진 | 문진 완료 또는 우선 확인 환자 목록 확인 |
| 원페이퍼 | `/doctor/:sessionId` | 의료진 | 증상, 원문 quote, 문진 맥락, 환자 질문, 체크리스트 확인 |
| 안내문 출력 | `/guide/:sessionId` | 환자/직원 | 의사가 작성한 답변과 강조사항을 출력 또는 공유 |

아무 세션도 없을 때는 상단 메뉴의 환자 태블릿, 원페이퍼, 안내문 메뉴가 비활성화됩니다. 접수처에서 세션을 만든 뒤부터 해당 세션으로 이동할 수 있습니다.

---

## 실행 환경

필수 도구:

- Node.js 20.19 이상 또는 22.12 이상
- npm
- HTTPS 배포 환경 또는 localhost

마이크 접근은 브라우저 정책상 HTTPS 또는 localhost에서만 안정적으로 동작합니다.

---

## 로컬 실행

```powershell
cd C:\Users\CGB\munjin-talk-talk-mvp\frontend
npm install
Copy-Item .env.example .env.local
npm run dev -- --host 127.0.0.1 --port 5173
```

브라우저:

```text
http://127.0.0.1:5173/staff
```

---

## 환경 변수

`.env.example`:

```text
VITE_API_BASE_URL=
VITE_ENABLE_MOCKS=false
```

### 실제 AWS 백엔드 연결

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
VITE_ENABLE_MOCKS=false
```

이 상태에서는 모든 세션, 문진 처리, 원페이퍼, 안내문 조회가 API Gateway + Lambda 백엔드로 연결됩니다.

### UI 목업 모드

```text
VITE_API_BASE_URL=
VITE_ENABLE_MOCKS=true
```

이 상태에서는 `services/demoSessions.js`와 `services/api/mockResponses.js`를 사용합니다. AWS 없이 화면 레이아웃만 확인할 때 사용합니다. 실제 MVP 검증에서는 목업 모드를 사용하지 않는 것이 좋습니다.

---

## 주요 폴더 구조

```text
frontend/
├── index.html
├── package.json
├── vite.config.js
├── .env.example
└── src/
    ├── App.jsx
    ├── main.jsx
    ├── components/
    │   ├── staff/
    │   ├── patient/
    │   ├── doctor/
    │   └── tablet/
    ├── hooks/
    ├── services/
    │   └── api/
    ├── config/
    ├── assets/
    └── styles/
```

---

## 화면별 코드 설명

### `src/App.jsx`

앱의 최상위 라우터입니다.

담당하는 일:

- `/staff`, `/patient/:sessionId`, `/doctor/queue`, `/doctor/:sessionId`, `/guide/:sessionId` 라우팅
- 상단 메뉴 활성화/비활성화
- 세션 목록을 주기적으로 가져와 현재 이동 가능한 세션 링크 계산
- 목업 모드에서만 데모 환자 화면 제공

### `components/staff/`

접수처 화면입니다.

| 파일 | 역할 |
| --- | --- |
| `ReceptionView.jsx` | 접수처 화면 controller. 세션 생성, 목록 갱신, 수동 입력 패널 상태 관리 |
| `ReceptionForm.jsx` | 이름, 생년월일, 성별, 연락처, 초진/재진 입력 |
| `ReceptionSessionList.jsx` | 오늘 접수 목록, 태블릿/원페이퍼/안내문 이동 버튼 |
| `ReceptionManualInput.jsx` | 직원이 환자 답변을 직접 입력하는 화면 |
| `receptionUtils.js` | 연락처 formatting, 환자 표시용 helper |

직원이 세션을 만들면 백엔드 `POST /sessions`를 호출합니다.

### `components/patient/`

환자 태블릿 문진 화면입니다.

| 파일 | 역할 |
| --- | --- |
| `PatientKioskView.jsx` | URL의 `sessionId`를 읽어 실제 환자 세션을 불러오는 wrapper |
| `PatientFlow.jsx` | 환자 문진 상태 머신. 질문 진행, 답변 확인, 안전 분기, 완료 처리 |
| `VoiceScreen.jsx` | 현재 질문과 마이크 UI, 실시간 인식 문구 표시 |
| `ConfirmTranscriptScreen.jsx` | 환자가 인식된 텍스트를 확인하고 다음 단계로 넘기는 화면 |
| `SafetyAlertScreen.jsx` | 객혈 등 위험 표현이 감지된 경우 직원 도움/중단 처리 |
| `StaffCallScreen.jsx` | 직원 호출 후 안심 문구와 돌아가기 버튼 표시 |
| `DoneScreen.jsx` | 문진 완료 후 대기 안내 |
| `VisitTypeScreen.jsx` | 초진/재진 선택 화면 |

환자 흐름:

```text
세션 로드
  -> 초진/재진 확인
  -> 질문 화면
  -> Transcribe Streaming 실시간 음성 인식
  -> 인식 문구 확인 화면
  -> 백엔드 /process-answer 전송
  -> 다음 질문 또는 완료
```

### `components/doctor/`

의사 대기열과 원페이퍼 화면입니다.

| 파일 | 역할 |
| --- | --- |
| `DoctorQueueView.jsx` | 진료 대기 목록 |
| `DoctorView.jsx` | 원페이퍼 session 로딩 wrapper |
| `DoctorOnePager.jsx` | 원페이퍼 본문 화면 |
| `DoctorOnePagerParts.jsx` | 증상 카드, 문맥 chip, UI 조각 |
| `DoctorAgendaPanel.jsx` | Q4 환자 질문, 의사 답변, 환자 강조사항 입력 |
| `DoctorOnePager.mocks.js` | UI 목업 데이터 |

백엔드 onepaper JSON은 그대로 화면에 쓰기 어렵기 때문에 `services/onepagerAdapter.js`에서 화면용 구조로 정규화합니다.

### `components/patient/PatientGuideScreen.jsx`

의사가 입력한 답변과 강조사항을 환자 안내문으로 보여주는 화면입니다.

특징:

- 출력용 레이아웃
- 가족 공유 또는 종이 출력 시나리오에 맞춘 큰 글씨
- 말로 재생하기 버튼
- 의사 강조사항은 LLM으로 바꾸지 않고 그대로 표시

---

## API service 구조

```text
src/services/
├── api.js
├── transcribeStreaming.js
├── onepagerAdapter.js
├── onepagerBrief.js
├── demoSessions.js
└── api/
    ├── client.js
    ├── sessions.js
    ├── transcripts.js
    ├── doctor.js
    └── mockResponses.js
```

| 파일 | 역할 |
| --- | --- |
| `api/client.js` | `VITE_API_BASE_URL`, 목업 여부, session 정규화 |
| `api/sessions.js` | 세션 생성, 조회, 대기열, 직원 도움 요청 |
| `api/transcripts.js` | `/process-answer` 호출 |
| `api/doctor.js` | 원페이퍼, 의사 답변, 안내문 API 호출 |
| `transcribeStreaming.js` | 브라우저 마이크 오디오를 Amazon Transcribe Streaming WebSocket으로 전송 |
| `onepagerAdapter.js` | 백엔드 onepaper JSON을 UI shape으로 변환 |
| `onepagerBrief.js` | 원페이퍼 brief가 비어 있을 때만 fallback 표시 생성 |

---

## 음성 인식 동작 방식

현재 MVP는 환자 음성을 S3에 업로드하지 않습니다.

동작 순서:

1. 환자 화면이 `POST /transcribe-stream-url` 호출
2. 백엔드가 Amazon Transcribe Streaming presigned WebSocket URL 발급
3. 브라우저가 마이크 오디오를 PCM 16-bit로 변환
4. AWS EventStream 형식으로 WebSocket 전송
5. Transcribe가 partial/final transcript 반환
6. 화면에 인식 텍스트 표시
7. 환자가 확인하면 텍스트만 `/process-answer`로 전송

관련 파일:

- `hooks/useStreamingTranscribe.js`
- `services/transcribeStreaming.js`
- `components/patient/VoiceScreen.jsx`
- `components/patient/ConfirmTranscriptScreen.jsx`

---

## 원페이퍼 데이터 표시 원칙

프론트는 백엔드 결과를 임의로 의료적 판단으로 바꾸지 않습니다.

- 증상명, 원문 quote, score는 백엔드 `matched_slots`를 사용합니다.
- 환자 질문은 백엔드 `agenda`를 사용합니다.
- 체크리스트는 백엔드 `review_items`를 사용합니다.
- EMR 문장은 백엔드 `transfer_text`를 사용합니다.
- 환자 안내 강조사항은 의사가 입력한 원문을 그대로 보여줍니다.

화면 fallback은 UI가 깨지지 않도록 빈 값일 때만 사용합니다. 의료적으로 새로운 내용을 만들기 위한 fallback이 아닙니다.

---

## 빌드

```powershell
cd C:\Users\CGB\munjin-talk-talk-mvp\frontend
npm run build
```

결과:

```text
frontend/dist/
├── index.html
└── assets/
```

`dist/`는 빌드 산출물이므로 저장소에 올리지 않는 것이 원칙입니다.

---

## Amplify 배포

GitHub 연결 배포 기준:

```text
Monorepo app root: frontend
Build command: npm run build
Build output directory: dist
Environment variable:
  VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
```

`amplify.yml`은 저장소 root에 있습니다.

직접 zip 배포를 할 때는 `frontend/dist` 폴더 자체가 아니라 그 안의 파일을 zip해야 합니다.

올바른 zip root:

```text
index.html
assets/
```

---

## 라우팅 주의사항

Vite/React는 single-page app입니다. Amplify에서 아래 rewrite가 필요합니다.

```json
[
  {
    "source": "/<*>",
    "status": "404-200",
    "target": "/index.html"
  }
]
```

이 규칙이 없으면 `/doctor/queue`, `/patient/:sessionId` 같은 경로를 새로고침할 때 404가 날 수 있습니다.

---

## 프론트에서 자주 수정하는 위치

| 바꾸고 싶은 것 | 볼 파일 |
| --- | --- |
| 질문 문구, 질문 순서 | `src/config/questions.js` |
| 위험 키워드 UI 1차 감지 | `src/config/safetyKeywords.js` |
| 접수처 입력 UI | `components/staff/ReceptionForm.jsx` |
| 환자 문진 흐름 | `components/patient/PatientFlow.jsx` |
| 마이크 화면 | `components/patient/VoiceScreen.jsx` |
| STT streaming 구현 | `services/transcribeStreaming.js` |
| 원페이퍼 표시 | `components/doctor/DoctorOnePager.jsx` |
| Q4 답변 입력 | `components/doctor/DoctorAgendaPanel.jsx` |
| 안내문 화면 | `components/patient/PatientGuideScreen.jsx` |
| API endpoint 연결 | `services/api/` |

---

## 확인 체크리스트

프론트 수정 후 최소한 아래는 확인합니다.

```powershell
npm run build
```

브라우저에서 확인:

1. `/staff`에서 세션 생성
2. 상단 메뉴가 세션 생성 후 활성화되는지 확인
3. `/patient/:sessionId`에서 마이크 권한 요청이 뜨는지 확인
4. 발화 텍스트가 확인 화면으로 넘어가는지 확인
5. `/doctor/:sessionId`에서 원문 quote와 증상 카드가 보이는지 확인
6. 의사 답변 입력 후 `/guide/:sessionId`에서 안내문이 보이는지 확인

---

## 현재 MVP에서 아직 남은 프론트 과제

- 직원/의사 화면 인증과 권한 분리
- 실제 병원 대기번호 시스템 연동
- 태블릿 기기별 마이크 권한 UX 세부 조정
- 환자 안내문 가족 공유 URL 정책
- 인쇄 CSS 고도화
- 접근성 검토

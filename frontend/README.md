# 문진톡톡 프론트엔드

문진톡톡 프론트엔드는 React + Vite로 구현된 단일 페이지 웹앱입니다. 하나의 배포 안에서 접수처, 환자 태블릿, 의사 대기열, 의사용 원페이퍼, 환자 안내문 화면을 제공합니다. AWS Amplify Hosting 배포를 기준으로 구성되어 있습니다.

프론트엔드는 의료적 판단을 직접 수행하지 않습니다. 화면 상태, 음성 입력, API 호출, 백엔드 JSON 표시를 담당하며, LLM extraction·IR 매칭·schema validation은 백엔드에서 수행합니다.

---

## 화면 구성

| 화면 | URL | 주 사용자 | 역할 |
| --- | --- | --- | --- |
| 직원 접수 | `/staff` | 접수처 직원 | 환자 정보 입력, 초진/재진 선택, 문진 세션 생성, 오늘 접수 목록 확인 |
| 환자 태블릿 | `/patient/:sessionId` | 환자 | 음성 문진, 발화 확인, 직원 도움 요청, 안전 분기 처리 |
| 의사 대기열 | `/doctor/queue` | 의료진 | 문진 완료 환자와 우선 확인 환자 목록 확인 |
| 원페이퍼 | `/doctor/:sessionId` | 의료진 | 증상, 원문 quote, 문진 맥락, 환자 질문, 확인 항목 확인 |
| 안내문 출력 | `/guide/:sessionId` | 환자·직원 | 의사 답변과 강조사항을 환자용 안내문으로 표시 |

세션이 없을 때는 환자 태블릿, 원페이퍼, 안내문 이동 메뉴가 비활성화됩니다. 접수처에서 세션을 생성하면 해당 세션 기준으로 각 화면에 접근할 수 있습니다.

---

## 실행 환경

필수:

- Node.js 20.19 이상 또는 22.12 이상
- npm
- HTTPS 배포 환경 또는 localhost

브라우저 마이크 접근은 HTTPS 또는 localhost에서만 안정적으로 허용됩니다. Amplify 배포 URL은 HTTPS이므로 태블릿 테스트에 사용할 수 있습니다.

---

## 로컬 실행

```powershell
cd frontend
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

`frontend/.env.example`:

```text
VITE_API_BASE_URL=
```

### AWS 백엔드 연결

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.<region>.amazonaws.com
```

이 설정에서는 접수, 문진 처리, 원페이퍼 조회, 의사 답변 저장, 안내문 조회가 실제 API Gateway + Lambda 백엔드로 연결됩니다.

## 폴더 구조

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

## 주요 파일과 책임

### 앱 라우팅

| 파일 | 책임 |
| --- | --- |
| `src/App.jsx` | 전체 라우팅, 상단 메뉴, 현재 세션 상태 관리 |
| `src/main.jsx` | React 앱 mount |

### 접수처

| 파일 | 책임 |
| --- | --- |
| `components/staff/ReceptionView.jsx` | 접수처 화면 controller |
| `components/staff/ReceptionForm.jsx` | 환자 기본 정보 입력 |
| `components/staff/ReceptionSessionList.jsx` | 오늘 접수 목록과 화면 이동 버튼 |
| `components/staff/ReceptionManualInput.jsx` | 직원 수동 문진 입력 |
| `components/staff/receptionUtils.js` | 연락처 formatting, 환자 표시 helper |

접수처는 `POST /sessions`를 호출해 세션을 생성합니다. 수동 입력은 환자가 음성 문진을 진행할 수 없거나 직원이 대신 입력해야 할 때 사용됩니다.

### 환자 태블릿

| 파일 | 책임 |
| --- | --- |
| `components/patient/PatientKioskView.jsx` | `sessionId` 기반 환자 세션 로딩 |
| `components/patient/PatientFlow.jsx` | 환자 문진 상태 머신 |
| `components/patient/VoiceScreen.jsx` | 질문 화면, 마이크 UI, 실시간 인식 문구 표시 |
| `components/patient/ConfirmTranscriptScreen.jsx` | 환자가 STT 결과를 확인하는 화면 |
| `components/patient/SafetyAlertScreen.jsx` | 위험 표현 감지 후 직원 도움/문진 종료 처리 |
| `components/patient/StaffCallScreen.jsx` | 직원 호출 후 복귀 또는 종료 |
| `components/patient/DoneScreen.jsx` | 문진 완료 안내 |
| `components/patient/VisitTypeScreen.jsx` | 초진/재진 선택 |

문진 흐름:

```text
세션 로드
  -> 초진/재진 확인
  -> 질문 화면
  -> Transcribe Streaming 실시간 인식
  -> 환자 확인 화면
  -> /process-answer 전송(text + question_id + question_text)
  -> 다음 질문 또는 완료
```

`question_text`는 환자 화면에 실제 표시된 질문 문구입니다. 백엔드는 이 값을 extraction prompt에 넣어 LLM이 “어떤 질문에 대한 답변인지”를 잃지 않도록 합니다. 프론트가 보내지 못한 경우에는 백엔드 도메인팩의 기본 질문 문구를 fallback으로 사용합니다.

### 의료진 화면

| 파일 | 책임 |
| --- | --- |
| `components/doctor/DoctorQueueView.jsx` | 의사 대기열 |
| `components/doctor/DoctorView.jsx` | 원페이퍼 세션 로딩 wrapper |
| `components/doctor/DoctorOnePager.jsx` | 원페이퍼 본문 |
| `components/doctor/DoctorOnePagerParts.jsx` | 원페이퍼 UI 조각 |
| `components/doctor/DoctorAgendaPanel.jsx` | 환자 질문, 의사 답변, 환자 강조사항 입력 |

원페이퍼 화면에는 증상 매칭 숫자를 표시하지 않습니다. 백엔드 내부에는 `ir_trace`가 남지만, 의료진 UI에는 `매칭됨` 또는 `우선 확인` 상태만 표시합니다. 숫자형 점수가 진단 확률처럼 해석되는 것을 방지하기 위한 처리입니다.

### 환자 안내문

| 파일 | 책임 |
| --- | --- |
| `components/patient/PatientGuideScreen.jsx` | 환자 안내문 표시, 말로 재생하기, 출력 화면 |

의사 강조사항은 LLM이 바꾸지 않고 원문 그대로 표시합니다.

---

## API 서비스 계층

```text
src/services/
├── api.js
├── transcribeStreaming.js
├── onepagerAdapter.js
└── api/
    ├── client.js
    ├── sessions.js
    ├── transcripts.js
    └── doctor.js
```

| 파일 | 역할 |
| --- | --- |
| `services/api/client.js` | API base URL, 공통 helper |
| `services/api/sessions.js` | 세션 생성·조회·대기열·직원 도움 요청 |
| `services/api/transcripts.js` | `/process-answer` 호출. 답변 텍스트와 함께 `question_text`를 전송 |
| `services/api/doctor.js` | 원페이퍼 조회, 의사 답변 저장, 안내문 조회 |
| `services/transcribeStreaming.js` | Amazon Transcribe Streaming WebSocket 통신 |
| `services/onepagerAdapter.js` | 백엔드 onepaper JSON을 화면용 구조로 변환 |

---

## Transcribe Streaming 처리

현재 프론트는 환자 음성을 S3에 업로드하지 않습니다.

처리 순서:

1. 환자 화면에서 `POST /transcribe-stream-url` 호출
2. 백엔드가 Transcribe Streaming presigned WebSocket URL 반환
3. 브라우저가 마이크 권한 요청
4. 오디오를 PCM 16-bit로 변환
5. AWS EventStream 포맷으로 WebSocket 전송
6. Transcribe partial/final transcript 수신
7. 화면에 인식 문구 표시
8. 환자 확인 후 텍스트만 `/process-answer`로 전송

관련 파일:

- `hooks/useStreamingTranscribe.js`
- `services/transcribeStreaming.js`
- `components/patient/VoiceScreen.jsx`
- `components/patient/ConfirmTranscriptScreen.jsx`

---

## 오류 표시 원칙

프론트는 LLM validator 오류를 환자에게 기술 용어로 노출하지 않습니다.

예시:

| 내부 원인 | 환자 화면 표시 |
| --- | --- |
| schema validation 실패 | 문진 처리 중 오류가 발생했습니다. 다시 말씀해 주세요. |
| STT 결과 없음 | 음성 인식 결과가 비어 있습니다. 다시 말씀해 주세요. |
| Transcribe 연결 실패 | 마이크 버튼을 다시 눌러 말씀해 주세요. |

개발자용 세부 오류는 브라우저 console과 백엔드 CloudWatch Logs에서 확인합니다.

---

## 빌드

```powershell
cd frontend
npm run build
```

산출물:

```text
frontend/dist/
├── index.html
└── assets/
```

`dist/`는 빌드 결과물이므로 저장소에 포함하지 않습니다.

---

## Amplify 배포

GitHub 연결 배포 설정:

```text
Monorepo app root: frontend
Build command: npm run build
Build output directory: dist
Environment variables:
  VITE_API_BASE_URL=https://<api-id>.execute-api.<region>.amazonaws.com
```

SPA rewrite:

```json
[
  {
    "source": "/<*>",
    "status": "404-200",
    "target": "/index.html"
  }
]
```

직접 zip 배포 시 올바른 zip root:

```text
index.html
assets/
```

---

## 수정 위치 안내

| 변경 목적 | 파일 |
| --- | --- |
| 질문 문구와 질문 순서 | `src/config/questions.js` |
| 환자 화면 위험 키워드 1차 감지 | `src/config/safetyKeywords.js` |
| 접수처 입력 화면 | `components/staff/ReceptionForm.jsx` |
| 환자 문진 흐름 | `components/patient/PatientFlow.jsx` |
| 마이크 화면 | `components/patient/VoiceScreen.jsx` |
| STT streaming | `services/transcribeStreaming.js` |
| 원페이퍼 표시 | `components/doctor/DoctorOnePager.jsx` |
| Q4 답변 입력 | `components/doctor/DoctorAgendaPanel.jsx` |
| 안내문 화면 | `components/patient/PatientGuideScreen.jsx` |
| API 연결 | `services/api/` |
| 전체 색상·토큰 | `src/styles/tokens.css` |
| 전역 스타일 | `src/styles/global.css` |

---

## 검증 체크리스트

프론트 수정 후 최소 검증:

```powershell
npm run build
```

브라우저 검증:

1. `/staff`에서 세션 생성
2. 상단 메뉴가 세션 생성 후 활성화되는지 확인
3. `/patient/:sessionId`에서 마이크 권한 요청 확인
4. STT 결과가 확인 화면으로 넘어가는지 확인
5. `/doctor/:sessionId`에서 증상 quote와 `매칭됨` 배지 확인
6. 의사 답변 입력 후 `/guide/:sessionId`에서 안내문 확인

---

## 남은 프론트 과제

- 직원/의사 인증과 권한 분리
- 실제 병원 대기번호 시스템 연동
- 태블릿 기기별 마이크 권한 UX 검증
- 환자 안내문 가족 공유 URL 정책
- 인쇄 CSS 고도화
- 접근성 검토

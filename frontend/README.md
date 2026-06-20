# 📱 문진톡톡 · 프론트엔드

React + Vite 단일 페이지 웹앱. 하나의 배포 안에서 **접수처 · 환자 태블릿 · 의사 대기열 · 원페이퍼 · 환자 안내문** 5개 화면을 제공합니다. AWS Amplify Hosting 배포를 기준으로 구성돼 있습니다.

> 📍 [루트 README](../README.md) · [백엔드](../backend/README.md) · [문서 모음](../docs/README.md)

프론트엔드는 의료 판단을 직접 수행하지 않습니다. 화면 상태, 음성 입력, API 호출, 백엔드 JSON 표시만 담당하며 LLM extraction · IR 매칭 · schema validation은 모두 백엔드에서 수행합니다.

---

## 🖥️ 화면 구성

| 화면 | URL | 사용자 | 역할 |
| --- | --- | --- | --- |
| 직원 접수 | `/staff` | 접수처 직원 | 환자 정보 입력, 초진/재진 선택, 세션 생성, 오늘 접수 목록 |
| 환자 태블릿 | `/patient/:sessionId` | 환자 | 음성 문진, 발화 확인, 직원 도움 요청, 안전 분기 |
| 의사 대기열 | `/doctor/queue` | 의료진 | 문진 완료/우선 확인 환자 목록 |
| 원페이퍼 | `/doctor/:sessionId` | 의료진 | 증상·원문 quote·문진 맥락·환자 질문·확인 항목 |
| 안내문 출력 | `/guide/:sessionId` | 환자·직원 | 의사 답변·강조사항을 환자용 안내문으로 표시 |

세션이 없으면 환자 태블릿·원페이퍼·안내문 메뉴가 비활성화됩니다. 접수처에서 세션을 생성하면 그 세션 기준으로 각 화면에 접근할 수 있습니다.

---

## 🚀 로컬 실행

**필수:** Node.js 20.19+ 또는 22.12+, npm. 마이크 접근은 HTTPS 또는 localhost에서만 안정적으로 허용됩니다.

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev -- --host 127.0.0.1 --port 5173
# 브라우저: http://127.0.0.1:5173/staff
```

<details>
<summary>Windows PowerShell</summary>

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev -- --host 127.0.0.1 --port 5173
```
</details>

### 환경 변수 (`frontend/.env.local`)

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.<region>.amazonaws.com
```

이 값이 설정되면 접수·문진 처리·원페이퍼 조회·의사 답변 저장·안내문 조회가 실제 API Gateway + Lambda 백엔드로 연결됩니다.

---

## 🗂️ 폴더 구조

```text
frontend/
├── index.html
├── package.json
├── vite.config.js
├── .env.example
├── public/
│   └── audio-worklets/pcm16-processor.js   # 마이크 PCM 16-bit 변환 worklet
└── src/
    ├── App.jsx          # 라우팅, 상단 메뉴, 현재 세션 상태
    ├── main.jsx         # React mount
    ├── components/{staff,patient,doctor,tablet}/
    ├── hooks/           # useStreamingTranscribe.js
    ├── services/        # api.js, transcribeStreaming.js, onepagerAdapter.js, api/
    ├── config/          # questions.js, questionText.js, safetyKeywords.js
    ├── assets/          # munjin-logo.svg
    └── styles/          # tokens.css, global.css
```

---

## 🧩 주요 파일과 책임

### 접수처 (`components/staff/`)

| 파일 | 책임 |
| --- | --- |
| `ReceptionView.jsx` | 접수처 화면 controller |
| `ReceptionForm.jsx` | 환자 기본 정보 입력 |
| `ReceptionSessionList.jsx` | 오늘 접수 목록과 화면 이동 |
| `ReceptionManualInput.jsx` | 직원 수동 문진 입력 |
| `receptionUtils.js` | 연락처 formatting, 환자 표시 helper |

접수처는 `POST /sessions`로 세션을 생성합니다. 수동 입력은 환자가 음성 문진을 못 하거나 직원이 대신 입력할 때 사용됩니다.

### 환자 태블릿 (`components/patient/`)

| 파일 | 책임 |
| --- | --- |
| `PatientKioskView.jsx` | `sessionId` 기반 세션 로딩 |
| `PatientFlow.jsx` | 환자 문진 상태 머신 |
| `VisitTypeScreen.jsx` | 초진/재진 선택 |
| `VoiceScreen.jsx` | 질문 화면, 마이크 UI, 실시간 인식 문구 |
| `ConfirmTranscriptScreen.jsx` | 환자가 STT 결과 확인 |
| `SafetyAlertScreen.jsx` | 위험 표현 감지 후 직원 도움/종료 |
| `StaffCallScreen.jsx` | 직원 호출 후 복귀/종료 |
| `DoneScreen.jsx` | 문진 완료 안내 |
| `PatientGuideScreen.jsx` | 환자 안내문 표시, 말로 재생, 출력 |

문진 흐름:

```text
세션 로드 → 초진/재진 → 질문 화면 → Transcribe Streaming 실시간 인식
        → 환자 확인 → POST /process-answer (text + question_id + question_text)
        → 다음 질문 또는 완료
```

`question_text`는 환자 화면에 실제로 표시된 질문 문구입니다. 백엔드는 이 값을 extraction prompt에 넣어 "어떤 질문에 대한 답변인지"를 잃지 않게 합니다. 프론트가 못 보낸 경우 백엔드 도메인팩의 기본 질문 문구를 fallback으로 씁니다.

### 의료진 (`components/doctor/`)

| 파일 | 책임 |
| --- | --- |
| `DoctorQueueView.jsx` | 의사 대기열 |
| `DoctorView.jsx` | 원페이퍼 세션 로딩 wrapper |
| `DoctorOnePager.jsx` | 원페이퍼 본문 |
| `DoctorOnePagerParts.jsx` | 원페이퍼 UI 조각 |
| `DoctorAgendaPanel.jsx` | 환자 질문, 의사 답변, 강조사항 입력 |

원페이퍼에는 증상 매칭 숫자를 표시하지 않습니다. UI에는 `매칭됨` 또는 `우선 확인` 상태만 표시해, 숫자형 점수가 진단 확률처럼 해석되는 것을 막습니다. 의사 강조사항은 LLM이 바꾸지 않고 원문 그대로 표시합니다.

---

## 🔌 API 서비스 계층 (`src/services/`)

```text
services/
├── api.js                 # 레거시 호환 진입점
├── transcribeStreaming.js # Transcribe Streaming WebSocket 통신
├── onepagerAdapter.js     # 백엔드 onepaper JSON → 화면용 구조 변환
└── api/
    ├── client.js          # API base URL, 공통 helper
    ├── sessions.js        # 세션 생성·조회·대기열·직원 도움
    ├── transcripts.js     # /process-answer 호출 (text + question_text)
    ├── doctor.js          # 원페이퍼 조회, 의사 답변 저장, 안내문 조회
    └── questionSets.js     # 질문셋 메타 조회
```

---

## 🎙️ Transcribe Streaming 처리

프론트는 환자 음성을 S3에 업로드하지 않습니다.

1. `POST /transcribe-stream-url` 호출
2. 백엔드가 presigned WebSocket URL 반환
3. 브라우저 마이크 권한 요청
4. 오디오를 PCM 16-bit로 변환 (`public/audio-worklets/pcm16-processor.js`)
5. AWS EventStream 포맷으로 WebSocket 전송
6. partial/final transcript 수신 → 화면 표시
7. 환자 확인 후 **텍스트만** `/process-answer`로 전송

관련 파일: `hooks/useStreamingTranscribe.js`, `services/transcribeStreaming.js`, `components/patient/VoiceScreen.jsx`, `ConfirmTranscriptScreen.jsx`

---

## ⚠️ 오류 표시 원칙

프론트는 validator 오류를 환자에게 기술 용어로 노출하지 않습니다.

| 내부 원인 | 환자 화면 표시 |
| --- | --- |
| schema validation 실패 | 문진 처리 중 오류가 발생했습니다. 다시 말씀해 주세요. |
| STT 결과 없음 | 음성 인식 결과가 비어 있습니다. 다시 말씀해 주세요. |
| Transcribe 연결 실패 | 마이크 버튼을 다시 눌러 말씀해 주세요. |

개발자용 세부 오류는 브라우저 console과 백엔드 CloudWatch Logs에서 확인합니다.

---

## 🛠️ 수정 위치 빠른 참조

| 변경 목적 | 파일 |
| --- | --- |
| 질문 문구·순서 | `src/config/questions.js`, `questionText.js` |
| 위험 키워드 1차 감지 | `src/config/safetyKeywords.js` |
| 환자 문진 흐름 | `components/patient/PatientFlow.jsx` |
| 마이크 화면 | `components/patient/VoiceScreen.jsx` |
| STT streaming | `services/transcribeStreaming.js` |
| 원페이퍼 표시 | `components/doctor/DoctorOnePager.jsx` |
| Q4 답변 입력 | `components/doctor/DoctorAgendaPanel.jsx` |
| 안내문 화면 | `components/patient/PatientGuideScreen.jsx` |
| API 연결 | `services/api/` |
| 색상·토큰 / 전역 스타일 | `src/styles/tokens.css` / `global.css` |

---

## 🏗️ 빌드 & 배포

```bash
cd frontend
npm run build       # 산출물: frontend/dist/ (저장소에 포함하지 않음)
```

### Amplify (GitHub 연결)

```text
Monorepo app root: frontend
Build command: npm run build
Build output directory: dist
Environment variable:
  VITE_API_BASE_URL=https://<api-id>.execute-api.<region>.amazonaws.com
```

SPA rewrite:

```json
[{ "source": "/<*>", "status": "404-200", "target": "/index.html" }]
```

---

## ✅ 검증 체크리스트

빌드 확인 후 브라우저에서:

1. `/staff`에서 세션 생성 → 상단 메뉴 활성화 확인
2. `/patient/:sessionId`에서 마이크 권한 요청 확인
3. STT 결과가 확인 화면으로 넘어가는지 확인
4. `/doctor/:sessionId`에서 증상 quote와 `매칭됨` 배지 확인
5. 의사 답변 입력 후 `/guide/:sessionId`에서 안내문 확인

---

## 🧭 남은 과제

직원/의사 인증·권한 분리, 병원 대기번호 시스템 연동, 태블릿 기기별 마이크 권한 UX 검증, 안내문 가족 공유 URL 정책, 인쇄 CSS 고도화, 접근성 검토.

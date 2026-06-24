# 문진톡톡 프론트엔드

React + Vite 기반 단일 페이지 웹앱입니다. 하나의 Amplify 배포 안에서 직원 접수, 환자 태블릿, 의사 대기열, 원페이퍼, 환자 안내문 화면을 제공합니다.

프론트엔드는 의료 판단을 수행하지 않습니다. 화면 상태, 음성 입력, STT 결과 확인, API 호출, 백엔드 JSON 표시를 담당합니다. LLM extraction, Hybrid IR, schema validation, 원페이퍼 생성은 백엔드에서 처리합니다.

관련 문서:

- [루트 README](../README.md)
- [백엔드 README](../backend/README.md)
- [문서 모음](../docs/README.md)

---

## 1. 화면 구성

| 화면 | URL | 사용자 | 역할 |
| --- | --- | --- | --- |
| 직원 접수 | `/staff` | 접수처 직원 | 환자 정보 입력, 세션 생성, 오늘 접수 목록, 수동 문진 입력 |
| 환자 태블릿 대기열 | `/tablet` | 환자·직원 | 문진 대기 환자 선택 |
| 환자 문진 | `/patient/:sessionId` | 환자 | 동의, 초진/재진 확인, 음성 문진, STT 확인, 직원 도움 요청 |
| 의사 대기열 | `/doctor/queue` | 의료진 | 분석 중/문진 완료/우선 확인 환자 목록 |
| 원페이퍼 | `/doctor/:sessionId` | 의료진 | 증상, 원문, 문진 요약, 환자 질문, 확인 항목, EMR 초안 |
| 안내문 출력 | `/guide/:sessionId` | 환자·직원 | 진료 후 안내문, 음성 재생, 종이 출력 |

세션이 없거나 선택되지 않은 경우 환자 태블릿, 원페이퍼, 안내문 메뉴는 비활성화됩니다.

---

## 2. 최신 환자 문진 흐름

환자 문진 중에는 LLM 분석을 기다리지 않습니다. Q1~Q4 답변을 모두 받은 뒤 한 번에 저장하고, 백엔드가 별도 작업으로 원페이퍼를 생성합니다.

```text
환자 태블릿 대기열
  -> 세션 선택
  -> 서비스 이용 동의
  -> 초진/재진 확인
  -> Q1~Q4 음성 입력
  -> STT 결과 확인 또는 직접 수정
  -> 답변 4개를 /process-answers 로 일괄 제출
  -> 환자 완료 화면
  -> 태블릿 대기열로 복귀

의료진 화면
  -> analysis_pending 상태면 "원페이퍼 생성 중" 표시
  -> 분석 완료 후 원페이퍼 확인
  -> 실패 시 AI 재검토 또는 수동 확인
```

이 구조 덕분에 환자는 질문마다 LLM 분석 지연을 기다리지 않습니다. 문진 완료 이후 원페이퍼 생성은 백엔드의 백그라운드 Lambda에서 처리됩니다.

---

## 3. 음성 입력과 STT

| 파일 | 역할 |
| --- | --- |
| `src/hooks/useStreamingTranscribe.js` | 마이크 권한, 녹음 상태, 실시간 전사 연결 |
| `src/services/transcribeStreaming.js` | Transcribe Streaming websocket 처리 |
| `public/audio-worklets/pcm16-processor.js` | 브라우저 마이크 입력을 PCM 16-bit stream으로 변환 |
| `src/components/patient/VoiceScreen.jsx` | 환자 음성 입력 화면 |
| `src/components/patient/ConfirmTranscriptScreen.jsx` | 전사 결과 확인/수정 화면 |

음성 원본 파일은 저장하지 않습니다. 브라우저가 Transcribe Streaming으로 음성을 보내고, 환자가 확인한 텍스트만 백엔드로 전송합니다.

---

## 4. API 연동

API 호출은 `src/services/api/` 아래에 역할별로 분리되어 있습니다.

| 파일 | 주요 API |
| --- | --- |
| `sessions.js` | 세션 생성, 세션 조회, 대기열 조회 |
| `transcripts.js` | Q1~Q4 답변 일괄 저장 `/process-answers` |
| `doctor.js` | 원페이퍼 조회, 재분석, 의사 답변 저장 |
| `guide.js` | 환자 안내문 조회 |
| `auth.js` | 직원/의사 접근 코드 로그인 |

`/process-answer` 단일 문항 API는 호환용으로 남아 있으나, 기본 환자 문진 흐름에서는 `/process-answers`를 사용합니다.

---

## 5. 폴더 구조

```text
frontend/
├── index.html
├── package.json
├── vite.config.js
├── public/
│   └── audio-worklets/
└── src/
    ├── App.jsx
    ├── main.jsx
    ├── assets/
    ├── components/
    │   ├── auth/
    │   ├── doctor/
    │   ├── patient/
    │   ├── staff/
    │   └── tablet/
    ├── config/
    ├── hooks/
    ├── services/
    └── styles/
```

---

## 6. 주요 컴포넌트

### 직원 접수

| 파일 | 책임 |
| --- | --- |
| `components/staff/ReceptionView.jsx` | 접수처 화면 controller |
| `ReceptionForm.jsx` | 이름, 생년월일, 성별, 진료과, 연락처 입력 |
| `ReceptionSessionList.jsx` | 오늘 접수 목록과 화면 이동 |
| `ReceptionManualInput.jsx` | 직원 수동 문진 입력 |
| `receptionUtils.js` | 이름 마스킹, 연락처 formatting, 상태 label |

### 환자 태블릿

| 파일 | 책임 |
| --- | --- |
| `components/tablet/TabletQueueView.jsx` | 문진 대기 환자 선택 |
| `components/patient/PatientKioskView.jsx` | 세션 로딩과 환자 화면 진입 |
| `PatientFlow.jsx` | 환자 문진 상태 머신 |
| `ConsentModal.jsx` | 서비스 이용 동의 |
| `VisitTypeScreen.jsx` | 초진/재진 확인 |
| `VoiceScreen.jsx` | 음성 입력 |
| `ConfirmTranscriptScreen.jsx` | 전사 결과 확인/수정 |
| `SafetyAlertScreen.jsx` | 위험 표현 감지 시 직원 호출 |
| `DoneScreen.jsx` | 완료 안내와 대기열 복귀 |

### 의료진

| 파일 | 책임 |
| --- | --- |
| `components/doctor/DoctorQueueView.jsx` | 의사 대기열 |
| `DoctorView.jsx` | 원페이퍼 데이터 로딩 |
| `DoctorOnePager.jsx` | 원페이퍼 화면 |
| `DoctorAgendaPanel.jsx` | 환자 질문 답변, 안내 강조사항 |
| `DoctorSymptomPanel.jsx` | 매칭된 증상과 원문 quote |

### 환자 안내문

| 파일 | 책임 |
| --- | --- |
| `components/patient/PatientGuideScreen.jsx` | 안내문 표시, 말로 재생, 인쇄 |
| `PatientGuideScreen.css` | 출력 전용 print style 포함 |

---

## 7. 접근 제어 UX

직원 화면과 의료진 화면은 접근 코드 로그인 모달을 사용합니다.

```text
직원/의사 화면 접속
  -> 접근 코드 입력
  -> /auth/login
  -> 백엔드 세션 토큰 발급
  -> 이후 API 호출에 토큰 포함
```

환자 화면은 세션별 환자 토큰으로 접근합니다. 직원/의사 접근 코드는 프론트에 하드코딩하지 않고 백엔드 환경 변수로 검증합니다.

---

## 8. 오류 표시 원칙

- 환자 문진 중 백엔드 LLM 분석 실패를 환자에게 직접 노출하지 않습니다.
- 위험 표현이 감지되면 직원 도움 화면으로 분기합니다.
- 원페이퍼가 아직 준비되지 않은 경우 의사 화면에서 “분석 중” 상태와 새로고침/AI 재검토 버튼을 보여줍니다.
- 안내문이 아직 생성되지 않은 경우 빈 화면이 아니라 준비 상태를 보여줍니다.

---

## 9. 로컬 실행

필수: Node.js 20.19+ 또는 22.12+, npm.

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev -- --host 127.0.0.1 --port 5173
```

PowerShell:

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev -- --host 127.0.0.1 --port 5173
```

`.env.local`

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.<region>.amazonaws.com
```

마이크 권한은 HTTPS 또는 localhost에서 안정적으로 허용됩니다.

---

## 10. 빌드와 배포

```bash
cd frontend
npm run build
```

Amplify 설정:

| 항목 | 값 |
| --- | --- |
| 앱 루트 | `frontend` |
| 빌드 명령 | `npm run build` |
| 출력 디렉터리 | `dist` |
| 환경 변수 | `VITE_API_BASE_URL` |

SPA 라우팅을 위해 Amplify rewrite rule은 `/<*> -> /index.html (404 Rewrite)`가 필요합니다.

---

## 11. 검증 항목

- `/staff`에서 세션 생성 가능
- `/tablet`에서 생성된 세션 선택 가능
- 환자 동의 모달이 화면을 막고, 동의 후에만 문진 시작
- Q1~Q4 입력 중 질문마다 긴 LLM 지연 없음
- 문진 완료 후 태블릿 대기열 복귀 가능
- 의사 대기열에서 `analysis_pending` 상태가 보임
- 분석 완료 후 원페이퍼 접근 가능
- 의사 답변 저장 후 안내문 출력 가능
- 인쇄 시 안내문 카드만 출력됨

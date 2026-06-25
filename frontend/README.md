# 문진톡톡 프론트엔드

React + Vite 기반 단일 페이지 웹앱입니다. 하나의 Amplify 배포 안에서 직원 접수, 환자 태블릿, 의사 대기열, 원페이퍼, 환자 안내문 화면을 제공합니다.

프론트엔드는 화면 상태, 음성 입력, STT 결과 확인, API 호출, 백엔드 JSON 표시를 담당합니다. LLM extraction, Hybrid IR, schema validation, 원페이퍼 생성은 백엔드에서 처리합니다.

해커톤 시연에서 프론트엔드가 보여주는 핵심은 “고령 환자가 앱을 설치하거나 긴 문항을 직접 입력하지 않아도 병원 태블릿에서 말로 문진을 끝낼 수 있다”는 점입니다. 직원은 접수와 수동 보조를 맡고, 환자는 음성으로 답하며, 의료진은 진료 전에 정리된 원페이퍼를 확인합니다. 진료 후에는 의사가 남긴 답변과 안내가 환자용 안내문으로 정리되어 종이 출력까지 이어집니다.

따라서 이 프론트엔드는 단순한 입력 폼이 아니라 다음 네 가지 사용 흐름을 하나의 데모로 연결합니다.

- 접수처 직원이 환자 정보를 확인하고 문진 세션을 생성합니다.
- 환자는 태블릿에서 음성으로 Q1~Q4 문진을 완료합니다.
- 의료진은 원페이퍼에서 증상, 원문, 문진 요약, 확인 항목, EMR 초안을 봅니다.
- 환자는 진료 후 안내문을 큰 글씨와 음성 재생, 종이 출력 형태로 받습니다.

관련 문서:

- [루트 README](../README.md)
- [백엔드 README](../backend/README.md)
- [문서 모음](../docs/README.md)

---

## 1. 시연에서 보는 화면

| 화면 | URL | 사용자 | 역할 |
| --- | --- | --- | --- |
| 직원 접수 | `/staff` | 접수처 직원 | 환자 정보 입력, 세션 생성, 오늘 접수 목록, 수동 문진 입력 |
| 환자 태블릿 대기열 | `/tablet` | 환자·직원 | 문진 대기 환자 선택 |
| 환자 문진 | `/patient/:sessionId` | 환자 | 동의, 초진/재진 확인, 음성 문진, STT 확인, 직원 도움 요청 |
| 의사 대기열 | `/doctor/queue` | 의료진 | 분석 중/문진 완료/우선 확인 환자 목록 |
| 원페이퍼 | `/doctor/:sessionId` | 의료진 | 증상, 원문, 문진 요약, 환자 질문, 확인 항목, EMR 초안 |
| 안내문 출력 | `/guide/:sessionId` | 환자·직원 | 진료 후 안내문, 음성 재생, 종이 출력 |

세션이 없거나 선택되지 않은 경우 환자 태블릿, 원페이퍼, 안내문 메뉴는 비활성화됩니다.

해커톤 시연은 다음 순서로 진행하면 서비스 흐름이 가장 자연스럽게 보입니다.

```text
/staff
  -> 환자 접수와 세션 생성
/tablet
  -> 문진 대기 환자 선택
/patient/:sessionId
  -> 동의, 음성 문진, STT 확인, 완료
/doctor/queue
  -> 분석 중/완료 상태 확인
/doctor/:sessionId
  -> 원페이퍼와 의료진 확인 항목 확인
/guide/:sessionId
  -> 환자 안내문 출력
```

---

## 2. 환자가 문진을 마치는 과정

환자 문진은 Q1~Q4 답변을 모두 받은 뒤 한 번에 저장하고, 백엔드가 별도 작업으로 원페이퍼를 생성합니다.

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

문진 완료 이후 원페이퍼 생성은 백엔드의 백그라운드 Lambda에서 처리됩니다.

---

## 3. 음성 문진 처리 방식

| 파일 | 역할 |
| --- | --- |
| `src/hooks/useStreamingTranscribe.js` | 마이크 권한, 녹음 상태, 실시간 전사 연결 |
| `src/services/transcribeStreaming.js` | Transcribe Streaming websocket 처리 |
| `public/audio-worklets/pcm16-processor.js` | 브라우저 마이크 입력을 PCM 16-bit stream으로 변환 |
| `src/components/patient/VoiceScreen.jsx` | 환자 음성 입력 화면 |
| `src/components/patient/ConfirmTranscriptScreen.jsx` | 전사 결과 확인/수정 화면 |

음성 원본 파일은 저장하지 않습니다. 브라우저가 Transcribe Streaming으로 음성을 보내고, 환자가 확인한 텍스트만 백엔드로 전송합니다.

`public/audio-worklets/pcm16-processor.js`는 삭제하면 안 됩니다. Vite의 `public` 폴더는 빌드 후 정적 파일로 그대로 배포되며, 이 파일은 브라우저 마이크 입력을 Amazon Transcribe Streaming에 보낼 수 있는 PCM 16-bit 오디오 조각으로 변환합니다. 환자 음성 문진에서 실시간 STT가 동작하기 위한 런타임 파일입니다.

---

## 4. 백엔드와 주고받는 데이터

API 호출은 `src/services/api/` 아래에 역할별로 분리되어 있습니다.

| 파일 | 주요 API |
| --- | --- |
| `sessions.js` | 세션 생성, 세션 조회, 대기열 조회 |
| `transcripts.js` | Q1~Q4 답변 일괄 저장 `/process-answers` |
| `doctor.js` | 원페이퍼 조회, 재분석, 의사 답변 저장, 환자 안내문 조회 |
| `client.js` | 공통 fetch, 환자 세션 토큰, 직원/의사 접근 코드 로그인 |

현재 기본 환자 문진 흐름은 Q1~Q4 답변을 모아 `/process-answers`로 한 번에 제출합니다. 질문마다 LLM 분석을 기다리지 않도록 만든 구조입니다.

---

## 5. 프론트엔드 폴더 구성

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

## 6. 화면별 주요 파일

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

## 7. 직원·의료진 접속 방식

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

## 8. 오류 상황을 다루는 방식

- 환자 문진 중 백엔드 LLM 분석 실패를 환자에게 직접 노출하지 않습니다.
- 위험 표현이 감지되면 직원 도움 화면으로 분기합니다.
- 원페이퍼가 아직 준비되지 않은 경우 의사 화면에서 “분석 중” 상태와 새로고침/AI 재검토 버튼을 보여줍니다.
- 안내문이 아직 생성되지 않은 경우 빈 화면이 아니라 준비 상태를 보여줍니다.

---

## 9. 로컬에서 실행하기

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

## 10. 빌드와 Amplify 배포

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

## 11. 시연 전 확인할 것

- `/staff`에서 세션 생성 가능
- `/tablet`에서 생성된 세션 선택 가능
- 환자 동의 모달이 화면을 막고, 동의 후에만 문진 시작
- Q1~Q4 입력 중 질문마다 긴 LLM 지연 없음
- 문진 완료 후 태블릿 대기열 복귀 가능
- 의사 대기열에서 `analysis_pending` 상태가 보임
- 분석 완료 후 원페이퍼 접근 가능
- 의사 답변 저장 후 안내문 출력 가능
- 인쇄 시 안내문 카드만 출력됨

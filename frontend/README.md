# 문진톡톡 프론트엔드

문진톡톡의 사용자 화면을 담당하는 React + Vite 기반 단일 페이지 웹앱입니다.

하나의 Amplify 배포 안에서 직원 접수, 환자 태블릿, 의사 대기열, 의료진 원페이퍼, 환자 안내문 화면을 제공합니다. 프론트엔드는 화면 상태, 음성 입력, STT 결과 확인, API 호출, 백엔드 JSON 표시를 담당하고, LLM 구조화·Hybrid IR·스키마 검증·원페이퍼 생성은 백엔드에서 처리합니다.

프론트엔드의 핵심 목표는 고령 환자가 앱을 설치하거나 긴 문항을 직접 입력하지 않아도, 병원 태블릿에서 말로 문진을 마칠 수 있게 만드는 것입니다. 직원은 접수와 수동 보조를 맡고, 환자는 음성으로 답하며, 의료진은 진료 전에 정리된 원페이퍼를 확인합니다. 진료 후에는 의사가 남긴 답변과 안내가 환자용 안내문으로 정리되어 종이 출력까지 이어집니다.

이 프론트엔드는 다음 네 가지 사용 흐름을 하나의 서비스 화면으로 연결합니다.

- 접수처 직원이 환자 정보를 확인하고 문진 세션을 생성합니다.
- 환자는 태블릿에서 음성으로 Q1~Q4 문진을 완료합니다.
- 의료진은 원페이퍼에서 증상, 원문, 문진 요약, 확인 항목, EMR 초안을 확인합니다.
- 환자는 진료 후 안내문을 큰 글씨, 음성 재생, 종이 출력 형태로 받습니다.

관련 문서:

- [루트 README](../README.md)
- [백엔드 README](../backend/README.md)
- [문서 모음](../docs/README.md)

---

## 1. 화면 구성

| 화면 | URL | 사용자 | 역할 |
| --- | --- | --- | --- |
| 직원 접수 | `/staff` | 접수처 직원 | 환자 정보 입력, 세션 생성, 오늘 접수 목록, 직원 수동 문진 입력 |
| 환자 태블릿 대기열 | `/tablet` | 환자·직원 | 문진 대기 환자 선택 |
| 환자 문진 | `/patient/:sessionId` | 환자 | 동의, 초진/재진 확인, 음성 문진, STT 결과 확인, 직원 도움 요청 |
| 의사 대기열 | `/doctor/queue` | 의료진 | 분석 중·문진 완료·우선 확인 환자 목록 |
| 의료진 원페이퍼 | `/doctor/:sessionId` | 의료진 | 증상, 원문, 문진 요약, 환자 질문, 확인 항목, EMR 초안 |
| 환자 안내문 | `/guide/:sessionId` | 환자·직원 | 진료 후 안내문 확인, 음성 재생, 종이 출력 |

세션이 없거나 선택되지 않은 경우 환자 태블릿, 원페이퍼, 안내문 메뉴는 비활성화됩니다.

시연은 다음 순서로 진행하면 서비스 흐름이 가장 자연스럽게 보입니다.

```text
/staff
  -> 환자 접수와 문진 세션 생성

/tablet
  -> 문진 대기 환자 선택

/patient/:sessionId
  -> 동의, 음성 문진, STT 확인, 문진 완료

/doctor/queue
  -> 분석 중/완료 상태 확인

/doctor/:sessionId
  -> 원페이퍼와 의료진 확인 항목 확인

/guide/:sessionId
  -> 환자 안내문 확인 및 출력
```

---

## 2. 환자 문진 흐름

환자 문진은 Q1~Q4 답변을 모두 받은 뒤 한 번에 백엔드로 제출합니다. 문항마다 LLM 분석을 기다리지 않기 때문에, 환자는 중간 대기 없이 문진을 이어갈 수 있습니다.

```text
환자 태블릿 대기열
  -> 문진 세션 선택
  -> 서비스 이용 동의
  -> 초진/재진 확인
  -> Q1~Q4 음성 입력
  -> STT 결과 확인 또는 직접 수정
  -> 4개 답변 일괄 제출
  -> 문진 완료 화면
  -> 태블릿 대기열 복귀
```

문진 완료 후 원페이퍼 생성은 백엔드에서 별도 처리됩니다. 환자는 분석이 끝날 때까지 기다리지 않고 문진을 마칠 수 있으며, 의료진 화면에서 분석 중/완료 상태를 확인합니다.

```text
의료진 화면
  -> analysis_pending 상태 표시
  -> 분석 완료 후 원페이퍼 접근
  -> 필요 시 AI 재검토 또는 수동 확인
```

---

## 3. 음성 문진 UX와 STT 처리

환자는 큰 마이크 버튼을 눌러 답변을 말하고, 인식된 문장을 확인한 뒤 다음 질문으로 넘어갑니다. 인식 결과가 틀린 경우 다시 말하거나 직접 수정할 수 있습니다.

| 파일 | 역할 |
| --- | --- |
| `src/hooks/useStreamingTranscribe.js` | 마이크 권한, 녹음 상태, 실시간 전사 연결 |
| `src/services/transcribeStreaming.js` | Amazon Transcribe Streaming websocket 처리 |
| `public/audio-worklets/pcm16-processor.js` | 브라우저 마이크 입력을 PCM 16-bit stream으로 변환 |
| `src/components/patient/VoiceScreen.jsx` | 환자 음성 입력 화면 |
| `src/components/patient/ConfirmTranscriptScreen.jsx` | 전사 결과 확인·수정 화면 |

음성 원본 파일은 저장하지 않습니다. 브라우저가 Transcribe Streaming으로 음성을 직접 전송하고, 환자가 확인한 텍스트만 백엔드로 전달합니다.

`public/audio-worklets/pcm16-processor.js` 파일은 브라우저 마이크 입력을 Amazon Transcribe Streaming이 받을 수 있는 오디오 형식으로 변환하는 역할을 합니다. Vite는 `public` 폴더의 파일을 빌드 결과에 그대로 포함하므로, 배포 후에도 브라우저에서 안정적으로 불러올 수 있습니다.

---

## 4. 백엔드 연동 구조

프론트엔드의 API 호출은 `src/services/api/` 아래에서 역할별로 나누어 관리합니다.

| 파일 | 주요 역할 |
| --- | --- |
| `sessions.js` | 세션 생성, 세션 조회, 대기열 조회 |
| `transcripts.js` | Q1~Q4 답변 일괄 저장 |
| `doctor.js` | 원페이퍼 조회, 의사 답변 저장, 환자 안내문 조회 |
| `client.js` | 공통 fetch, 환자 세션 토큰, 직원/의사 로그인 토큰 처리 |

환자 문진 흐름에서는 Q1~Q4 답변을 모두 모아 백엔드에 한 번에 제출합니다. 분석 상태는 의사 대기열과 원페이퍼 화면에서 확인하며, 환자 화면에는 LLM 분석 실패나 대기 상태를 직접 노출하지 않습니다.

---

## 5. 폴더 구성

```text
frontend/
├─ index.html
├─ package.json
├─ vite.config.js
├─ public/
│  └─ audio-worklets/
└─ src/
   ├─ App.jsx
   ├─ main.jsx
   ├─ assets/
   ├─ components/
   │  ├─ auth/
   │  ├─ doctor/
   │  ├─ patient/
   │  ├─ staff/
   │  └─ tablet/
   ├─ config/
   ├─ hooks/
   ├─ services/
   └─ styles/
```

---

## 6. 화면별 구현 파일

### 직원 접수

| 파일 | 역할 |
| --- | --- |
| `components/staff/ReceptionView.jsx` | 접수처 화면 전체 흐름 |
| `ReceptionForm.jsx` | 이름, 생년월일, 성별, 진료과, 연락처 입력 |
| `ReceptionSessionList.jsx` | 오늘 접수 목록과 화면 이동 |
| `ReceptionManualInput.jsx` | 직원 수동 문진 입력 |
| `receptionUtils.js` | 이름 마스킹, 연락처 formatting, 상태 label |

### 환자 태블릿

| 파일 | 역할 |
| --- | --- |
| `components/tablet/TabletQueueView.jsx` | 문진 대기 환자 선택 |
| `components/patient/PatientKioskView.jsx` | 세션 로딩과 환자 화면 진입 |
| `PatientFlow.jsx` | 환자 문진 상태 흐름 |
| `ConsentModal.jsx` | 서비스 이용 동의 |
| `VisitTypeScreen.jsx` | 초진/재진 확인 |
| `VoiceScreen.jsx` | 음성 입력 |
| `ConfirmTranscriptScreen.jsx` | 전사 결과 확인·수정 |
| `SafetyAlertScreen.jsx` | 위험 표현 감지 시 직원 호출 |
| `DoneScreen.jsx` | 문진 완료 안내와 대기열 복귀 |

### 의료진

| 파일 | 역할 |
| --- | --- |
| `components/doctor/DoctorQueueView.jsx` | 의사 대기열 |
| `DoctorView.jsx` | 원페이퍼 데이터 로딩 |
| `DoctorOnePager.jsx` | 원페이퍼 화면 |
| `DoctorAgendaPanel.jsx` | 환자 질문 답변, 안내 강조사항 |
| `DoctorSymptomPanel.jsx` | 매칭된 증상과 원문 quote |

### 환자 안내문

| 파일 | 역할 |
| --- | --- |
| `components/patient/PatientGuideScreen.jsx` | 안내문 표시, 말로 재생, 인쇄 |
| `PatientGuideScreen.css` | 안내문 화면과 인쇄 전용 스타일 |

---

## 7. 접근 제어 흐름

직원 화면과 의료진 화면은 접근 코드 로그인 모달을 사용합니다.

```text
직원/의사 화면 접속
  -> 접근 코드 입력
  -> /auth/login
  -> 백엔드 세션 토큰 발급
  -> 이후 API 호출에 토큰 포함
```

환자 화면은 세션별 환자 토큰으로 접근합니다. 직원/의사 접근 코드는 프론트엔드에 하드코딩하지 않고 백엔드 환경 변수로 검증합니다.

---

## 8. 예외 상황 처리

프론트엔드는 사용자가 흐름 안에 갇히지 않도록 예외 화면과 복귀 버튼을 분리했습니다.

- 위험 표현이 감지되면 환자에게 복잡한 오류를 보여주지 않고 직원 도움 화면으로 전환합니다.
- 직원 도움 화면에서는 직원과 진행하거나 문진 대기열로 돌아갈 수 있습니다.
- 원페이퍼가 아직 준비되지 않은 경우 의료진 화면에서 분석 중 상태를 보여줍니다.
- 원페이퍼 분석이 실패한 경우 의료진이 AI 재검토를 실행할 수 있습니다.
- 안내문이 아직 생성되지 않은 경우 빈 화면 대신 준비 상태를 표시합니다.
- 인쇄 시에는 안내문 본문만 출력되도록 print style을 분리했습니다.

---

## 9. 로컬 실행

필요 환경:

- Node.js 20.19 이상 또는 22.12 이상
- npm

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

`.env.local` 예시:

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.<region>.amazonaws.com
```

마이크 권한은 HTTPS 또는 localhost 환경에서 안정적으로 허용됩니다.

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

SPA 라우팅을 위해 Amplify rewrite rule은 다음과 같이 설정합니다.

```text
/<*> -> /index.html (404 Rewrite)
```

---

## 11. 데모에서 확인할 사용자 경험

프론트엔드는 해커톤 데모에서 환자, 직원, 의료진의 흐름이 끊기지 않도록 구성했습니다.

- 환자는 앱 설치 없이 병원 태블릿에서 문진을 시작합니다.
- Q1~Q4 답변은 문항마다 분석을 기다리지 않고 연속으로 진행됩니다.
- 음성 인식 결과는 환자가 직접 확인하고, 필요하면 다시 말하거나 직접 수정할 수 있습니다.
- 위험 표현이 감지되면 환자에게 복잡한 오류를 보여주지 않고 직원 도움 흐름으로 전환합니다.
- 의료진은 원페이퍼에서 환자 원문, 표준화 표현, 증상 매칭, 확인 항목, EMR 초안을 한 화면에서 확인합니다.
- 진료 후 안내문은 큰 글씨와 음성 재생, 종이 출력에 맞게 표시됩니다.

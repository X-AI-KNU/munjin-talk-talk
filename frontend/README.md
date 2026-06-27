# 문진톡톡 프론트엔드

문진톡톡의 사용자 화면을 담당하는 React와 Vite 기반의 단일 페이지 웹 애플리케이션(SPA)입니다.

하나의 Amplify 배포 환경 안에서 직원 접수, 환자 태블릿, 의사 대기열, 의료진 원페이퍼, 환자 안내문 화면을 통합하여 제공합니다. 프론트엔드의 주요 역할은 화면 상태 관리, 음성 입력 처리, STT(음성 인식) 결과 확인, API 호출, 그리고 백엔드에서 전달받은 JSON 데이터의 시각화입니다. LLM 구조화, Hybrid IR, 스키마 검증, 원페이퍼 생성과 같은 핵심 로직은 백엔드에서 전담하여 처리합니다.

프론트엔드 개발의 핵심 목표는 고령 환자가 별도의 앱을 설치하거나 긴 문항을 직접 입력할 필요 없이, 병원에 비치된 태블릿을 통해 말로 문진을 완료할 수 있도록 지원하는 것입니다. 직원은 접수와 수동 보조를 담당하고, 환자는 음성으로 답변하며, 의료진은 진료 전에 체계적으로 정리된 원페이퍼를 확인하게 됩니다. 진료가 끝난 후에는 의사의 답변과 안내 사항이 환자용 안내문으로 정리되어 종이 출력까지 매끄럽게 이어집니다.

본 프론트엔드는 다음 네 가지 주요 사용 흐름을 하나의 서비스 화면으로 연결합니다.

* **직원 접수:** 접수처 직원이 환자 정보를 확인하고 문진 세션을 생성합니다.
* **환자 문진:** 환자는 태블릿에서 음성으로 Q1부터 Q4까지의 문진을 완료합니다.
* **의료진 원페이퍼:** 의료진은 원페이퍼를 통해 환자의 증상, 원문, 문진 요약, 확인 항목, EMR 초안을 확인합니다.
* **환자 안내문:** 환자는 진료 후 안내문을 큰 글씨, 음성 재생, 종이 출력 등의 형태로 제공받습니다.

관련 문서:

- [루트 README](../README.md)
- [백엔드 README](../backend/README.md)
- [문서 모음](../docs/README.md)

---

## 1. 화면 구성

문진톡톡 프론트엔드는 다음과 같은 화면과 경로로 구성되어 있습니다.

| 화면 | URL | 사용자 | 역할 |
| --- | --- | --- | --- |
| 직원 접수 | `/staff` | 접수처 직원 | 환자 정보 입력, 세션 생성, 오늘 접수 목록, 직원 수동 문진 입력 |
| 환자 태블릿 대기열 | `/patient` | 환자·직원 | 문진 대기 환자 선택 |
| 환자 문진 | `/patient/:sessionId` | 환자 | 동의, 초진/재진 확인, 음성 문진, STT 결과 확인, 직원 도움 요청 |
| 의사 대기열 | `/doctor/queue` | 의료진 | 분석 중·문진 완료·우선 확인 환자 목록 |
| 의료진 원페이퍼 | `/doctor/:sessionId` | 의료진 | 증상, 원문, 문진 요약, 환자 질문, 확인 항목, EMR 초안 |
| 환자 안내문 | `/guide/:sessionId` | 환자·직원 | 진료 후 안내문 확인, 음성 재생, 종이 출력 |

세션이 없거나 선택되지 않은 상태에서는 환자 태블릿, 원페이퍼, 안내문 메뉴로의 접근이 비활성화됩니다.

가장 자연스러운 서비스 흐름을 확인하기 위한 데모 시연 순서는 다음과 같습니다.

```text
/staff
  -> 환자 접수와 문진 세션 생성

/patient
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

환자 문진 시 Q1부터 Q4까지의 답변을 모두 수집한 뒤 백엔드로 한 번에 제출합니다. 각 문항마다 LLM 분석을 기다리지 않으므로, 환자는 중간 대기 시간 없이 매끄럽게 문진을 이어나갈 수 있습니다.

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

문진 완료 이후의 원페이퍼 생성 작업은 백엔드에서 비동기로 별도 처리됩니다. 환자는 분석 완료를 기다리지 않고 화면을 종료할 수 있으며, 의료진은 화면에서 '분석 중(analysis_pending)' 상태를 확인한 후 완료 시 원페이퍼에 접근하여 AI 재검토나 수동 확인을 진행할 수 있습니다.

```text
의료진 화면
  -> analysis_pending 상태 표시
  -> 분석 완료 후 원페이퍼 접근
  -> 필요 시 AI 재검토 또는 수동 확인
```

---

## 3. 음성 문진 UX와 STT 처리

환자는 화면의 큰 마이크 버튼을 눌러 답변을 녹음하고, 텍스트로 변환된 문장을 확인한 뒤 다음 질문으로 넘어갑니다. 인식 결과가 부정확할 경우 다시 녹음하거나 직접 텍스트를 수정할 수 있도록 설계했습니다.

| 파일 | 역할 |
| --- | --- |
| `src/hooks/useStreamingTranscribe.js` | 마이크 권한, 녹음 상태, 실시간 전사 연결 |
| `src/services/transcribeStreaming.js` | Amazon Transcribe Streaming websocket 처리 |
| `public/audio-worklets/pcm16-processor.js` | 브라우저 마이크 입력을 PCM 16-bit stream으로 변환 |
| `src/components/patient/VoiceScreen.jsx` | 환자 음성 입력 화면 |
| `src/components/patient/ConfirmTranscriptScreen.jsx` | 전사 결과 확인·수정 화면 |

음성 원본 파일은 서버에 별도로 저장되지 않습니다. 브라우저가 Transcribe Streaming으로 음성 스트림을 직접 전송하며, 환자가 최종 확인을 마친 텍스트 데이터만 백엔드로 전달됩니다.

---

## 4. 백엔드 연동 구조

프론트엔드의 모든 API 호출은 `src/services/api/` 디렉터리 하위에서 역할별로 모듈화되어 관리됩니다.

| 파일 | 주요 역할 |
| --- | --- |
| `sessions.js` | 세션 생성, 세션 조회, 대기열 조회 |
| `transcripts.js` | Q1~Q4 답변 일괄 저장 |
| `doctor.js` | 원페이퍼 조회, 의사 답변 저장, 환자 안내문 조회 |
| `client.js` | 공통 fetch, 환자 세션 토큰, 직원/의사 로그인 토큰 처리 |

환자의 문진 답변은 문항별로 전송되지 않고 최종 단계에서 한 번에 묶어 제출됩니다. 분석 진행 상태는 의사 대기열과 원페이퍼 화면에만 노출되며, 환자 화면에는 불필요한 LLM 분석 실패나 지연 상태를 표시하지 않습니다.

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

(위 구조는 주요 로직과 컴포넌트가 분리된 프론트엔드의 디렉터리 배치를 보여줍니다.)

---

## 6. 화면별 구현 파일

각 화면과 흐름을 구성하는 주요 컴포넌트 목록입니다.

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
| `components/patient/PatientTabletQueueView.jsx` | 문진 대기 환자 선택 |
| `components/patient/PatientKioskView.jsx` | 세션 로딩과 환자 화면 진입 |
| `PatientFlow.jsx` | 환자 문진 상태 흐름 |
| `PrivacyConsentModal.jsx` | 서비스 이용 동의 |
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
| `DoctorOnePagerParts.jsx` | 매칭된 증상, 원문 quote, 원페이퍼 세부 섹션 |

### 환자 안내문

| 파일 | 역할 |
| --- | --- |
| `components/patient/PatientGuideScreen.jsx` | 안내문 표시, 말로 재생, 인쇄 |
| `PatientGuideScreen.css` | 안내문 화면과 인쇄 전용 스타일 |

---

## 7. 접근 제어 흐름

직원 화면과 의료진 화면은 공통된 접근 코드(Access Code) 기반의 로그인 모달을 통과해야 합니다.

```text
직원/의사 화면 접속
  -> 접근 코드 입력
  -> /auth/login
  -> 백엔드 세션 토큰 발급
  -> 이후 API 호출에 토큰 포함
```

반면 환자 화면은 각 문진 세션별로 고유하게 발급된 환자 토큰을 기반으로 라우팅됩니다. 또한, 직원 및 의사용 접근 코드는 보안을 위해 프론트엔드 코드 내에 하드코딩되지 않으며, 전적으로 백엔드의 환경 변수 로직을 통해 안전하게 검증됩니다.

---

## 8. 예외 상황 처리

사용자가 특정 오류 상황이나 흐름에 갇히는 것을 방지하기 위해, 예외 처리 화면과 복귀 액션을 명확히 분리하여 설계했습니다.

- 환자의 발화 중 위험 표현이 감지되면 시스템적인 오류 메시지 대신 '직원 도움 화면'으로 부드럽게 전환됩니다.
- 직원 도움 화면에서는 직원이 환자를 보조하여 문진을 마저 진행하거나 대기열로 취소 및 복귀하는 옵션을 제공합니다.
- 원페이퍼 생성이 완료되지 않은 세션을 조회할 경우, 의료진 화면에 '분석 중' 상태를 명시적으로 안내합니다.
- 원페이퍼 분석 파이프라인에서 오류가 발생한 경우, 의료진이 직접 수동으로 AI 재검토 로직을 트리거할 수 있습니다.
- 안내문이 아직 생성되지 않은 상태일 경우, 빈 화면이 아닌 '준비 상태'를 렌더링하여 혼란을 방지합니다.
- 인쇄(Print) 모드 시 화면의 내비게이션 등 불필요한 UI 요소는 숨기고, 안내문 본문만 깔끔하게 출력되도록 CSS의 Print Style을 엄격히 분리 적용했습니다.

---

## 9. 로컬 실행

필요 환경:

- Node.js 20.19 이상 또는 22.12 이상
- npm

### **실행 명령어 (Mac / Linux):**

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev -- --host 127.0.0.1 --port 5173
```

### **실행 명령어 (Windows PowerShell):**

PowerShell:

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev -- --host 127.0.0.1 --port 5173
```

`.env.local` 환경 변수 설정 예시:

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.<region>.amazonaws.com
```

(참고: 브라우저의 마이크 접근 권한은 HTTPS 환경이나 로컬호스트(127.0.0.1) 환경에서만 정상적으로 허용됩니다.)

---

## 10. 빌드와 배포

프론트엔드 프로덕션 빌드 명령어는 다음과 같습니다.

```bash
cd frontend
npm run build
```

AWS Amplify 배포 설정 기준:

| 항목 | 값 |
| --- | --- |
| 앱 루트 | `frontend` |
| 빌드 명령 | `npm run build` |
| 출력 디렉터리 | `dist` |
| 환경 변수 | `VITE_API_BASE_URL` |

SPA(Single Page Application)의 정상적인 라우팅 처리를 위해, Amplify의 Rewrite Rule을 아래와 같이 추가해야 합니다.

Plaintext

```text
/<*> -> /index.html (404 Rewrite)
```

---

## 11. 데모에서 확인할 사용자 경험

본 프론트엔드는 해커톤 데모 심사 과정에서 환자, 접수 직원, 의료진으로 이어지는 경험의 흐름이 끊기지 않도록 세밀하게 조정되었습니다.

- 환자는 별도의 앱 설치나 로그인 절차 없이 병원 접수처의 태블릿만으로 문진을 즉시 시작할 수 있습니다.
- Q1부터 Q4까지의 문항을 진행할 때, 백엔드 분석 응답을 기다릴 필요 없이 연속적으로 답변을 진행합니다.
- STT(음성 인식) 결과를 환자가 화면에서 직접 확인하며, 오타나 인식 오류 시 다시 말하거나 텍스트를 터치하여 수정할 수 있습니다.
- 객혈, 흉통 등 중증 위험 표현 감지 시 환자에게 복잡한 화면을 띄우지 않고, 즉시 직원을 호출하는 안전한 예외 흐름으로 전환됩니다.
- 의료진은 원페이퍼를 통해 환자의 원문 발화, 표준화된 증상명, 매칭 결과, 필수 확인 항목, EMR 초안까지 단일 화면에서 종합적으로 파악할 수 있습니다.
- 진료 후 발급되는 안내문은 고령 환자의 시력을 배려하여 큰 글씨로 렌더링되며, 즉각적인 음성 재생 기능 및 오프라인 종이 출력 레이아웃을 완벽하게 지원합니다.

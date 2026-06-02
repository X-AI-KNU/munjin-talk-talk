# 문진톡톡 MVP 프로젝트 구조

이 문서는 저장소를 처음 보는 개발자가 “어디를 봐야 하는지” 빠르게 파악하도록 만든 구조 설명서입니다.

현재 저장소는 실제 MVP 배포에 필요한 코드와 문서만 남기는 것을 목표로 정리되어 있습니다. 로컬 IR 실험 산출물, persona 평가 결과, 임시 output 파일은 배포 저장소에 포함하지 않는 것이 원칙입니다.

---

## 전체 구조

```text
munjin-talk-talk-mvp/
├── README.md
├── amplify.yml
├── frontend/
├── backend/
└── docs/
```

| 경로 | 역할 |
| --- | --- |
| `README.md` | 서비스와 저장소 전체 입구 문서 |
| `amplify.yml` | AWS Amplify 프론트엔드 빌드 설정 |
| `frontend/` | React + Vite 웹앱 |
| `backend/` | AWS 서버리스 백엔드 |
| `docs/` | 아키텍처, 파이프라인, 스키마, 배포 문서 |

---

## 프론트엔드 구조

```text
frontend/
├── README.md
├── package.json
├── package-lock.json
├── index.html
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

### `src/App.jsx`

최상위 라우터입니다.

담당:

- `/staff`
- `/patient/:sessionId`
- `/doctor/queue`
- `/doctor/:sessionId`
- `/guide/:sessionId`
- 상단 메뉴 활성화/비활성화
- 세션 목록 polling

### `components/staff/`

접수처 화면입니다.

```text
components/staff/
├── ReceptionView.jsx
├── ReceptionForm.jsx
├── ReceptionSessionList.jsx
├── ReceptionManualInput.jsx
├── ReceptionView.css
└── receptionUtils.js
```

| 파일 | 역할 |
| --- | --- |
| `ReceptionView.jsx` | 접수처 화면 controller |
| `ReceptionForm.jsx` | 환자 기본 정보와 초진/재진 입력 |
| `ReceptionSessionList.jsx` | 오늘 접수 목록과 이동 버튼 |
| `ReceptionManualInput.jsx` | 직원 직접 입력 |
| `receptionUtils.js` | 연락처 formatting, 나이 계산, 표시 helper |

### `components/patient/`

환자 태블릿과 안내문 화면입니다.

```text
components/patient/
├── PatientKioskView.jsx
├── PatientFlow.jsx
├── VisitTypeScreen.jsx
├── VoiceScreen.jsx
├── ConfirmTranscriptScreen.jsx
├── SafetyAlertScreen.jsx
├── StaffCallScreen.jsx
├── DoneScreen.jsx
├── PatientGuideScreen.jsx
├── PatientKioskView.css
└── PatientGuideScreen.css
```

| 파일 | 역할 |
| --- | --- |
| `PatientKioskView.jsx` | `sessionId`로 세션을 불러와 문진 시작 |
| `PatientFlow.jsx` | 환자 문진 state machine |
| `VoiceScreen.jsx` | 마이크, 질문, 실시간 텍스트 표시 |
| `ConfirmTranscriptScreen.jsx` | 환자가 인식 결과를 확인 |
| `SafetyAlertScreen.jsx` | 위험 표현 감지 시 직원 도움/문진 종료 |
| `StaffCallScreen.jsx` | 직원 호출 후 안심 화면 |
| `DoneScreen.jsx` | 문진 완료와 대기 안내 |
| `PatientGuideScreen.jsx` | 환자 안내문 출력 화면 |

### `components/doctor/`

의사 대기열과 원페이퍼 화면입니다.

```text
components/doctor/
├── DoctorQueueView.jsx
├── DoctorView.jsx
├── DoctorOnePager.jsx
├── DoctorOnePagerParts.jsx
├── DoctorAgendaPanel.jsx
├── DoctorOnePager.mocks.js
├── DoctorQueueView.css
├── DoctorView.css
├── DoctorOnePager.css
└── DoctorAgendaPanel.css
```

| 파일 | 역할 |
| --- | --- |
| `DoctorQueueView.jsx` | 의사 대기열 |
| `DoctorView.jsx` | 원페이퍼 session loading wrapper |
| `DoctorOnePager.jsx` | 원페이퍼 본문 |
| `DoctorOnePagerParts.jsx` | 증상 카드, chip, 보조 UI |
| `DoctorAgendaPanel.jsx` | 환자 질문, 의사 답변, 안내 강조사항 입력 |
| `DoctorOnePager.mocks.js` | UI 목업 데이터 |

### `hooks/`

```text
hooks/useStreamingTranscribe.js
```

Transcribe Streaming 상태를 React hook으로 감싼 파일입니다.

관리하는 상태:

- 녹음 중 여부
- partial/final transcript
- 에러
- 진행 시간
- stop 시 최종 텍스트 반환

### `services/`

```text
services/
├── api.js
├── demoSessions.js
├── transcribeStreaming.js
├── onepagerAdapter.js
├── onepagerBrief.js
└── api/
    ├── client.js
    ├── sessions.js
    ├── transcripts.js
    ├── doctor.js
    └── mockResponses.js
```

| 파일 | 역할 |
| --- | --- |
| `api.js` | 서비스 API re-export |
| `api/client.js` | API base URL, mock mode, 공통 session normalize |
| `api/sessions.js` | 세션 생성, 조회, 대기열 |
| `api/transcripts.js` | `/process-answer` 호출 |
| `api/doctor.js` | 원페이퍼, doctor response, guide API |
| `transcribeStreaming.js` | WebSocket STT streaming 구현 |
| `onepagerAdapter.js` | 백엔드 onepaper JSON을 UI용 shape으로 변환 |
| `onepagerBrief.js` | brief fallback helper |
| `demoSessions.js` | UI 목업용 localStorage 세션 |

---

## 백엔드 구조

```text
backend/
├── README.md
└── serverless/
    ├── README.md
    ├── template.yaml
    ├── samconfig.toml
    ├── s3-cors.json
    └── src/
```

현재 백엔드는 `serverless/`만 배포 대상입니다.

---

## 서버리스 백엔드 `src/`

```text
backend/serverless/src/
├── handler.py
├── common.py
├── settings.py
├── sessions.py
├── audio.py
├── llm.py
├── langchain_prompting.py
├── orchestration.py
├── pipeline_graph.py
├── pipeline_nodes.py
├── pipeline_state.py
├── pipeline_trace.py
├── extraction.py
├── extraction_prompts.py
├── extraction_schema.py
├── extraction_fallback.py
├── retrieval.py
├── retrieval_documents.py
├── retrieval_embeddings.py
├── retrieval_scoring.py
├── clinical_terms.py
├── onepager.py
├── onepager_sections.py
├── onepager_review.py
├── guide.py
├── utils.py
├── schemas/
└── data/
```

### API 계층

| 파일 | 역할 |
| --- | --- |
| `handler.py` | Lambda entrypoint. HTTP route 정의 |
| `common.py` | 예전 import 호환용 facade |
| `settings.py` | 환경 변수, AWS client, 모델 ID, 데이터 경로 |
| `utils.py` | 응답, 시간, 텍스트 정리 공통 함수 |

### 저장 계층

| 파일 | 역할 |
| --- | --- |
| `sessions.py` | DynamoDB session item 생성, 조회, update, queue list |

### 음성 인식

| 파일 | 역할 |
| --- | --- |
| `audio.py` | Transcribe Streaming presigned WebSocket URL 생성 |

환자 음성 파일 업로드 경로는 사용하지 않습니다. 프론트가 WebSocket으로 Transcribe에 직접 보냅니다.

### LLM 호출 계층

| 파일 | 역할 |
| --- | --- |
| `llm.py` | Bedrock Runtime 호출 |
| `langchain_prompting.py` | LangChain Core 기반 message 조립 |
| `extraction_prompts.py` | extraction prompt와 Q별 모델 라우팅 |

### LangGraph 파이프라인

| 파일 | 역할 |
| --- | --- |
| `orchestration.py` | `/process-answer` 진입점 |
| `pipeline_graph.py` | LangGraph 조립, 노드 연결, 조건 분기 |
| `pipeline_nodes.py` | 실제 노드 구현 |
| `pipeline_state.py` | 상태 타입과 그래프 메타데이터 |
| `pipeline_trace.py` | trace와 orchestration snapshot 저장 |

이렇게 나눈 이유:

- `pipeline_graph.py`를 읽으면 전체 흐름만 보이게 하기 위해
- `pipeline_nodes.py`를 읽으면 각 단계의 처리만 보이게 하기 위해
- `pipeline_state.py`에서 저장되는 상태 shape을 한눈에 보기 위해
- `pipeline_trace.py`에서 설명 가능성 관련 로직을 분리하기 위해

### Extraction과 검증

| 파일 | 역할 |
| --- | --- |
| `extraction.py` | Bedrock extraction 실행과 retry loop |
| `extraction_schema.py` | runtime 보강, quote grounding, 문항 단위 검증 |
| `extraction_fallback.py` | 명시적으로 허용된 경우에만 쓰는 fallback |
| `schemas/extraction.py` | Pydantic fixed schema |

### Hybrid IR

| 파일 | 역할 |
| --- | --- |
| `retrieval.py` | 증상 검색, 후보 채택, 결과 조립 |
| `retrieval_documents.py` | 원천 JSON을 검색 문서로 변환 |
| `retrieval_embeddings.py` | Titan embedding과 cache |
| `retrieval_scoring.py` | BM25, vector, label score |
| `clinical_terms.py` | 표준 증상, safety flag, 원천 데이터 loading |

### 원페이퍼와 안내문

| 파일 | 역할 |
| --- | --- |
| `onepager.py` | 원페이퍼 생성/저장 진입점 |
| `onepager_sections.py` | 환자 요약, 증상, agenda, transfer text 조립 |
| `onepager_review.py` | Nova Pro 기반 체크리스트와 EMR 문장 리뷰 |
| `guide.py` | 환자 안내문 생성 |
| `schemas/review.py` | 원페이퍼 review schema |
| `schemas/guide.py` | 환자 안내문 schema |

---

## 데이터 파일

```text
backend/serverless/src/data/
├── diseases_cleaned.json
├── symptom_index.json
└── symptom_embeddings_amazon.titan-embed-text-v2_0_512.json
```

| 파일 | 역할 |
| --- | --- |
| `diseases_cleaned.json` | 질환별 설명, 증상, 관련 정보 원천 데이터 |
| `symptom_index.json` | 표준 증상명, alias, slot id |
| `symptom_embeddings_*.json` | 검색 문서의 Titan embedding cache |

`symptom_retrieval_dataset`처럼 LLM이 가공한 검색 dataset은 runtime 필수 데이터로 사용하지 않습니다.

---

## 기능을 바꿀 때 볼 위치

| 하고 싶은 수정 | 우선 볼 파일 |
| --- | --- |
| API endpoint 추가 | `handler.py` |
| Lambda 환경 변수 추가 | `template.yaml`, `settings.py` |
| 질문 문구 수정 | `frontend/src/config/questions.js` |
| Bedrock prompt 수정 | `extraction_prompts.py`, `onepager_review.py`, `guide.py` |
| LLM JSON schema 수정 | `schemas/extraction.py`, `schemas/review.py`, `schemas/guide.py` |
| source_quote 검증 수정 | `schemas/extraction.py`, `extraction_schema.py` |
| LangGraph 노드 추가 | `pipeline_state.py`, `pipeline_nodes.py`, `pipeline_graph.py` |
| 증상 매칭 점수 조정 | `retrieval_scoring.py`, `settings.py` |
| 표준 증상 인덱스 수정 | `data/symptom_index.json` |
| 원페이퍼 화면 표시 수정 | `frontend/src/components/doctor/DoctorOnePager.jsx` |
| onepaper JSON 조립 수정 | `onepager.py`, `onepager_sections.py` |
| 환자 안내문 표시 수정 | `PatientGuideScreen.jsx`, `guide.py` |

---

## 저장소에 넣지 않는 것

아래는 Git에 올리지 않는 것이 원칙입니다.

- `frontend/node_modules/`
- `frontend/dist/`
- `backend/serverless/.aws-sam/`
- 로컬 persona 평가 데이터
- `outputs/`
- 실제 환자 음성 파일
- 실제 환자 개인정보가 담긴 JSON
- AWS credential
- `.env.local`

---

## 관련 문서

- [메인 README](../README.md)
- [프론트엔드 README](../frontend/README.md)
- [백엔드 README](../backend/README.md)
- [서버리스 백엔드 README](../backend/serverless/README.md)
- [LangGraph 파이프라인](LANGGRAPH_PIPELINE.md)
- [내부 JSON 스키마](DATA_SCHEMA.md)

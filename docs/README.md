# 문진톡톡 문서 모음

이 디렉터리는 문진톡톡 MVP의 구조, 파이프라인, 데이터 스키마, 배포 절차, 발표용 기술 설명을 담습니다. 메인 README가 프로젝트의 입구라면, `docs/`는 개발·검증·배포·평가를 위한 세부 문서 영역입니다.

---

## 문서 목록

| 문서 | 대상 독자 | 설명 |
| --- | --- | --- |
| [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | 개발자 | 저장소 구조, 프론트/백엔드 파일별 역할, 수정 위치 |
| [LANGGRAPH_PIPELINE.md](LANGGRAPH_PIPELINE.md) | 개발자, 평가자 | 환자 답변 1개가 LangGraph 노드에서 처리되는 과정 |
| [DATA_SCHEMA.md](DATA_SCHEMA.md) | 백엔드 개발자, 데이터 검토자 | DynamoDB item, LLM extraction, matched_slots, onepaper, guide JSON 구조 |
| [SECURITY_DATA_INVENTORY.md](SECURITY_DATA_INVENTORY.md) | 개발자, 보안 검토자 | DynamoDB/S3 하이브리드 저장 구조와 필드별 보안 처리 기준 |
| [MVP_SETUP.md](MVP_SETUP.md) | 개발자, 시연 준비자 | 로컬 실행, AWS 백엔드 연결, test 환경 점검 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 배포 담당자 | Amplify, SAM, DynamoDB, IAM, Bedrock, Transcribe 배포 절차 |
| [technical-guide.html](technical-guide.html) | 발표자, 평가자 | 브라우저에서 볼 수 있는 시각적 기술 설명 페이지 |
| [architecture.drawio](architecture.drawio) | 발표자, 설계 검토자 | draw.io 아키텍처 다이어그램 |
| [architecture.svg](architecture.svg) | 발표자, 문서 작성자 | SVG 아키텍처 이미지 |

---

## 권장 읽기 순서

처음 프로젝트를 검토할 때는 다음 순서를 권장합니다.

1. [메인 README](../README.md)
2. [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)
3. [LANGGRAPH_PIPELINE.md](LANGGRAPH_PIPELINE.md)
4. [DATA_SCHEMA.md](DATA_SCHEMA.md)
5. [SECURITY_DATA_INVENTORY.md](SECURITY_DATA_INVENTORY.md)
6. [MVP_SETUP.md](MVP_SETUP.md)
7. [DEPLOYMENT.md](DEPLOYMENT.md)
8. [technical-guide.html](technical-guide.html)

---

## 문서별 핵심 내용

### 메인 README

프로젝트를 처음 여는 사람이 전체 목적과 현재 구현 상태를 빠르게 파악하는 입구 문서입니다.

포함 내용:

- 서비스가 해결하려는 진료 전 문진 흐름
- 프론트엔드, 백엔드, AWS 서비스 구성
- LangChain/LangGraph, Pydantic validation, Hybrid IR의 역할
- DynamoDB/S3 하이브리드 저장 원칙
- 로컬 실행과 AWS 배포로 넘어가기 위한 기본 명령

### PROJECT_STRUCTURE.md

저장소를 유지보수하는 개발자를 위한 파일 지도입니다.

포함 내용:

- root, frontend, backend, docs 구조
- 화면별 React 컴포넌트 위치
- Lambda 모듈별 책임
- LangGraph 파이프라인 코드 분리 기준
- 기능 변경 시 확인할 파일

### LANGGRAPH_PIPELINE.md

환자 답변 1개가 서버에서 어떻게 처리되는지 설명합니다.

포함 내용:

- `input_transcript`부터 `response_payload`까지 노드 흐름
- LangGraph `StateGraph` 안에서 LangChain Runnable node가 실행되는 방식
- LLM extraction, schema validation, Hybrid IR, onepaper refresh 연결
- safety flag 분기
- LangChain과 LangGraph 역할 차이
- S3 trace와 DynamoDB artifact pointer 확인 위치

### DATA_SCHEMA.md

내부 JSON 구조를 설명합니다.

포함 내용:

- DynamoDB session item
- S3 `answers.redacted.json`
- LLM extraction schema
- Hybrid IR `matched_slots`
- `ir_trace`
- `onepager`
- S3 `patient_guide.redacted.json`
- Pydantic validation error 구조

### SECURITY_DATA_INVENTORY.md

DynamoDB/S3 하이브리드 보안 구조의 기준 문서입니다.

포함 내용:

- 필드별 기존 위치와 반영 후 저장 위치
- DynamoDB에 남기는 최소 세션 메타데이터
- S3 artifact로 이동하는 문진 산출물
- 저장하지 않는 직접식별정보
- Macie, Lifecycle, KMS 적용 위치

### MVP_SETUP.md

개발과 시연 환경을 준비하는 문서입니다.

포함 내용:

- 프론트 로컬 실행
- 로컬 프론트 실행과 AWS 백엔드 연결 모드
- SAM backend build
- test 환경 스모크 테스트
- 자주 발생하는 오류와 원인

### DEPLOYMENT.md

AWS 배포 담당자를 위한 절차 문서입니다.

포함 내용:

- DynamoDB 준비
- IAM role 준비
- Bedrock model access 확인
- SAM backend 배포
- Amplify GitHub 연결
- 환경 변수 설정
- SPA rewrite 설정
- 배포 후 점검

### technical-guide.html

발표와 회의 설명을 위한 HTML 문서입니다. 브라우저에서 열어 전체 구조, AI 파이프라인, JSON 구조, 배포 구조를 시각적으로 설명할 수 있습니다.

---

## 문서 작성 기준

문진톡톡 문서는 다음 기준을 따릅니다.

- 기본 서술 언어는 한국어입니다.
- API path, 환경 변수, model id, 파일명은 영어 원문을 유지합니다.
- 의료 판단처럼 해석될 수 있는 표현을 피합니다.
- LLM extraction, Hybrid IR, final review, guide generation의 책임을 분리해서 설명합니다.
- 환자 음성은 S3에 저장하지 않는다는 원칙을 명시합니다.
- 문진 원문, 원페이퍼, 안내문은 DynamoDB가 아니라 가명처리 S3 artifact로 저장한다는 원칙을 명시합니다.
- LLM extraction fallback이 제거되어 실패가 조용히 대체되지 않음을 명시합니다.
- 실제 계정 ID, 실제 API endpoint, 실제 bucket 이름, access key는 문서에 고정하지 않습니다.
- LangChain은 "LLM 호출 chain", LangGraph는 "문진 처리 흐름 graph"로 구분해서 설명합니다.
- DynamoDB에는 최소 상태와 S3 pointer만 저장하고, 문진 산출물은 S3 artifact에 저장한다는 현재 구현 상태를 기준으로 설명합니다.

---

## 기준 브랜치

이 문서들은 `test` 브랜치의 MVP 구조를 기준으로 작성되었습니다. `main` 브랜치 또는 팀 저장소에 반영할 때는 Amplify 배포 대상 브랜치, API Gateway endpoint, DynamoDB table name, SAM stack name을 다시 확인해야 합니다.

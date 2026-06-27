# 문진톡톡 문서 허브 (Documentation Hub)

문진톡톡 프로젝트의 기술 아키텍처, 데이터 흐름, 클라우드 배포 절차, 보안 설계를 총망라한 중앙 문서 색인입니다. 

해커톤 심사위원(평가자)은 본 서비스가 실질적인 임상 소통 병목을 어떤 인프라와 로직으로 해결했는지 검증할 수 있으며, 엔지니어(개발자)는 로컬 빌드부터 AWS 프로덕션 배포 및 유지보수에 필요한 표준 명세서를 확인할 수 있습니다.

---

## 🧭 평가자 추천 읽기 경로

심사위원 및 기술 검토자께서는 아래의 순서대로 문서를 확인하시면 프로젝트의 전체 맥락을 가장 빠르게 파악하실 수 있습니다.

| 순서 | 문서명 | 핵심 검증 포인트 |
| :---: | --- | --- |
| **1** | [루트 README](../README.md) | 우리가 푸는 문제의 배경, E2E 서비스 UX 흐름, 핵심 기술 스택, 보안 수준 |
| **2** | [평가 패키지 명세](../evaluation/README.md) | 공식 End-to-End 벤치마크 요약 지표 및 데이터 거버넌스(공개/비공개) 기준 |
| **3** | [LangGraph 문진 파이프라인](LANGGRAPH_PIPELINE.md) | 음성 답변이 구조화되어 의료진 원페이퍼와 환자 안내문으로 변환되는 추론 워크플로우 |
| **4** | [내부 데이터 스키마](DATA_SCHEMA.md) | DynamoDB 상태값, S3 아티팩트, 원페이퍼, 안내문, Trace의 엄격한 JSON 규격 |
| **5** | [보안 데이터 인벤토리](SECURITY_DATA_INVENTORY.md) | 개인식별정보(PII)와 건강정보가 어디에 격리되고 어떻게 파기되는지에 대한 생명주기 |
| **6** | [프로젝트 아키텍처 구조](PROJECT_STRUCTURE.md) | React SPA 프론트엔드와 AWS 서버리스 백엔드의 코드 및 책임 분리 구조 |

---

## 💻 개발자 추천 읽기 경로

프로젝트를 로컬 환경에 온보딩하거나 클라우드 인프라를 프로비저닝하려는 엔지니어는 다음 순서를 권장합니다.

| 순서 | 문서명 | 확인 및 실행할 작업 |
| :---: | --- | --- |
| **1** | [프론트엔드 README](../frontend/README.md) | 4개 사용자 화면 구성, 음성 스트리밍 STT 연동 UX, API 클라이언트 모듈화 구조 |
| **2** | [백엔드 README](../backend/README.md) | 비동기 문진 처리 파이프라인 원리, Hybrid IR 검색 아키텍처, 데이터 최소화 정책 |
| **3** | [서버리스 인프라 명세](../backend/serverless/README.md) | REST API 규격표, AWS SAM CLI 빌드/배포 명령어, 런타임 환경 변수 주입 목록 |
| **4** | [런타임 데이터 배치 가이드](../backend/serverless/src/data/README.md) | 저작권 보호로 Git에서 제외된 필수 IR 인덱스 파일 3종의 로컬 수동 배치 방법 |
| **5** | [AWS 클라우드 배포 가이드](DEPLOYMENT.md) | Amplify Hosting, API Gateway, Lambda, DynamoDB, S3 인프라 프로비저닝 절차 |

---

## 🗂️ 전체 문서 디렉터리 색인

| 파일 링크 | 분류 | 상세 정의 내용 |
| --- | :---: | --- |
| [DATA_SCHEMA.md](DATA_SCHEMA.md) | 규격서 | 문진 세션, 답변 수합본, 원페이퍼, 환자 안내문, 비식별 Trace 로그의 JSON 스키마 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 가이드 | AWS 프로덕션 환경의 인프라 구축 절차 및 권장 보안 방화벽 설정 |
| [LANGGRAPH_PIPELINE.md](LANGGRAPH_PIPELINE.md) | 명세서 | LangChain 및 LangGraph 기반의 상태 주도형 추론 노드/엣지 명세 |
| [MVP_SETUP.md](MVP_SETUP.md) | 체크리스트| 해커톤 현장 시연 직전 프론트엔드-백엔드 간 연결을 점검하는 스모크 테스트 가이드 |
| [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | 매뉴얼 | 전체 레포지토리 폴더 트리와 디렉터리별 핵심 소스 파일의 비즈니스 책임 |
| [SECURITY_DATA_INVENTORY.md](SECURITY_DATA_INVENTORY.md) | 정책서 | 저장소별 PII 데이터 격리 경계, 정규표현식 마스킹 규칙, 자동 파기 규칙 |

---

## 📊 평가 및 실험 브랜치 체계

본 프로젝트는 공식 발표 지표의 무결성을 지키기 위해 **공식 요약 브랜치**와 **탐색적 실험 브랜치**를 엄격히 분리했습니다.

| 브랜치 링크 | 역할 | 세부 내용 |
| --- | --- | --- |
| [main/evaluation](../evaluation/README.md) | **공식 기준(Master)** | 공식 End-to-End 성능 평가 스크립트, Held-out 벤치마크 결과, 요약 리포트 |
| [`eval/dialect-rag`](https://github.com/X-AI-KNU/munjin-talk-talk/tree/eval/dialect-rag) | 실험 데이터 | 강원 사투리 및 비표준 발화를 의학 용어로 해독할 때의 의미 보존율 튜닝 기록 |
| [`eval/hybrid-ir-pipeline`](https://github.com/X-AI-KNU/munjin-talk-talk/tree/eval/hybrid-ir-pipeline) | 실험 데이터 | BM25 + Vector 스코어링 퓨전 가중치 실험 및 Bedrock 추론 구간별 Latency 분석 |
| [`test/add-coverage`](https://github.com/X-AI-KNU/munjin-talk-talk/tree/test/add-coverage) | 테스트 인프라 | Pytest 모의 객체(Stub) 기반의 단위 테스트 및 AWS 클라우드 통합 테스트 셋 |

> 💡 **심사 안내:** 최종 피칭 자료에 기재된 임상 정합성 수치는 `main/evaluation`을 기준으로 도출되었습니다. 세부 파라미터 튜닝 과정은 각 독립 브랜치에서 확인하실 수 있습니다.

---

## ⚡ 현행 시스템 아키텍처 기준

현재 main 브랜치에 구현되어 작동 중인 문진톡톡 백엔드는 다음의 핵심 엔지니어링 원칙을 기반으로 실행됩니다.

* **Non-Blocking 일괄 처리:** 환자의 답변(Q1~Q4)은 개별 문항마다 LLM을 기다리지 않고 한 번에 수합되어 전송됩니다. 전송 직후 환자는 즉시 완료 화면으로 이동하며, 백그라운드 Lambda가 LangGraph 추론을 비동기로 수행합니다.
* **Zero-Storage 음성 보안:** 브라우저 마이크의 오디오 스트림은 AWS Transcribe로 직접 전송되며, 서버 스토리지에 음성 원본 파일(`.wav` 등)을 일절 남기지 않습니다.
* **PII 최소화 상태 저장:** DynamoDB에는 세션의 대기 순번과 상태값 중심의 경량 메타데이터만 남기며, 민감 텍스트가 포함된 모든 결과물은 가명 처리(Redaction) 후 S3에 보관합니다.
* **엄격한 스키마 통제:** LLM의 생성 텍스트는 Pydantic 고정 스키마 규격과 원문 대조(Source Quote Grounding)를 100% 통과해야만 최종 산출물에 반영됩니다.
* **확률 노출 차단:** 의사의 혼선을 막기 위해 LLM 내부의 임의 점수나 확률(probability) 값은 화면에 노출하지 않으며, "매칭됨", "우선 확인" 등 직관적인 임상 확인 상태만 원페이퍼에 렌더링합니다.

*(참고: `/process-answer` 엔드포인트는 과거 단일 문항 처리 방식의 레거시 및 프롬프트 회귀 테스트용 보조 API입니다. 현장 시연 및 서비스 분석 흐름은 `/process-answers`를 기준으로 합니다.)*

---

## 🔐 문서 작성 거버넌스 원칙

본 저장소의 모든 기술 문서는 다음의 규정을 준수하여 제정되었습니다.

1. **실행 코드 일치 원칙:** 현재 배포되어 작동 중인 소스 코드의 아키텍처와 100% 일치하는 내용만 명기합니다.
2. **보안 경로 격리:** 실제 환자의 발화 데이터 원본, 병원 백과 인덱스 마스터 파일, AWS Access Key, 로그인 접근 코드, 로컬 물리 드라이브 경로는 문서 본문에 일절 기재하지 않습니다.
3. **한계점의 투명한 공개:** AI 모델의 단독 성능 과장을 배제하며, 실패 시 인간 의료진(Human-in-the-Loop) 제어 대기열로 우회하는 fallback 경로를 항상 병기합니다.

# 📚 문진톡톡 · 문서 모음

이 디렉터리는 문진톡톡 MVP의 구조 · 파이프라인 · 데이터 스키마 · 배포 절차 · 발표용 기술 설명을 담습니다. 루트 README가 프로젝트의 입구라면, `docs/`는 개발 · 검증 · 배포 · 평가를 위한 세부 문서 영역입니다.

> 📍 [루트 README](../README.md) · [프론트엔드](../frontend/README.md) · [백엔드](../backend/README.md)

---

## 📄 문서 목록

| 문서 | 대상 | 설명 |
| --- | --- | --- |
| [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | 개발자 | 저장소 구조, 파일별 역할, 수정 위치 |
| [LANGGRAPH_PIPELINE.md](LANGGRAPH_PIPELINE.md) | 개발자·평가자 | 답변 1개가 LangGraph 노드에서 처리되는 과정 |
| [DATA_SCHEMA.md](DATA_SCHEMA.md) | 백엔드·데이터 검토자 | DynamoDB item, extraction, matched_slots, onepaper, guide JSON |
| [SECURITY_DATA_INVENTORY.md](SECURITY_DATA_INVENTORY.md) | 개발자·보안 검토자 | DynamoDB/S3 하이브리드 저장 구조와 필드별 보안 처리 |
| [MVP_SETUP.md](MVP_SETUP.md) | 개발자·시연 준비자 | 로컬 실행, AWS 백엔드 연결, 환경 점검 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 배포 담당자 | Amplify·SAM·DynamoDB·IAM·Bedrock·Transcribe 절차 |
| [technical-guide.html](technical-guide.html) | 발표자·평가자 | 브라우저용 시각적 기술 설명 페이지 |
| [rag-mentoring-brief.html](rag-mentoring-brief.html) | 멘토링·발표 | RAG/IR 멘토링 브리프 |
| [architecture.drawio](architecture.drawio) / [architecture.svg](architecture.svg) | 발표자·설계 검토자 | draw.io 다이어그램 / SVG 이미지 |
| munjin-talk-talk-mvp-code-guide.docx | 개발자 | 코드 가이드 (Word) |

---

## 🧭 권장 읽기 순서

1. [루트 README](../README.md)
2. [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)
3. [LANGGRAPH_PIPELINE.md](LANGGRAPH_PIPELINE.md)
4. [DATA_SCHEMA.md](DATA_SCHEMA.md)
5. [SECURITY_DATA_INVENTORY.md](SECURITY_DATA_INVENTORY.md)
6. [MVP_SETUP.md](MVP_SETUP.md)
7. [DEPLOYMENT.md](DEPLOYMENT.md)
8. [technical-guide.html](technical-guide.html)

---

## 📝 문서 작성 기준

- 기본 서술 언어는 한국어. API path · 환경 변수 · model id · 파일명은 영어 원문 유지.
- 의료 판단처럼 해석될 수 있는 표현을 피함.
- LLM extraction · Hybrid IR · final review · guide generation의 책임을 분리해 설명.
- 환자 음성은 S3에 저장하지 않는다는 원칙을 명시.
- 문진 원문·원페이퍼·안내문은 DynamoDB가 아니라 가명처리 S3 artifact로 저장한다는 원칙을 명시.
- LLM extraction fallback이 제거되어 실패가 조용히 대체되지 않음을 명시.
- 실제 계정 ID·API endpoint·bucket 이름·access key는 문서에 고정하지 않음.
- LangChain은 "LLM 호출 chain", LangGraph는 "문진 처리 흐름 graph"로 구분.

---

## 🔧 기준 구현

이 문서들은 현재 저장소의 서버리스 MVP 구조를 기준으로 작성되었습니다. 다른 AWS 계정 · Amplify 앱 · 스테이징 환경으로 배포할 때는 대상 브랜치, API Gateway endpoint, DynamoDB table name, SAM stack name, artifact bucket 이름을 환경에 맞게 다시 확인해야 합니다.

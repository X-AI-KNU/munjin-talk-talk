# 문진톡톡 문서 모음

이 폴더는 문진톡톡 MVP를 설명하는 세부 문서 모음입니다.

메인 README가 서비스와 저장소의 입구라면, 이 폴더의 문서는 실제 개발, 배포, 디버깅, 발표 준비에 필요한 내용을 더 깊게 설명합니다.

---

## 문서 읽는 순서

처음 프로젝트에 들어온 사람은 아래 순서로 읽는 것을 추천합니다.

| 순서 | 문서 | 목적 |
| --- | --- | --- |
| 1 | [메인 README](../README.md) | 서비스 목적과 전체 구조 이해 |
| 2 | [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | 파일별 역할 파악 |
| 3 | [LANGGRAPH_PIPELINE.md](LANGGRAPH_PIPELINE.md) | 환자 답변 1개가 처리되는 과정 이해 |
| 4 | [DATA_SCHEMA.md](DATA_SCHEMA.md) | DynamoDB와 LLM JSON 구조 이해 |
| 5 | [MVP_SETUP.md](MVP_SETUP.md) | 로컬 실행과 test 환경 확인 |
| 6 | [DEPLOYMENT.md](DEPLOYMENT.md) | AWS Amplify/SAM 배포 |
| 7 | [technical-guide.html](technical-guide.html) | 발표, 공유, 시각 자료용 설명 |

---

## 문서별 상세 설명

### `PROJECT_STRUCTURE.md`

개발자가 가장 자주 보는 문서입니다.

알 수 있는 것:

- 저장소 전체 구조
- 프론트 화면별 파일
- 백엔드 모듈별 역할
- LangGraph 파이프라인 파일 분리 기준
- 어떤 기능을 바꿀 때 어느 파일을 봐야 하는지

### `LANGGRAPH_PIPELINE.md`

환자 답변 하나가 백엔드에서 어떻게 처리되는지 설명합니다.

알 수 있는 것:

- `input_transcript`부터 `response_payload`까지 노드 흐름
- LLM 실패 시 retry와 safety branch
- LangChain과 LangGraph의 차이
- DynamoDB trace 확인 위치
- LLM과 IR의 책임 경계

### `DATA_SCHEMA.md`

내부 JSON을 설명합니다.

알 수 있는 것:

- DynamoDB session item
- `responses.Qx`
- LLM extraction JSON
- Hybrid IR `matched_slots`
- onepaper JSON
- patient guide JSON
- Pydantic validation error

### `MVP_SETUP.md`

로컬 개발자와 발표 시연자가 보는 실행 문서입니다.

알 수 있는 것:

- 로컬 프론트 실행
- AWS 백엔드 연결
- test 브랜치 확인
- 스모크 테스트 순서
- 자주 나는 오류와 원인

### `DEPLOYMENT.md`

AWS 콘솔과 CLI로 배포할 때 보는 문서입니다.

알 수 있는 것:

- Amplify GitHub 연결
- Amplify 환경 변수
- SPA rewrite
- SAM backend 배포
- DynamoDB, IAM, Bedrock, Transcribe 준비
- 배포 후 확인 절차

### `technical-guide.html`

발표 또는 팀 공유용 HTML 설명 페이지입니다.

브라우저에서 열어 전체 구조와 파이프라인을 시각적으로 설명할 때 사용합니다.

---

## 문서 작성 원칙

- 가능하면 한글로 작성합니다.
- API path, model id, 환경 변수, 파일명 같은 고유명사는 영어를 유지합니다.
- 의료 판단처럼 오해될 수 있는 표현은 피합니다.
- “LLM이 한다”와 “IR이 한다”를 분리해서 씁니다.
- 환자 음성은 S3에 저장하지 않는다는 원칙을 반복해서 명시합니다.
- rule-based fallback은 기본 운영 경로가 아니라는 점을 명확히 씁니다.

---

## 현재 문서와 코드의 기준 브랜치

이 문서는 `test` 브랜치의 현재 MVP 구조를 기준으로 작성되었습니다.

`main` 브랜치 또는 팀 저장소에 반영할 때는 AWS Amplify 배포 대상 브랜치와 API endpoint 환경 변수를 반드시 다시 확인해야 합니다.

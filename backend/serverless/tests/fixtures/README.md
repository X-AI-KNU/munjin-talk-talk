# 테스트 fixture 안내

이 폴더는 백엔드 회귀 검증에 사용하는 기준 fixture를 보관합니다. fixture는 실제 환자 데이터나 의료 정답 데이터가 아니라, 코드 변경으로 프롬프트 구조가 의도치 않게 흔들리지 않았는지 확인하기 위한 기준값입니다.

## 이 브랜치에서의 역할

`eval/dialect-rag` 브랜치는 사투리 RAG 의미 보존 평가를 보여주는 브랜치입니다. 이 fixture 폴더는 평가 데이터 자체를 담는 위치가 아니라, 백엔드 프롬프트 회귀 테스트가 어떤 기준으로 관리되는지 보여주는 보조 문서입니다.

사투리 RAG 평가 데이터는 아래 위치를 봅니다.

```text
evaluation/dialect_rag/data/
evaluation/dialect_rag/reports/
```

fixture는 평가 지표를 만드는 파일이 아닙니다. 발표나 제출에서 이 폴더는 "프롬프트 구조가 갑자기 바뀌지 않도록 회귀 검증을 둔 부분"으로 설명하면 됩니다.

## 검증 대상

| 파일 | 목적 |
| --- | --- |
| `prompts_golden.json` | extraction, review, guide 등 핵심 프롬프트의 구조 회귀 검증 |

관련 테스트:

```text
backend/serverless/tests/test_prompts_golden.py
```

## 무엇을 확인하나

`prompts_golden.json`은 Bedrock 호출 결과를 평가하지 않습니다. 대신 Bedrock에 전달되기 전의 프롬프트 본문이 안전 규칙, JSON schema 요구사항, source quote grounding 지시, 금지 필드 규칙을 계속 포함하는지 확인합니다.

예를 들어 다음 규칙들이 의도 없이 빠지면 회귀 테스트가 잡아야 합니다.

- 진단이나 처방을 만들지 말 것
- `source_quote`는 환자 원문에서 그대로 복사할 것
- `score`, `confidence`, `probability` 같은 임의 수치 필드를 만들지 말 것
- Q4에서 "궁금한 것 없음" 같은 답변을 환자 질문으로 만들지 말 것
- 사투리/구어체 힌트를 쓰더라도 원문에 없는 증상이나 사실을 추가하지 말 것

## 관리 원칙

- fixture에는 실제 환자 정보나 민감정보를 넣지 않습니다.
- 평가 데이터셋의 정답 문장을 그대로 복사해 넣지 않습니다.
- 프롬프트 변경이 의도된 경우에만 fixture를 함께 갱신합니다.
- AWS 호출이 필요한 부분은 stub으로 대체해 로컬 환경 차이 때문에 테스트가 흔들리지 않게 합니다.
- fixture 변경은 "프롬프트 정책 변경"으로 보고, 단순 snapshot 갱신처럼 처리하지 않습니다.

이 fixture는 의료적 정답을 평가하는 파일이 아니라, 프롬프트 구조가 갑자기 바뀌지 않았는지 확인하는 안전장치입니다.

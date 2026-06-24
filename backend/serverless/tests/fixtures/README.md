# 테스트 fixture 안내

이 폴더는 백엔드 회귀 검증에 사용하는 기준 fixture를 보관합니다.

현재 핵심 파일은 `prompts_golden.json`입니다. 이 파일은 Bedrock에 전달되는 주요 프롬프트 구조가 의도와 다르게 바뀌지 않았는지 확인하기 위한 기준값입니다.

---

## 검증 대상

| 파일 | 목적 |
| --- | --- |
| `prompts_golden.json` | extraction, review, guide 등 핵심 프롬프트의 회귀 검증 |

관련 테스트:

```text
backend/serverless/tests/test_prompts_golden.py
```

---

## 관리 원칙

- fixture에는 실제 환자 정보나 민감정보를 넣지 않습니다.
- 평가 데이터셋의 정답 문장을 그대로 복사해 넣지 않습니다.
- 프롬프트 변경이 의도된 경우에만 fixture를 함께 갱신합니다.
- AWS 호출이 필요한 부분은 stub으로 대체해 로컬 환경 차이 때문에 테스트가 흔들리지 않게 합니다.

이 fixture는 의료적 정답을 평가하는 파일이 아니라, 프롬프트 구조가 갑자기 바뀌지 않았는지 확인하는 안전장치입니다.

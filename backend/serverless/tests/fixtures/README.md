# 프롬프트 회귀 검증 기준

이 폴더의 `prompts_golden.json`은 핵심 프롬프트가 의도와 다르게 바뀌지 않았는지 확인하기 위한 기준 파일입니다. 관련 검증 코드는 `backend/serverless/tests/test_prompts_golden.py`입니다.

## 검증 대상

| 항목 | 목적 |
| --- | --- |
| Extraction prompt | 환자 발화 표준화, 의미 span 추출, status 태깅 지침이 유지되는지 확인 |
| Onepaper review prompt | 의료진 확인 항목과 EMR 초안 생성 지침이 유지되는지 확인 |

## 관리 원칙

- 프롬프트 변경은 서비스 출력 품질에 직접 영향을 주므로, 의도한 변경일 때만 기준 파일을 함께 갱신합니다.
- 기준 파일 갱신 시 기준 커밋 해시를 `prompts_golden.json` 내부에 함께 기록합니다.
- AWS 호출이 필요한 부분은 stub으로 대체해 로컬 환경 차이 때문에 검증 결과가 흔들리지 않게 관리합니다.

# 🧪 Prompt Golden Fixtures

이 폴더의 `prompts_golden.json`은 특정 커밋 시점의 프롬프트 출력을 기준으로 만든 회귀 테스트 fixture입니다 (기준 커밋 해시는 fixture 내부에 기록).

> 📍 [serverless README](../../README.md) · 관련 테스트: `tests/test_prompts_golden.py`

기본 문항 경로에서 extraction prompt와 onepager review prompt가 **임의로 바뀌면 안 됩니다.** 프롬프트를 의도적으로 변경할 때는 먼저 팀 승인을 받고, 변경 이유와 영향 범위를 문서화한 뒤 fixture를 재생성합니다.

## 재생성 절차

> ℹ️ 현재 저장소에는 재생성용 실행 스크립트(`regenerate_prompts_golden.py`)를 **별도로 두지 않습니다.** fixture는 `test_prompts_golden.py`가 검증하는 것과 동일한 prompt 빌드 로직으로 수동 생성합니다.

재생성이 필요하면 다음 기준으로 진행합니다.

- `settings`·`utils`·`llm`·`schemas.review` 같은 AWS 의존 모듈은 fixture 생성용 stub으로 대체해 로컬 환경 차이에 흔들리지 않게 합니다.
- extraction/onepager review prompt 빌더를 호출해 얻은 출력을 `prompts_golden.json`에 갱신하고, 기준 커밋 해시를 fixture 내부에 함께 기록합니다.
- 별도 실행 스크립트를 추가하는 경우 이 README의 절차도 같이 업데이트합니다.

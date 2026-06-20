# 🧪 Prompt Golden Fixtures

이 폴더의 `prompts_golden.json`은 특정 커밋 시점의 프롬프트 출력을 기준으로 만든 회귀 테스트 fixture입니다 (기준 커밋 해시는 fixture 내부에 기록).

> 📍 [serverless README](../../README.md) · 관련 테스트: `tests/test_prompts_golden.py`

기본 문항 경로에서 extraction prompt와 onepager review prompt가 **임의로 바뀌면 안 됩니다.** 프롬프트를 의도적으로 변경할 때는 먼저 팀 승인을 받고, 변경 이유와 영향 범위를 문서화한 뒤 fixture를 재생성합니다.

## 재생성 절차

저장소 루트에서 fixture 생성 로직을 실행합니다.

```bash
cd <repo-root>
python backend/serverless/tests/fixtures/regenerate_prompts_golden.py
```

> ℹ️ 현재 저장소에는 재생성 스크립트를 별도 실행 파일로 두지 않고, 작업 지시문에 명시된 절차와 동일한 로직으로 fixture를 생성했습니다. 새 스크립트를 추가할 경우 `settings`·`utils`·`llm`·`schemas.review` 같은 AWS 의존 모듈은 fixture 생성용 stub으로 대체해야 로컬 환경 차이에 흔들리지 않습니다.

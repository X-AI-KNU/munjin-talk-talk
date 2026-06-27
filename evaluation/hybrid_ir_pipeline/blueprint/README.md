# Train 100 v2 Blueprint

이 폴더는 `train_100_v2`를 만들기 위한 row-level blueprint입니다. 실제 환자 발화 텍스트가 아니라, 렌더러가 생성해야 할 증상 조합, 질문 유형, 사투리 source layer, 난이도 조건을 정의합니다.

## 목적

blueprint는 LLM이 문장을 렌더링하기 전에 "어떤 종류의 케이스 100개를 만들 것인가"를 고정하는 설계도입니다. 이렇게 분리한 이유는 평가 데이터가 특정 문장 표현에만 치우치지 않도록 방문 유형, 질문, 증상군, 방언 layer, 상태 패턴을 먼저 잠그기 위해서입니다.

이 단계에는 실제 환자 문장이나 Bedrock 출력문이 들어가지 않습니다. 데이터 오염을 막기 위해 증상 조합과 생성 조건만 남깁니다.

## 파일

- `distribution_plan.json`: 고정 분포와 생성 규칙입니다.
- `case_blueprint.schema.json`: row schema입니다.
- `case_blueprint.jsonl`: 100개 planned row입니다.
- `quality_gate_report.json`: blueprint 검증 요약입니다.
- `build_blueprint.py`: blueprint 재생성 스크립트입니다.

## 고정 분포

`distribution_plan.json` 기준입니다.

| 항목 | 분포 |
| --- | --- |
| 방문/질문 | 초진 Q1 50개, 재진 Q3 50개 |
| 언어 스타일 | 표준어 50개, 강원체 50개 |
| 방언 source layer | rag_pack_anchored 10개, clinical_colloquial 25개, light_dialect_style 15개, none 50개 |
| 표현 정책 | direct_common 35개, lay_paraphrase 45개, technical_hidden 20개 |
| 상태 패턴 | active_current 45개, recurrent_or_persistent 25개, improved_or_resolved 10개, denied_negative_context 15개, mixed_context 5개 |

## 범위

허용된 질문 대상은 초진 Q1 주호소와 재진 Q3 경과/재발 답변입니다. Q2 발생 시점, Q4 의사에게 물어볼 질문, 약물/영양제 질문은 이 데이터셋에서 제외합니다.

## 품질 기준

`quality_gate_report.json`의 `passed`가 `true`여야 렌더링 단계로 넘깁니다. 특히 `rag_pack_anchored` 행은 실제 방언 pack에서 기대 anchor를 검색할 수 있어야 하며, 강원체라고 표시한 모든 행을 사투리 RAG 근거가 있는 행으로 주장하지 않습니다.

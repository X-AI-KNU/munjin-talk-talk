# 문진톡톡 Q1 파이프라인 테스트 — gold leakage 분리 버전

## 파일

- `aws_q1_pipeline_test_input_only.ipynb`: 수정 노트북
- `data/q1_gangwon_test_cases_100.json`: Q1 테스트셋
- `data/symptom_index.json`: reverse index 원본
- `outputs/`: 실행 결과 저장

## 핵심 수정

기존 노트북의 로컬 모드는 gold span/normalized_candidates를 사용할 수 있어 end-to-end 성능으로 해석하면 안 됩니다.
이 버전은 모드를 분리했습니다.

- `LOCAL_INPUT_ONLY`: input만 사용. gold leakage 없음. 로컬 smoke test.
- `ORACLE_RETRIEVAL_COMPONENT`: gold span/normalization 사용. Stage 3 retrieval component test 전용.
- `AWS_E2E`: input만 사용. Bedrock/Titan/Verifier 실제 테스트.

## 권장 순서

1. `PIPELINE_MODE="LOCAL_INPUT_ONLY"`, `MAX_CASES=10`으로 실행
2. `PIPELINE_MODE="ORACLE_RETRIEVAL_COMPONENT"`으로 Stage 3 retrieval 함수 확인
3. `PIPELINE_MODE="AWS_E2E"`, `USE_AWS_STAGE2=True`로 3개 케이스부터 실행
4. Titan embedding, verifier를 하나씩 켬

주의: `candidate_symptom_matches`는 질환 후보가 아니라 87개 표준 증상 vocabulary 중 retrieval shortlist입니다.
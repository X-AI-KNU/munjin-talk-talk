# 문진톡톡 Hybrid IR 파이프라인 평가팩

이 폴더는 문진톡톡의 증상 후보 검색, 사투리 RAG 힌트, Bedrock 기반 문진 분석 파이프라인을 분리해서 점검한 평가 자료입니다. 공식 서비스 코드 브랜치가 아니라, 성능 테스트와 재현 근거를 정리한 공간입니다.

## 평가 목적

문진톡톡의 원페이퍼에는 LLM이 자유롭게 만든 증상명이 그대로 올라가면 안 됩니다. 환자 발화에서 추출된 표현은 표준 증상 후보 검색과 검증을 거쳐야 하며, 부정 증상이나 이미 나아진 증상은 active symptom으로 잘못 올라가지 않아야 합니다.

이 평가팩은 다음을 분리해서 봅니다.

- 정답 표준 증상이 후보 리스트에 들어오는지
- 사투리 RAG 힌트가 실제 강원 방언 pack anchor에서 검색되는지
- Bedrock extraction과 LangGraph pipeline을 거친 최종 `matched_slots`가 기준 증상과 맞는지
- 스키마 실패, source quote grounding 실패, 부정 증상 오탐이 있는지

## 파일 구성

```text
evaluation/hybrid_ir_pipeline/
├── README.md
├── run_separated_evaluation.py
├── blueprint/
│   ├── README.md
│   ├── case_blueprint.jsonl
│   ├── case_blueprint.schema.json
│   ├── distribution_plan.json
│   └── quality_gate_report.json
├── design/
│   ├── README.md
│   ├── evaluation_tracks.md
│   └── train_100_v2_blueprint_draft.md
├── train_100_v2/
│   ├── README.md
│   ├── train_100_v2.jsonl
│   ├── quality_gate_report.json
│   ├── artifact_build_report.json
│   ├── build_artifacts.py
│   └── render_train.py
└── reports/
    ├── metrics_summary.json
    ├── separated_evaluation_report.md
    └── pipeline_error_analysis.md
```

| 위치 | 역할 |
| --- | --- |
| `blueprint/` | 렌더링 전 100개 케이스의 분포와 제약 조건 |
| `train_100_v2/` | 렌더링된 synthetic 환자 발화와 train-derived runtime artifact 생성 도구 |
| `reports/` | Track A/B/C 평가 결과와 오류 분석 |
| `run_separated_evaluation.py` | 세 평가 트랙을 한 번에 실행하는 스크립트 |
| `design/` | train/test 분리, 평가 트랙, 데이터 오염 방지 원칙 |

## 데이터셋 개요

현재 평가는 `train_100_v2/train_100_v2.jsonl`의 100개 synthetic 문진 발화를 사용합니다.

`blueprint/quality_gate_report.json`과 `train_100_v2/quality_gate_report.json` 기준 분포는 다음과 같습니다.

| 항목 | 분포 |
| --- | --- |
| 방문/질문 | 초진 Q1 50개, 재진 Q3 50개 |
| 언어 스타일 | 표준어 50개, 강원체 50개 |
| 방언 source layer | none 50개, clinical_colloquial 25개, rag_pack_anchored 10개, light_dialect_style 15개 |
| 증상군 | upper airway 18, cough/sputum/lower airway 20, dyspnea/chest/urgent 18, systemic course 14, ENT/swallow/eye/voice 10, cardio/neuro/edema 10, GI confounders 10 |
| 상태 패턴 | active_current 45, recurrent_or_persistent 25, improved_or_resolved 10, denied_negative_context 15, mixed_context 5 |

이 데이터셋은 학습/점검용입니다. 최종 held-out 성능은 별도 고정 테스트셋에서 첫 실행 리포트를 저장한 뒤에만 주장해야 합니다.

## 평가 트랙

### Track A: Offline IR

Bedrock을 호출하지 않습니다. 로컬 alias retrieval, BM25 symptom reference retrieval, combined candidate ranking을 실행합니다.

확인하는 질문:

- 정답 증상이 top-k 후보 안에 들어오는가?
- 후보 검색 단계에서 이미 정답이 빠지는가?
- alias와 BM25를 합쳤을 때 후보 검색이 보완되는가?

주요 지표:

- `recall@1`, `recall@3`, `recall@5`, `recall@10`
- `all_gold_hit@5`
- `negative_in_top5_rate_among_negative_rows`

주의: Track A는 후보 검색 품질입니다. 최종 모델 F1이나 원페이퍼 품질로 직접 말하면 안 됩니다.

### Track B: Dialect RAG Sanity

Bedrock을 호출하지 않습니다. 현재 강원 방언팩을 대상으로 `rag_pack_anchored` 행에서 기대 방언 힌트가 검색되는지 확인합니다.

확인하는 질문:

- 방언 pack에 anchor가 있는 10개 행에서 기대 힌트가 실제로 검색되는가?
- anchor가 없는 강원체 행에서 불필요한 방언 힌트가 과하게 검색되는가?

주요 지표:

- `rag_pack_anchor_recall`
- `non_anchor_hint_rate`

### Track C: Pipeline Integration

Bedrock을 호출합니다. 실제 `run_answer_pipeline` 또는 동기 파이프라인을 사용하되, S3/DynamoDB 저장은 monkeypatch해서 평가 중 원격 저장소에 쓰지 않습니다.

확인하는 질문:

- LangGraph/Bedrock extraction이 끝까지 schema-valid 결과를 내는가?
- RAG context node가 프롬프트 흐름에 포함되는가?
- source quote가 원문에 근거하는가?
- Hybrid IR linking 이후 active symptom `matched_slots`가 기준 증상과 맞는가?
- 부정 증상이 active symptom으로 잘못 올라가지 않는가?

주요 지표:

- micro precision, recall, F1
- schema/runtime failures
- source quote grounding rate
- RAG context node seen rate
- negative false-positive rate

## 현재 요약 지표

`reports/metrics_summary.json` 기준입니다.

| 지표 | 값 |
| --- | ---: |
| generated_at | `2026-06-26T06:10:14.124246+00:00` |
| dataset rows | 100 |
| held_out_test | false |
| Track A combined recall@1 | 0.8198 |
| Track A combined recall@3 | 1.0000 |
| Track A combined recall@5 | 1.0000 |
| Track A combined recall@10 | 1.0000 |
| Track A all_gold_hit@5 | 1.0000 |
| Track B rag-pack anchored recall | 1.0000 |
| Track B non-anchor hint rate | 0.0000 |
| Track C completed rows | 100/100 |
| Track C precision | 1.0000 |
| Track C recall | 0.9279 |
| Track C F1 | 0.9626 |
| Track C schema/runtime failures | 0 |
| Track C source quote grounding rate | 1.0000 |
| Track C RAG context node seen rate | 1.0000 |
| Track C negative false-positive rate | 0.0000 |

## 오류 분석 요약

`reports/pipeline_error_analysis.md` 기준으로 최종 남은 mismatch는 8개입니다. 모두 false negative이며, `progress_improved/status=없음` 계열입니다.

예시:

- `train_v2_055`: 호흡곤란이 조금 나아졌지만 여전히 힘들 때가 있음
- `train_v2_064`: 열이 나아진 것 같음
- `train_v2_070`: 피로감은 덜하지만 근육통은 현재 남음
- `train_v2_076`: 목소리 변화가 조금 나아짐

현재 제품 정책은 `progress_improved`와 `symptom_absent`를 active symptom card와 IR `matched_slots`에 올리지 않습니다. 이 항목들은 follow-up context나 clinical clue로 보존하는 쪽에 가깝습니다. 따라서 남은 recall 손실은 후보 검색 실패가 아니라 scoring-policy mismatch로 해석해야 합니다.

## 실행 준비

프로젝트 루트에서 실행한다고 가정합니다.

```bash
cd munjin-talk-talk

export AWS_PROFILE=<your-profile>
export AWS_REGION=ap-northeast-2
export AWS_DEFAULT_REGION=ap-northeast-2
```

Windows PowerShell:

```powershell
$env:AWS_PROFILE="<your-profile>"
$env:AWS_REGION="ap-northeast-2"
$env:AWS_DEFAULT_REGION="ap-northeast-2"
```

Track C는 Bedrock을 호출하므로 AWS 권한과 비용이 필요합니다. Track A/B만 보는 코드 경로는 Bedrock을 쓰지 않지만, 현재 통합 스크립트는 Track C까지 함께 실행하는 구조입니다.

## 평가 실행

```bash
python evaluation/hybrid_ir_pipeline/run_separated_evaluation.py \
  --dataset evaluation/hybrid_ir_pipeline/train_100_v2/train_100_v2.jsonl \
  --out-dir evaluation/hybrid_ir_pipeline/reports/run_latest
```

새 실행 결과의 상세 JSON 로그는 커밋하지 않고, 제출이나 발표에는 아래 세 파일만 고정 결과로 사용합니다.

- `reports/metrics_summary.json`
- `reports/separated_evaluation_report.md`
- `reports/pipeline_error_analysis.md`

## Git 관리 기준

커밋 권장:

- 평가 설계 문서
- blueprint, train_100_v2 데이터와 quality gate report
- 제출용 summary/report/error analysis
- 평가 스크립트

커밋 비권장:

- Bedrock raw response trace
- 실행별 임시 output directory
- S3/DynamoDB persistence 결과물
- held-out test 실패를 보고 튜닝한 뒤 덮어쓴 first-pass report

## 해석 시 주의

현재 수치는 `train_100_v2` 기반 파이프라인 점검 결과입니다. 최종 모델 성능 또는 held-out 성능으로 표현하면 안 됩니다.

발표나 제출에서는 다음처럼 말하는 것이 안전합니다.

```text
문진톡톡은 후보 검색, 사투리 RAG 힌트, Bedrock 기반 추출/연결 파이프라인을 분리해 평가했다.
train_100_v2 점검에서 Offline IR combined recall@5는 1.0,
Pipeline Integration F1은 0.9626이었고,
남은 mismatch는 제품 정책상 active symptom으로 올리지 않는 개선/해소 계열에서 발생했다.
```

최종 공개 성능 주장은 별도 고정 테스트셋을 만든 뒤 첫 실행 리포트를 저장하고, 그 이후 튜닝과 분리해서 관리해야 합니다.

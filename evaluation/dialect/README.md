# 문진톡톡 사투리→표준어 변환 평가

이 폴더는 `backend/serverless/src/dialect_normalization.py`의 `normalize_dialect_text()`를 AWS Bedrock 환경에서 실행해, 사투리/구어체 문진 텍스트가 표준어 보조 문장으로 얼마나 잘 바뀌는지 평가하기 위한 자료입니다.

## 파일

```text
evaluation/dialect/
├── run_dialect_norm_eval.py
└── data/
    └── dialect_norm_eval_200.jsonl
```

`dialect_norm_eval_200.jsonl`은 업로드된 `munjin_eval.json`의 100개 문진 문장을 기반으로 만든 synthetic regression set입니다. 원본 100개 문장을 표준어 정답 문장으로 확장하고, 일부 문장은 사투리/구어체 변형을 추가해 총 200개 case로 구성했습니다.

## 데이터 형식

```json
{
  "case_id": "dialect_norm_001",
  "dialect_text": "가만있어도 숨이 차서 데우 힘들어요.",
  "gold_standard_text": "가만있어도 숨이 차서 매우 힘들어요.",
  "expected_replacements": [
    {"source_quote": "데우", "standard_text": "매우"}
  ],
  "gold_symptoms": ["호흡곤란"],
  "negative_symptoms": []
}
```

`gold_symptoms`와 `negative_symptoms`는 기존 증상 추출 평가와 이어서 볼 수 있도록 남긴 보조 필드입니다. 사투리 표준화 성능의 핵심 정답은 `gold_standard_text`와 `expected_replacements`입니다.

## 실행 전 준비

프로젝트 루트에서 실행한다고 가정합니다.

```bash
cd munjin-talk-talk

export AWS_PROFILE=<your-profile>
export AWS_REGION=ap-northeast-2
export AWS_DEFAULT_REGION=ap-northeast-2
export DIALECT_NORMALIZER_MODEL_ID=apac.amazon.nova-lite-v1:0
```

필요 패키지는 기존 백엔드/평가 환경과 동일하게 설치합니다.

```bash
pip install -r evaluation/ir/requirements.txt
# 또는 팀에서 쓰는 backend/serverless 의존성 설치 방식 사용
```

## 기본 실행

```bash
python evaluation/dialect/run_dialect_norm_eval.py \
  --input evaluation/dialect/data/dialect_norm_eval_200.jsonl \
  --output-dir evaluation/dialect/outputs/run_001
```

## Nova Lite Bedrock judge까지 실행

문장 exact match는 너무 엄격할 수 있습니다. 예를 들어 `매우 힘들어요`와 `너무 힘들어요`는 의미가 거의 같지만 exact match는 실패할 수 있습니다. 이때 Bedrock judge를 추가로 돌려 의미 보존 여부를 보조 평가합니다.

기본 judge 모델도 Nova Lite입니다. 우선순위는 `--judge-model-id` 인자, `DIALECT_EVAL_JUDGE_MODEL_ID`, `DIALECT_NORMALIZER_MODEL_ID`, `apac.amazon.nova-lite-v1:0` 순서입니다.

```bash
export DIALECT_EVAL_JUDGE_MODEL_ID=apac.amazon.nova-lite-v1:0

python evaluation/dialect/run_dialect_norm_eval.py \
  --input evaluation/dialect/data/dialect_norm_eval_200.jsonl \
  --output-dir evaluation/dialect/outputs/run_001_lite_judge \
  --semantic-judge \
  --judge-model-id apac.amazon.nova-lite-v1:0
```

## 결과 파일

```text
evaluation/dialect/outputs/run_001_lite_judge/
├── dialect_eval_summary.json
├── dialect_eval_case_results.jsonl
├── dialect_eval_case_results.csv
└── dialect_eval_failed_cases.csv
```

발표에는 보통 아래 지표를 넣으면 됩니다.

| 지표 | 의미 |
|---|---|
| `validator_pass_rate` | LLM 출력이 schema와 source_quote grounding 검증을 통과한 비율 |
| `exact_match_rate` | 모델 표준어 문장이 gold 표준어 문장과 완전히 같은 비율 |
| `avg_char_similarity` | 모델 표준어 문장과 gold 표준어 문장의 문자 기반 유사도 평균 |
| `replacement_precision` | 모델이 제시한 방언 치환 중 정답 치환인 비율 |
| `replacement_recall` | 정답 방언 치환 중 모델이 찾아낸 비율 |
| `replacement_f1` | 방언 치환 precision/recall의 조화평균 |
| `semantic_same_meaning_rate` | Nova Lite judge 기준 의미 보존 비율 |
| `no_added_fact_rate` | Nova Lite judge 기준 새 의학적 사실을 추가하지 않은 비율 |
| `no_omitted_fact_rate` | Nova Lite judge 기준 원문 의미를 누락하지 않은 비율 |

## 해석 주의

이 200개 데이터는 발표·회귀 테스트용 synthetic starter set입니다. 실제 성능 주장에는 병원/보건소 환경의 실제 발화 또는 독립 annotator가 만든 gold set을 추가하는 것이 좋습니다.

또한 같은 계열 모델이 표준화와 judge를 모두 맡으면 의미 보존 판단이 관대해질 수 있습니다. 발표 전에는 `dialect_eval_failed_cases.csv`와 성공 case 일부를 사람이 샘플링 검토하는 것을 권장합니다.

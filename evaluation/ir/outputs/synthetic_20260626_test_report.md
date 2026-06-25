# Synthetic IR Test Report - 2026-06-26

## Scope

- Dataset: `evaluation/ir/data/synthetic/synthetic_1000.json`
- Splits: dev 300, validation 200, locked holdout 500
- Fast test: IR candidate retrieval only, no LLM linker
- Full mini test: actual pipeline extraction + current G variant final linker on first 30 dev cases
- Embedding/ranking: Bedrock Titan embeddings + `rrf-hybrid`
- Linker model: `apac.amazon.nova-pro-v1:0`

## Dataset Validation

All generated synthetic files passed validation.

| File | Cases | Errors | Warnings |
| --- | ---: | ---: | ---: |
| `synthetic_1000.json` | 1000 | 0 | 0 |
| `synthetic_dev_300.json` | 300 | 0 | 0 |
| `synthetic_validation_200.json` | 200 | 0 | 0 |
| `synthetic_locked_holdout_500.json` | 500 | 0 | 0 |

## Fast Candidate-Only IR

This test checks whether the correct symptom appears in the top-k candidate list before final LLM linking.

| Split | Cases | Recall@3 | Recall@5 | Recall@10 | Recall@20 | MRR@5 | NDCG@5 | NegativeHit@20 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dev | 300 | 0.6522 | 0.7139 | 0.7972 | 0.8756 | 0.6662 | 0.6375 | 0.2500 |
| Validation | 200 | 0.5825 | 0.6492 | 0.7383 | 0.8408 | 0.6235 | 0.5791 | 0.2500 |
| Locked holdout | 500 | 0.6227 | 0.6843 | 0.7747 | 0.8510 | 0.6460 | 0.6112 | 0.2500 |
| Full synthetic | 1000 | 0.6235 | 0.6862 | 0.7742 | 0.8563 | 0.6476 | 0.6127 | 0.2500 |

## Oracle Upper Bound

Oracle uses the gold symptom name as the retrieval query. This checks whether the IR index itself contains the answer.

| Dataset | Cases | Recall@3 | Recall@5 | Recall@10 | Recall@20 | MRR@5 | NDCG@5 | NegativeHit@20 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Full synthetic oracle | 1000 | 0.9843 | 0.9980 | 1.0000 | 1.0000 | 0.9280 | 0.9478 | 0.1180 |

Interpretation: answer coverage is present in the symptom index. Most candidate-only misses are caused by casual speech, dialect surface forms, and symptom paraphrase mismatch before the query reaches the linker.

## Full Mini Pipeline Test

Input: first 30 cases from `synthetic_dev_300.json`

### Pipeline Extraction/Initial Matching

| Metric | Value |
| --- | ---: |
| Micro F1 | 0.6582 |
| Macro F1 | 0.6356 |
| Exact match rate | 0.5667 |
| False positive rate | 0.2353 |
| False negative rate | 0.4222 |
| Validator pass rate | 0.9333 |
| Error rate | 0.0333 |
| Avg extraction attempts | 1.367 |

Stage diagnostics:

| Stage metric | Value |
| --- | ---: |
| Span extracted case rate | 0.8667 |
| Active span case rate | 0.8667 |
| Matched case rate | 0.8333 |
| Avg span count | 1.500 |
| Avg active span count | 1.267 |
| Avg matched slot count | 1.167 |

### G Variant Final Linker on Pipeline Spans

| Metric | Value |
| --- | ---: |
| Candidate Recall@3 | 0.8278 |
| Candidate Recall@5 | 0.9056 |
| Candidate Recall@10 | 0.9222 |
| Candidate Recall@20 | 0.9222 |
| Linker Micro F1 | 0.8276 |
| Linker Macro F1 | 0.8611 |
| Linker Exact match rate | 0.8000 |
| Linker false positive rate | 0.1429 |
| Linker false negative rate | 0.2000 |
| Linker invalid count | 0 |

Interpretation: once a usable active symptom span is extracted, the current top-k linker performs much better than candidate-only retrieval. The main remaining bottleneck is not only final linking, but also extraction/normalization of casual and dialect symptom expressions.

## Recommended Next Steps

1. Tune only on `synthetic_dev_300.json`.
2. Keep `synthetic_locked_holdout_500.json` untouched until a candidate improvement is ready.
3. Analyze dev failures by symptom group and dialect surface form before adding more few-shot examples.
4. Add few-shot examples as category coverage, not as exact test-answer memorization.
5. Rerun the same fast IR and full mini pipeline commands after each prompt/RAG change.

## Reproduction Commands

```powershell
python evaluation\ir\run_ir_eval.py --input evaluation\ir\data\synthetic\synthetic_1000.json --output-dir evaluation\ir\outputs\synthetic_20260626_fast\ir_candidate_only --top-k 20 --variants C --skip-llm-judge
python evaluation\ir\run_ir_eval.py --input evaluation\ir\data\synthetic\synthetic_locked_holdout_500.json --output-dir evaluation\ir\outputs\synthetic_20260626_holdout_fast\ir_candidate_only --top-k 20 --variants C --skip-llm-judge
python evaluation\ir\run_ir_eval.py --input evaluation\ir\data\synthetic\synthetic_dev_300.json --output-dir evaluation\ir\outputs\synthetic_20260626_dev_fast\ir_candidate_only --top-k 20 --variants C --skip-llm-judge
python evaluation\ir\run_ir_eval.py --input evaluation\ir\data\synthetic\synthetic_validation_200.json --output-dir evaluation\ir\outputs\synthetic_20260626_validation_fast\ir_candidate_only --top-k 20 --variants C --skip-llm-judge
python evaluation\ir\run_ir_eval.py --input evaluation\ir\data\synthetic\synthetic_1000.json --output-dir evaluation\ir\outputs\synthetic_20260626_fast\ir_oracle_upper_bound --top-k 20 --variants O --skip-llm-judge
python evaluation\ir\run_eval_suite.py --input evaluation\ir\data\synthetic\synthetic_dev_300.json --output-dir evaluation\ir\outputs\synthetic_20260626_dev_full30 --limit 30 --top-k 20 --variants G
```

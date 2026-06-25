# Alias/Few-Shot Improvement Summary

Evaluation date: 2026-06-26

This run keeps the packaged Titan embedding cache stable and improves retrieval/linking through:

- domain-pack symptom aliases and keyword rules
- BM25 document alias text
- production-aligned alias preference in IR evaluation
- a small set of targeted symptom-hint few-shots

## Metrics

| Metric | Baseline | Improved |
| --- | ---: | ---: |
| Fast candidate recall@20 | 0.7300 | 0.9250 |
| Full pipeline candidate recall@20 | 0.7750 | 0.9550 |
| Linker micro F1 | 0.8063 | 0.9238 |
| Linker macro F1 | 0.7150 | 0.9100 |
| Exact match rate | 0.6900 | 0.8900 |
| False positive rate | 0.0723 | 0.0490 |
| False negative rate | 0.2870 | 0.1019 |

## Remaining Misses

The final full-pipeline run has 10 remaining failure rows. Most are extraction/gold-label boundary mismatches rather than broad retrieval collapse:

- eval_024: missed sneezing when rhinorrhea was selected
- eval_025: chest-pain wording still received no final prediction
- eval_041: anxiety/tachycardia collapsed to arrhythmia
- eval_043: headache wording received no final prediction
- eval_049: loose-stool wording received no final diarrhea prediction
- eval_065: chest pain collapsed to chest tightness/discomfort
- eval_069: fatigue collapsed to malaise
- eval_092: eye discharge missed while eye redness was selected
- eval_093: dysphagia collapsed to choking/aspiration wording
- eval_097: headache wording received no final prediction

Detailed artifacts:

- `ir_from_pipeline/summary.json`
- `ir_from_pipeline/failure_cases.csv`
- `ir_from_pipeline/candidates.csv`

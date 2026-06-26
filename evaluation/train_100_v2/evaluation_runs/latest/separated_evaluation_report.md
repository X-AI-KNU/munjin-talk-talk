# Separated Evaluation Report

- generated_at: `2026-06-26T05:25:31.329032+00:00`
- dataset: `evaluation/train_100_v2/train_100_v2.jsonl`
- dataset_rows: `100`
- held_out_test: `False`

## Track A - Offline IR

Runs no Bedrock. Combines alias hints and local BM25 symptom references.

- alias: recall@1=0.8198, recall@3=1.0, recall@5=1.0, recall@10=1.0, all_gold_hit@5=1.0, negative_in_top5_rate=0.5
- bm25: recall@1=0.5045, recall@3=0.8108, recall@5=0.8829, recall@10=0.9459, all_gold_hit@5=0.87, negative_in_top5_rate=0.6364
- combined: recall@1=0.8198, recall@3=1.0, recall@5=1.0, recall@10=1.0, all_gold_hit@5=1.0, negative_in_top5_rate=0.7727

## Track B - Dialect RAG

- Gangwon rows: `50`
- rag_pack_anchored recall: `1.0` (10/10)
- non-anchor hint rate: `0.0` (0/40)

## Track C - Pipeline Integration

- persistence: `monkeypatched_no_s3_dynamodb`
- rows: `100/100` completed
- precision: `0.9091`
- recall: `0.7207`
- F1: `0.804`
- schema/runtime failures: `0`
- source quote grounding rate: `1.0`
- RAG context node seen rate: `1.0`
- negative false-positive rate: `0.1364`

## Interpretation

- Track A is candidate-search quality, not final model F1.
- Track C is the first model/pipeline score, but this run is on train_100_v2 unless a locked test dataset is supplied.
- Held-out reporting still requires test_1000_v2 generation and a frozen first-pass report before any test-driven tuning.
- See `pipeline_error_analysis.md` for failure pattern interpretation.

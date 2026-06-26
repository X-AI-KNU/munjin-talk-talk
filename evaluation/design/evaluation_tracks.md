# Evaluation Tracks

The rebuild must separate retrieval, LLM extraction, and product behavior.

## Track A: Offline IR

Runs:

- local alias retrieval
- local symptom reference retrieval
- BM25 candidate ranking

Does not run:

- Bedrock
- LangGraph
- S3 or DynamoDB writes

Purpose:

- Check whether the correct symptom candidate appears in the retrieved list.
- Diagnose candidate-search failure before paying for LLM calls.

Metrics:

- recall@1, recall@3, recall@5, recall@10
- all-gold-hit@5
- negative-in-top5
- directness-stratified recall
- dialect-layer-stratified recall

## Track B: Dialect RAG Sanity

Runs:

- current Gangwon dialect pack retrieval
- source-layer checking

Does not run:

- Bedrock by default

Purpose:

- Prove whether a row marked `rag_pack_anchored` actually retrieves the expected dialect hint.
- Prevent false claims that all Gangwon-style rows are dialect-RAG-grounded.

Metrics:

- dialect hint recall@k for `rag_pack_anchored` rows
- false dialect hint rate for `clinical_colloquial` and `light_dialect_style` rows

## Track C: Pipeline Integration

Runs:

- `run_answer_pipeline` or `run_answers_pipeline_sync`
- dialect normalization
- RAG context retrieval
- Bedrock extraction
- schema validation
- hybrid IR linking

Purpose:

- Measure actual extraction behavior.
- Confirm that RAG context is included in prompts.
- Confirm that Bedrock returns schema-valid, transcript-grounded output.

Metrics:

- symptom micro precision, recall, F1
- symptom macro F1 by group
- status accuracy
- negative symptom false-positive rate
- source-quote grounding rate
- Bedrock/schema failure rate

## Track D: Product E2E

Runs:

- patient Q1-Q4 submit flow
- async Lambda analysis
- S3/DynamoDB persistence
- onepaper refresh
- staff and doctor UI readiness states

Purpose:

- Validate product behavior after model/pipeline evaluation is acceptable.

Metrics:

- session reaches expected status
- onepaper generated
- no patient-facing blocking on Bedrock
- staff/doctor views show consistent state

## Reporting Rule

Never describe Track A IR recall as final model F1.

The first real model score must come from Track C on a locked dataset.

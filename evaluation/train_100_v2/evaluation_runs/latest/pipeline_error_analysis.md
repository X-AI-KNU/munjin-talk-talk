# Pipeline Error Analysis

Dataset: `evaluation/train_100_v2/train_100_v2.jsonl`

This is not a held-out score. It is a train-set pipeline inspection run used to
separate candidate-search quality from actual Bedrock extraction and linking.

## Summary

- Completed rows: 100/100
- Schema/runtime failures: 0
- Source quote grounding rate: 1.0
- Pipeline symptom precision: 0.9091
- Pipeline symptom recall: 0.7207
- Pipeline symptom F1: 0.8040
- Negative false-positive rate among rows with negative symptoms: 0.1364

## Main Finding

Track A combined IR recall@5 is 1.0, but Track C recall is 0.7207.

This means the current bottleneck is not candidate availability. The important
loss happens after retrieval context is available, mainly in extraction span
typing, quote granularity, and final IR linking.

## Failure Types

### 1. Over-broad source_quote contaminates IR query

The LLM often returns the whole sentence as `source_quote`. When one sentence
contains multiple symptoms or a negated symptom, the IR query can be pulled to
the wrong candidate.

Examples:

- `train_v2_014`: "열은 아직 있고 기침은 완전 없어졌어"
  - gold: `열`
  - predicted: `기침`
  - issue: negated/resolved cough contaminated the active fever span query.
- `train_v2_096`: "속이 울렁거리고 토했는데 설사는 전혀 없어"
  - gold: `구토`
  - predicted: `설사`
  - issue: absent diarrhea contaminated the vomiting span query.
- `train_v2_022`: "기침할 때 노랗고 걸쭉한 가래가 많이 나와"
  - gold: `화농성 객담`
  - predicted: `기침`
  - issue: trigger/context word "기침할 때" dominated the sputum-character query.

### 2. LLM marks symptoms as context instead of active symptom

Examples:

- `train_v2_007`: "목이 아푸나 싶고 코도 계속 막혀서 숨 쉬기가 불편해"
  - gold: `목의 통증`, `코막힘`
  - predicted: none
  - issue: LLM produced `context` spans with `slot_ref=other`, so hybrid IR skipped them.

### 3. Local obstruction is confused with dyspnea

Example:

- `train_v2_002`: "코가 완전 막혀서 숨쉬기 힘들어"
  - gold: `코막힘`
  - predicted: `호흡곤란`
  - issue: the phrase "숨쉬기 힘들어" describes nasal obstruction consequence, but the pipeline treats it as respiratory dyspnea.

### 4. Multi-symptom answers lose secondary symptoms

Examples:

- `train_v2_021`: "기침이 자꾸 나고 가래도 많이 나와"
  - gold includes `가래`
  - predicted only `기침`
- `train_v2_043`: "숨 쉬기가 힘들고 가슴이 답답해"
  - gold includes `호흡곤란`, `가슴 답답`
  - predicted only `가슴 답답`
- `train_v2_063`: "몸땡이 쑤시고 온몸이 피곤해"
  - gold includes `근육통`, `피로감`
  - predicted only `피로감`

## Stratified Weak Spots

- Q3 standard rows: precision 0.857, recall 0.667, F1 0.750
- Q3 Gangwon clinical colloquial rows: precision 1.000, recall 0.643, F1 0.783
- Q1 Gangwon RAG-anchored rows: precision 1.000, recall 0.625, F1 0.769

The weaker groups are mostly recall-limited rather than precision-limited.

## Recommended Next Fixes

1. Tighten extraction prompt examples so active symptoms are not emitted as `context`.
2. Add a repair/normalization rule that narrows broad `source_quote` to the smallest symptom-bearing substring before IR.
3. In IR linking, give stronger priority to the LLM `slot_ref` when it is a valid ontology slot and the source quote is broad.
4. Add explicit rules for local obstruction:
   - nasal obstruction causing breathing inconvenience should remain `코막힘`
   - create `호흡곤란` only when breathlessness is not locally explained by nasal blockage.
5. For negation and resolved symptoms, prevent absent terms from contaminating active span IR queries.

## Reporting Rule

Do not report this as final held-out performance. The first publishable model
score must be run on locked `test_1000_v2` after it is generated and frozen.

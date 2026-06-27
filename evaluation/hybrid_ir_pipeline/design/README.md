# Clean Evaluation Rebuild Design

This folder is the new starting point after removing the first contaminated train/evaluation cycle.

## 한국어 요약

이 폴더는 오염된 첫 train/evaluation cycle을 걷어낸 뒤, 평가를 다시 설계한 기준 문서입니다. 핵심은 `train_100_v2`와 향후 `test_1000_v2`를 분리하고, held-out test 실패를 본 뒤 prompt, alias, few-shot, domain pack을 다시 고치는 식의 누수를 막는 것입니다.

`train_100_v2`는 런타임 산출물을 만들고 파이프라인을 점검하는 용도입니다. 최종 공개 성능은 별도 고정 테스트셋에서 첫 실행 리포트를 저장한 뒤에만 말해야 합니다.

## Reset Scope

Removed from the active tree:

- old `evaluation/generated/train_100`
- old `evaluation/train_100_blueprint`
- old `evaluation/train_100_training`
- old `evaluation/train_100_evaluation`
- old `evaluation/test_1000_blueprint`
- train-derived `backend/serverless/src/data/domain_packs/respiratory.json`
- train-derived `backend/serverless/src/data/fewshots/respiratory/*.json`

Preserved:

- application pipeline code
- question set structure
- current Gangwon dialect RAG pack as a source reference
- reset marker documentation

## Core Principle

The new study has two separate jobs.

1. `train_100_v2`: build and inspect runtime artifacts.
2. `test_1000_v2`: measure held-out performance.

Do not use `test_1000_v2` failures to change aliases, few-shots, domain packs, prompts, or scoring rules before the first held-out report is saved.

## Data Target

The synthetic utterances are for symptom extraction, not for full questionnaire completion.

Target questions:

- Initial visit: Q1 chief complaint only.
- Follow-up visit: Q3 recurrence/course only.

Excluded from symptom-evaluation datasets:

- Q2 onset timing.
- Q4 patient questions to doctor.

Language split:

- 50% standard Korean.
- 50% Gangwon-style Korean.

Dialect rows must carry a source layer:

- `rag_pack_anchored`: uses a term or pattern actually present in the current Gangwon dialect RAG pack.
- `clinical_colloquial`: natural medical colloquial speech not claimed as RAG-pack dialect.
- `light_dialect_style`: local cadence or endings only; not evidence of dialect RAG coverage.

## Generation Style

Rows should be LLM-rendered from a blueprint, not mechanically assembled from templates.

Good rows:

- sound like a patient speaking casually.
- avoid direct technical symptom names when patients would usually describe the feeling.
- allow simple common words such as cough, runny nose, fever, throat pain, and phlegm.
- hide more technical concepts behind natural descriptions.

Bad rows:

- repeat the same sentence frame with swapped symptom names.
- mention every canonical symptom name directly.
- include duration, recurrence, medication, and doctor questions inside Q1/Q3 unless the blueprint explicitly marks them as context.
- use dialect labels without source-layer evidence.

## Artifact Provenance

Every future train-derived artifact must record its source.

Required fields:

- source case ids.
- source quote.
- proposed canonical symptom or rule.
- artifact type: domain pack, alias, few-shot, reviewer rule, or scoring rule.
- acceptance reason.
- rejection reason when not accepted.

Few-shot examples must be sparse and representative. They should teach structure and ambiguity handling, not memorize the train set.

## Evaluation Tracks

Keep these metrics separate.

| Track | Runs Bedrock | Measures |
| --- | ---: | --- |
| Offline IR | No | Whether the correct canonical symptom enters deterministic candidate lists |
| Dialect RAG sanity | No | Whether dialect pack hints are retrieved for dialect-layer rows |
| Pipeline integration | Yes | Whether LangGraph uses dialect normalization, RAG prompt notes, Bedrock extraction, schema validation, and IR linking correctly |
| Product E2E | Yes | Whether the real Q1-Q4 async flow produces usable onepaper state |

IR recall is not final F1. Final extraction performance must come from the pipeline integration track.

## Current Output

The accepted blueprint now lives in `evaluation/hybrid_ir_pipeline/blueprint/`.

The blueprint defines:

- exact symptom-group distribution.
- exact dialect source-layer counts.
- direct-name versus paraphrase policy.
- negative and resolved symptom ratios.
- difficulty levels.
- validation checks before rendering.

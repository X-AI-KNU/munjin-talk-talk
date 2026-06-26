# Test 1000 Quality Gate

Accept the rendered test set only when all checks pass.

## Structural Checks

- Exactly 1000 cases.
- Every `case_id` in `case_blueprint.jsonl` appears once.
- No extra case IDs.
- All metadata fields match the blueprint exactly.
- `dataset_role` is always `held_out_test`.
- `text` is non-empty.
- No duplicate `text`.

## Distribution Checks

- Q1 chief complaint: 500.
- Q3 new symptoms or course: 500.
- Standard colloquial: 500.
- Kangwon colloquial: 500.
- Quadrants are 250 each.
- Standard rows all have `dialect_source_layer: none`.
- Kangwon source-layer counts match `distribution_plan.json`.
- Symptom group counts match `distribution_plan.json`.
- Status pattern counts match `distribution_plan.json`.
- Gold symptom count and negative symptom count distributions match `distribution_plan.json`.

## Leakage Checks

- No rendered text exactly matches any `train_100` text.
- No rendered text is near-duplicate of `train_100` text by high character n-gram overlap.
- `rag_pack_anchored` Kangwon rows contain at least one natural expression grounded in `dialect_kangwon.csv/json`.
- `train_validated_medical_colloquial` rows must not claim that their colloquial forms are dialect-pack terms.
- Rare dialect-pack words must not be forced into medical utterances when unnatural.
- `direct_label_forbidden` cases must not contain exact forbidden standard labels.
- Patient text must not be EMR style.
- Patient text must not contain JSON, bullets, diagnosis, explanation, or staff/doctor narration.
- Test data must not be used to revise training artifacts before the first evaluation report.

## Semantic Checks

- Every `gold_symptoms` item is supported by the patient text.
- Every `negative_symptoms` item is denied, absent, resolved, or improved.
- Q1 cases answer chief complaint only.
- Q3 cases answer new symptoms, persistent symptoms, worsening, improvement, or post-visit course.
- Standard cases are casual spoken Korean, not formal writing.
- Kangwon cases remain understandable and do not become rare-word dumps.
- Complex symptom labels are usually paraphrased rather than copied.

## First Evaluation Lock

Before inspecting individual failures:

1. Freeze runtime artifacts.
2. Run the evaluation.
3. Save aggregate metrics and case-level output.
4. Commit the first report.

Only after that can failure analysis begin.

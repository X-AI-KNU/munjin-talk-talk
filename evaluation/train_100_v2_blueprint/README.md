# Train 100 v2 Blueprint

This folder contains the accepted row-level blueprint for `train_100_v2`.

It is not rendered patient text. It defines what the later LLM renderer must create.

## Files

- `distribution_plan.json`: fixed counts and hard rules.
- `case_blueprint.schema.json`: row schema.
- `case_blueprint.jsonl`: 100 planned rows.
- `quality_gate_report.json`: generated validation summary.

## Scope

Only these question targets are allowed:

- Initial visit Q1 chief complaint.
- Follow-up visit Q3 recurrence/course.

Q2 onset/duration and Q4 patient questions are intentionally excluded from this dataset.

## Rendering Rule

The renderer must create casual spoken Korean patient utterances from the blueprint.
It must not mechanically assemble templates or copy prior `train_100` text.

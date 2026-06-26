# Test 1000 Blueprint

This folder defines the held-out evaluation dataset design for MunjinTalkTalk symptom IR/RAG testing.

`test_1000` must be generated after the runtime artifacts derived from `train_100` are frozen. It is not training material. It must not be used to revise domain packs, aliases, few-shots, prompts, or scoring rules before the first evaluation report is saved.

## Files

| File | Purpose |
| --- | --- |
| `distribution_plan.json` | Target distribution for the 1000 held-out cases |
| `case_blueprint.schema.json` | JSON schema for each future test blueprint row |
| `llm_render_prompt.md` | Prompt template for LLM-based test utterance rendering |
| `quality_gate.md` | Manual and automated checks before accepting rendered test data |
| `row_design_protocol.md` | Rules for creating the 1000 row-level blueprint without leaking train data |
| `dialect_source_policy.md` | Source-grounding rules for Kangwon dialect expressions |

## Workflow

1. Freeze the current `train_100`-derived runtime artifacts.
2. Create `case_blueprint.jsonl` with exactly 1000 rows using this folder's distribution plan.
3. Render patient utterances with an LLM using `llm_render_prompt.md`.
4. Save rendered output as `evaluation/generated/test_1000/cases.jsonl`.
5. Run quality gates without changing runtime artifacts.
6. Run the first evaluation once and save the report before inspecting failures case by case.

## Role

`test_1000` answers one question only:

> When the current runtime built from `train_100` sees new synthetic patient speech, how well does it retrieve and normalize symptoms without having seen those utterances during artifact construction?

It is acceptable for the first score to be imperfect. That imperfection is the measurement.

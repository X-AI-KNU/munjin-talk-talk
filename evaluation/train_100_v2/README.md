# Train 100 v2 Rendered Data

This folder contains the LLM-rendered training utterances created from
`evaluation/train_100_v2_blueprint/case_blueprint.jsonl`.

The generated data is training material only. It may be used to build clean
domain packs, aliases, few-shot examples, and validation rules. It must not be
reported as held-out model performance.

## Files

- `render_train.py`: Bedrock renderer and quality gate.
- `train_100_v2.jsonl`: rendered patient utterances.
- `quality_gate_report.json`: validation summary.

## Rendering Contract

- Render only initial Q1 and follow-up Q3 answers.
- Use casual spoken Korean.
- Avoid formal `-습니다` style.
- Do not include Q2 onset/duration as the main answer.
- Do not include Q4 doctor questions or medication/supplement questions.
- Preserve gold symptoms and explicitly negated symptoms from the blueprint.
- For `rag_pack_anchored` rows, include the assigned dialect anchor naturally.

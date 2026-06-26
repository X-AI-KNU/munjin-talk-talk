# Evaluation Reset

The previous IR evaluation folder, generated datasets, run outputs, train-derived aliases, few-shots, and domain-pack tuning artifacts have been removed.

This directory now keeps only reset status and clean design documents. Generated train/test data must not be committed here until the new blueprint is accepted.

Current rebuild order:

1. Freeze the reset scope and leakage rules.
2. Design `train_100_v2`.
3. Render `train_100_v2` with LLM-generated patient utterances from the approved blueprint.
4. Build the runtime domain pack from the source symptom ontology, then add aliases and few-shot candidates from accepted `train_100_v2` only.
5. Freeze runtime artifacts with provenance that separates ontology source and train-derived support.
6. Design and render a separate locked `test_1000_v2`.
7. Run offline IR evaluation and real Bedrock pipeline evaluation as separate tracks.
8. Save the first held-out report before inspecting individual test failures for improvements.

Do not restore the old `evaluation/ir`, `train_100`, or `test_1000` outputs as training material.

See `design/` for the new clean rebuild plan.

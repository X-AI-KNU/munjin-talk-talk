# LLM Render Prompt For Test 1000

Use this prompt to render future `case_blueprint.jsonl` rows into held-out synthetic patient utterances.

The blueprint controls labels and distribution. The LLM only writes natural patient text.

## System Prompt

```text
You generate synthetic Korean patient utterances for a held-out medical intake symptom IR evaluation set.

This is not real patient data. Your task is not diagnosis. Your task is to render natural patient speech from a fixed blueprint row.

Hard rules:
1. Do not change case_id, dataset_role, visit_type, question_id, question_type, dialect_type, dialect_intensity, dialect_source_layer, symptom_group, gold_symptoms, negative_symptoms, status_pattern, expression_policy, difficulty, or surface_target.
2. Generate only one patient utterance in the `text` field.
3. Use casual spoken Korean. Do not use formal EMR, report style, bullet style, or "-습니다/-합니다" style.
4. Q1 must answer chief complaint. Q3 must answer new symptoms, persistent symptoms, worsening, improvement, or post-visit course.
5. Do not include Q2 onset-only content or Q4 patient questions.
6. For negative_symptoms, mention them only as denied, absent, resolved, or improved.
7. For gold_symptoms, make them currently active, newly developed, persistent, or worsened according to status_pattern.
8. If expression_policy is direct_label_forbidden, do not copy the exact standard symptom label into the patient utterance.
9. Prefer lay speech for complex symptoms. Basic words such as 기침, 가래, 콧물, 코막힘, 열, 재채기, 구토, 설사 may appear naturally.
10. If dialect_type is kangwon, follow dialect_source_layer:
    - rag_pack_anchored: include one natural expression grounded in dialect_kangwon.csv/json, only if it fits the medical meaning.
    - train_validated_medical_colloquial: use known medical colloquial families such as 가심, 맥혀, 코물, 아푸다, 아퍼, 아녀, 않어, 하니, or 영 without copying train_100 sentences.
    - light_dialect_flavor: keep mostly standard symptom wording with mild local cadence.
    Do not overuse rare dialect words.
11. Avoid any phrase listed in avoid_surface_forms.
12. Preserve semantic clarity. A clinician should be able to infer the gold symptoms and denied negative symptoms from the utterance.
13. Return strict JSON only.
```

## User Prompt Template

```text
Render this held-out blueprint row into one synthetic patient utterance.

Blueprint row:
{BLUEPRINT_ROW_JSON}

Return JSON:
{
  "case_id": "same as blueprint",
  "dataset_role": "same as blueprint",
  "visit_type": "same as blueprint",
  "question_id": "same as blueprint",
  "question_type": "same as blueprint",
  "dialect_type": "same as blueprint",
  "dialect_intensity": "same as blueprint",
  "dialect_source_layer": "same as blueprint",
  "symptom_group": "same as blueprint",
  "text": "one natural patient utterance",
  "gold_symptoms": ["same as blueprint"],
  "negative_symptoms": ["same as blueprint"],
  "status_pattern": "same as blueprint",
  "expression_policy": "same as blueprint",
  "difficulty": "same as blueprint",
  "surface_target": "same as blueprint"
}
```

## Batch Rule

Render at most 10 blueprint rows per LLM call. Larger batches flatten style and increase phrase repetition.

Do not include examples from `train_100` in the prompt.

# Train 100 v2 Blueprint Draft

This is a design draft only. It is not generated data and must not be used as evaluation output.

## Scope

`train_100_v2` trains and inspects the symptom extraction support layer.

Included:

- Initial visit Q1: chief complaint.
- Follow-up visit Q3: recurrence, persistence, worsening, improvement, or return of symptoms.

Excluded:

- Q2 onset timing.
- Q4 patient questions to the doctor.
- Medication history unless a future blueprint explicitly creates a separate medication-context task.
- Exact duration expressions unless a future blueprint explicitly evaluates duration handling.

## Required Counts

Total rows: 100.

Visit and question split:

| Visit | Question | Count |
| --- | --- | ---: |
| Initial | Q1 chief complaint | 50 |
| Follow-up | Q3 recurrence/course | 50 |

Language split:

| Language Style | Count |
| --- | ---: |
| Standard Korean | 50 |
| Gangwon-style Korean | 50 |

Cross split:

| Visit/Question | Standard | Gangwon-style |
| --- | ---: | ---: |
| Initial Q1 | 25 | 25 |
| Follow-up Q3 | 25 | 25 |

## Dialect Source Layers

Every Gangwon-style row must carry one source layer.

| Layer | Target Count | Rule |
| --- | ---: | --- |
| `rag_pack_anchored` | source-limited | Use only expressions actually present in the current Gangwon dialect pack |
| `clinical_colloquial` | remaining clinical speech | Natural patient speech, not claimed as dialect-pack evidence |
| `light_dialect_style` | remaining local cadence | Local ending/cadence only, not claimed as dialect evidence |

The current dialect pack appears sparse for medical symptoms. Therefore `rag_pack_anchored` is not a forced quota until the source scan is complete. If the pack cannot support enough medical rows, record that as a dataset limitation instead of fabricating dialect evidence.

## Symptom Group Distribution

The first draft should cover respiratory/ENT-adjacent symptom extraction without overfitting to one symptom family.

| Group | Count |
| --- | ---: |
| Upper airway and common cold-like symptoms | 18 |
| Cough, phlegm, and lower-airway symptoms | 20 |
| Dyspnea, chest discomfort, and urgent respiratory clues | 18 |
| Fever, chills, fatigue, body ache, and systemic course | 14 |
| Voice, swallowing, throat, eye, and ENT-adjacent symptoms | 10 |
| Dizziness, palpitation, edema, and overlapping red-flag context | 10 |
| GI or nonspecific context that may confuse respiratory extraction | 10 |

These are design buckets, not final canonical labels. Canonical symptom names must be frozen only after the clean domain pack is rebuilt from accepted training rows.

## Expression Policy

Common patient words can appear directly:

- cough
- runny nose
- stuffy nose
- fever
- phlegm
- throat pain
- dizziness

Technical or less patient-natural concepts should be paraphrased:

- dyspnea
- wheezing
- hemoptysis
- purulent sputum
- edema
- dysphagia
- chest tightness

Target directness:

| Expression Type | Count |
| --- | ---: |
| Direct common patient word | 35 |
| Lay paraphrase | 45 |
| Technical concept hidden behind natural description | 20 |

## Status Pattern Distribution

| Status Pattern | Count | Meaning |
| --- | ---: | --- |
| `active_current` | 45 | Symptom is present now |
| `recurrent_or_persistent` | 25 | Follow-up Q3 symptom persists, returns, or repeats |
| `improved_or_resolved` | 10 | Symptom improved or resolved and should not become current complaint unless recurrence is present |
| `denied_negative_context` | 15 | Symptom is explicitly absent |
| `mixed_context` | 5 | One symptom present while another is absent or improved |

## Leakage Rules

The renderer must not:

- copy old `train_100` utterances.
- copy old `test_1000` blueprint rows.
- use Q2-style onset phrases such as "when it started" as the main content.
- use Q4-style doctor questions as the target sentence.
- repeatedly swap symptom names into the same sentence frame.
- insert canonical labels solely to make IR easy.

The renderer may:

- use short casual speech.
- use imperfect grammar if natural.
- use mild dialect endings when the row is marked `light_dialect_style`.
- include negative context when explicitly assigned.

## Quality Gate Before Rendering

Before generating patient text, the blueprint must pass:

- exactly 100 planned rows.
- exactly 50 Q1 and 50 Q3.
- exactly 50 standard and 50 Gangwon-style.
- no Q2 or Q4 target rows.
- every Gangwon-style row has a source layer.
- every row has expected gold symptoms and expected negative symptoms.
- every row has one status pattern.
- every row has an expression policy.

## Quality Gate After Rendering

After LLM rendering, reject a row if:

- it does not sound like spoken Korean.
- it contains a doctor question rather than a patient answer.
- Q2 timing dominates the content.
- it mentions medication as the main answer.
- the gold symptom is not inferable from the text.
- a negative symptom is phrased as present.
- a technical concept is directly named in a row marked `technical_hidden`.
- dialect layer evidence is overstated.

## Artifact Build Rule

Accepted `train_100_v2` may produce:

- clean domain pack candidates.
- alias candidates.
- few-shot candidates.
- reviewer or safety rules.

Every accepted artifact must include source case ids and a human-readable reason.

No artifact may be built from `test_1000_v2`.

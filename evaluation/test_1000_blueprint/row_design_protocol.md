# Test 1000 Row Design Protocol

This document describes how to create `case_blueprint.jsonl`. It should be used before any LLM rendering of final patient utterances.

## Non-Negotiables

- Create exactly 1000 blueprint rows.
- Do not write final patient utterances in the blueprint.
- Do not copy `train_100` patient text.
- Do not copy `train_100` renderer notes.
- Do not inspect current failure cases while authoring rows.
- Do not use Q2 onset timing or Q4 patient question content.
- Use only Q1 chief complaint and Q3 follow-up/new symptom content.
- Keep standard Korean and Gangwon colloquial at exactly 50% each.
- Standard rows must set `dialect_source_layer` to `none`.
- For Kangwon rows, set `dialect_source_layer` according to `dialect_source_policy.md`.

## Row ID Blocks

| Range | Question | Dialect | Count |
| --- | --- | --- | ---: |
| `test_bp_0001`-`test_bp_0250` | Q1 | standard | 250 |
| `test_bp_0251`-`test_bp_0500` | Q1 | kangwon | 250 |
| `test_bp_0501`-`test_bp_0750` | Q3 | standard | 250 |
| `test_bp_0751`-`test_bp_1000` | Q3 | kangwon | 250 |

## Symptom Coverage

Use the same canonical symptom inventory as the frozen respiratory domain pack, but do not force every patient utterance to say the canonical label.

Basic words may appear directly:

- 기침
- 가래
- 콧물
- 코막힘
- 열
- 재채기
- 구토
- 설사

Complex or clinical labels should usually be rendered as lay speech:

- 호흡곤란: "숨이 차", "숨쉬기가 답답해", "말하기도 벅차"
- 운동 시 호흡곤란: "계단 오르면 숨이 차", "조금만 움직여도 숨이 벅차"
- 흉통: "가슴 한쪽이 콕콕 아파", "가심이 결려"
- 객혈: "가래에 피가 비쳐", "피 섞인 게 나와"
- 화농성 객담: "누런 가래가 진하게 나와"
- 검은색 가래: "가래 색이 거뭇해"
- 거품이 섞인 가래: "거품 낀 가래가 나와"
- 삼키기 곤란: "약이 목에 걸린 듯 잘 안 넘어가"
- 가슴 두근거림: "심장이 갑자기 빨리 뛰는 느낌"
- 부정맥: "맥이 고르지 않고 한 번씩 툭 빠져"
- 근력 약화: "팔다리에 힘이 잘 안 들어가"
- 식욕부진: "입맛이 너무 없어"

## Negative Context Design

Negative symptoms are not current symptoms. They must be expressed as denied, absent, resolved, or improved.

Good negative forms:

- "열은 없어"
- "가슴이 아픈 건 아니야"
- "피는 안 보여"
- "설사는 안 해"
- "숨이 차진 않아"
- "기침은 좀 나았는데..."

Avoid ambiguous negative forms unless the row is intentionally hard and still clinically clear.

## Dialect Design

Gangwon rows should sound colloquial, not like a list of rare dialect words.

The current runtime dialect RAG pack is a general vocabulary pack, not a medical symptom lexicon. Therefore Kangwon rows must declare one of three source layers:

- `rag_pack_anchored`: includes at least one natural expression grounded in `dialect_kangwon.csv/json`.
- `train_validated_medical_colloquial`: uses medical colloquial families already validated in `train_100`, without copying full train utterances.
- `light_dialect_flavor`: mostly standard symptom wording with mild local cadence or endings.

Target mix inside 500 Kangwon rows:

| Layer | Count |
| --- | ---: |
| `rag_pack_anchored` | 120 |
| `train_validated_medical_colloquial` | 280 |
| `light_dialect_flavor` | 100 |

RAG-pack anchored examples that can be used when natural:

- `아푸나?` -> `아프니?`
- `(가슴이) 제리제리하다` -> `저리다`
- `코빼기` -> `코`
- `다리깽이` -> `다리`
- `몸땡이` -> `몸통`
- `자우름` -> `졸음`
- `장구카다`, `잠구키다` -> `잠기다`
- `줄구다` -> `줄이다`
- `지악`, `으찌냑` -> `저녁`, `어제 저녁`
- `역부러` -> `일부러`

Train-validated medical colloquial examples:

- "아녀", "없어/없드래", "그랬어", "하니", "가심", "맥혀", "아퍼"

These are style families, not proof that the current dialect RAG pack contains those exact terms.

Strong dialect rows are limited to 50 cases and must remain understandable.

## Surface Variation

Each row should include a `surface_target` to prevent mechanical repetition.

- `short_single_clause`: one simple spoken complaint.
- `two_clause_with_reason_or_timing`: one symptom plus timing, reason, or daily context.
- `mixed_active_and_denied`: active gold symptom plus denied negative symptom.
- `followup_course_sentence`: Q3-only course after prior visit or medication.

## Held-Out Discipline

After `test_1000` is rendered and accepted, save the first evaluation report before changing any runtime logic. Later improvements must be reported as post-test iteration, not as the initial held-out score.

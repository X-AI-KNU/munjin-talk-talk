# Dialect Source Policy

`test_1000` uses Gangwon-style utterances, but the source of each dialect feature must be clear.

The runtime dialect RAG source is:

- `backend/serverless/src/data/dialect_packs/dialect_kangwon.csv`
- `backend/serverless/src/data/dialect_packs/dialect_kangwon.json`

The pack currently contains 436 source CSV rows and 581 loaded variants after bracket/variant expansion.

## Important Finding

The Gangwon dialect pack is a general vocabulary pack, not a medical symptom lexicon. It has useful everyday words, body words, and some symptom-adjacent forms, but it does not cover most medical complaint phrases directly.

Therefore, the test set must not pretend that all dialectal medical expressions come from the RAG pack.

## Three Dialect Evidence Layers

### Layer A: RAG-Pack Anchored Dialect

These are expressions directly grounded in `dialect_kangwon.csv/json`. Use them only when natural in a patient utterance.

| Dialect pack form | Standard meaning | Test-set use |
| --- | --- | --- |
| `아푸나?` | `아프니?` | pain-related wording anchor |
| `(가슴이) 제리제리하다` | `저리다` | chest/body sensation anchor, not a synonym for chest pain by itself |
| `코빼기` | `코` | nose/body-part anchor |
| `다리깽이` | `다리` | leg/body-part anchor |
| `몸땡이` | `몸통` | body anchor |
| `자우름` | `졸음` | fatigue/sleepiness-adjacent anchor |
| `창지` | `창자` | abdominal/body-part anchor |
| `장구카다` | `잠기다` | voice/nasal blockage context only if natural |
| `잠구키다` / `장구키다` | `잠기다` | voice/nasal blockage context only if natural |
| `줄구다` | `줄이다` | improvement/reduction context |
| `지악` | `저녁` | timing context |
| `으찌냑` | `어제 저녁` | timing context |
| `역부러` | `일부러` | daily context |
| `빡시다` | `(힘이) 세다` | effort/strength context, not direct weakness |

### Layer B: Train-Validated Medical Colloquial Forms

These are not claimed to come from the dialect RAG pack. They are medical-intake colloquial forms already used successfully in `train_100` or generated runtime few-shots.

Examples:

- `가심` as a colloquial chest form.
- `맥혀` as a colloquial blocked/stuffy form.
- `코물` as a colloquial runny nose form.
- `아푸다`, `아퍼`, `아푸고` as pain variants.
- `아녀`, `않어` as denial endings.
- `하니`, `영` as light Gangwon-style flavor.

For held-out testing, these may be used as style families, but exact train sentences must not be copied.

### Layer C: Light Dialect Flavor Without Lexical Claim

These cases use mostly standard symptom wording with mild local cadence or endings. They are useful because real patient speech is often only lightly dialectal.

Examples:

- Slight sentence endings.
- Natural word order.
- Casual denial forms.
- No rare dialect vocabulary.

## Target Mix Inside 500 Kangwon Cases

| Dialect source layer | Count | Rationale |
| --- | ---: | --- |
| Layer A: RAG-pack anchored | 120 | Measures whether actual dialect pack hints can help when relevant terms appear |
| Layer B: train-validated medical colloquial | 280 | Measures medical symptom robustness for realistic local speech not fully covered by the pack |
| Layer C: light dialect flavor | 100 | Measures common lightly dialectal speech without overfitting to rare vocabulary |

## Prohibited Claims

- Do not say `가심`, `맥혀`, or `아녀` are from the current dialect RAG pack unless they are later added to that pack.
- Do not force rare pack words into symptom utterances just to satisfy a dialect quota.
- Do not use dialect terms that change the medical meaning.
- Do not use dialect pack terms as gold labels.
- Do not use Q2 or Q4 content to increase dialect variety.

## Evaluation Interpretation

When analyzing test failures, separate these buckets:

- Failure on Layer A: dialect RAG coverage or retrieval issue.
- Failure on Layer B: medical colloquial normalization issue.
- Failure on Layer C: general robustness issue, not specifically dialect RAG.

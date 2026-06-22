# 문진톡톡 IR 평가 브랜치

이 디렉터리는 문진톡톡의 **표준 증상 매칭 성능**을 평가하기 위한 전용 코드입니다.
실서비스 파이프라인에서 LLM이 만든 증상 span을 입력으로 받아, BM25 + Vector 기반 IR 후보군을 만들고, 필요한 경우 Pro LLM linker가 후보 안에서 최종 표준 증상을 선택합니다.

현재 이 브랜치의 기본 채택안은 다음 조합입니다.

```text
G안 = 표준화 span + LLM 증상명
   -> BM25 + Titan Vector + label signal
   -> RRF hybrid rank fusion
   -> top-20 후보
   -> Nova Pro final linker
   -> 후보 밖 선택 금지 validator
```

이 조합은 복잡한 full-list fallback 없이, IR이 만든 후보군 안에서만 LLM이 고르는 구조입니다.
평가 결과 기준으로는 `ir_all100_g_top20_rrf_linker_prompt_v2`에서 `linker_micro_f1 = 0.8223` 수준을 보였고, 현재 MVP에서는 이 구성이 가장 단순하면서도 설명 가능한 기준선입니다.

## 왜 IR과 Linker를 분리하나

LLM이 바로 표준 증상명을 생성하게 하면, 실제 증상 목록에 없는 이름을 만들거나 비슷한 표현을 임의로 생성할 수 있습니다.
그래서 문진톡톡은 먼저 IR로 표준 증상 후보를 좁히고, LLM은 그 후보 안에서만 고르게 합니다.

분리해서 보면 병목도 명확해집니다.

| 단계 | 평가하려는 것 |
|---|---|
| IR 후보 검색 | 정답 증상이 top-k 후보 안에 들어오는가 |
| Pro linker | 후보 안에 정답이 있을 때 LLM이 올바르게 고르는가 |
| Validator | 후보 밖 증상명 생성, 부정/호전 증상의 잘못된 선택을 막는가 |

## 파일 구성

| 파일 | 역할 |
|---|---|
| `run_pipeline_eval.py` | 원본 평가 문장을 실제 백엔드 파이프라인에 넣어 `normalized_text`, `span`, `symptom_hint`를 생성합니다. |
| `run_ir_eval.py` | 파이프라인이 만든 span으로 IR 후보 검색과 LLM linker 평가를 수행합니다. |
| `run_eval_suite.py` | 파이프라인 생성과 IR 평가를 이어서 실행하는 보조 스크립트입니다. |
| `data/eval_cases.sample.jsonl` | 공개 가능한 샘플 평가 데이터입니다. |
| `data/eval_cases.jsonl` | 실제 평가 데이터 위치입니다. 개인정보나 저작권 이슈가 있으면 Git에 올리지 않습니다. |
| `outputs/` | 실행 결과 저장 위치입니다. 결과 파일은 원칙적으로 Git 관리 대상이 아닙니다. |

## 평가 데이터 형식

평가 데이터에는 환자 발화와 정답 표준 증상명만 둡니다.
`query term`, `normalized_text`, `LLM symptom name`은 사람이 미리 적지 않고, 실제 파이프라인을 돌려 생성합니다.

```json
{
  "case_id": "eval_001",
  "visit_type": "초진",
  "dialect_type": "standard",
  "question_id": "Q1",
  "text": "어제부터 목이 칼칼하고 코가 막혀요.",
  "gold_symptoms": ["목의 통증", "코막힘"],
  "negative_symptoms": []
}
```

`gold_symptoms`와 `negative_symptoms`는 반드시 `backend/serverless/src/data/symptom_index.json`에 있는 표준 증상명이어야 합니다.

## 1단계: 파이프라인으로 IR 입력 생성

먼저 원본 평가 문장 100개를 실제 백엔드 파이프라인에 통과시켜 IR 평가용 span을 만듭니다.

```powershell
cd C:\Users\CGB\munjin-talk-talk-mvp

python evaluation\ir\run_pipeline_eval.py `
  --input evaluation\ir\data\eval_cases.jsonl `
  --output-dir evaluation\ir\outputs\pipeline
```

주요 출력 파일은 다음과 같습니다.

| 파일 | 확인 내용 |
|---|---|
| `pipeline_ir_eval_cases.jsonl` | IR 평가에 바로 넣을 span 기반 데이터입니다. |
| `pipeline_case_results.jsonl` | 케이스별 전체 파이프라인 결과입니다. |
| `pipeline_stage_summary.json` | validator 통과율, active span 비율, 매칭 가능 케이스 수를 봅니다. |
| `pipeline_span_diagnostics.csv` | LLM이 만든 span의 `type`, `status`, `normalized_text`, `name`을 점검합니다. |
| `pipeline_failure_cases.csv` | 어떤 단계에서 실패했는지 보는 파일입니다. |

## 2단계: 현재 채택안 평가

기본 실행은 현재 MVP 채택안인 `G안 + RRF hybrid + top-20`입니다.

```powershell
python evaluation\ir\run_ir_eval.py `
  --input evaluation\ir\outputs\pipeline\pipeline_ir_eval_cases.jsonl `
  --output-dir evaluation\ir\outputs\ir_g_rrf_top20
```

위 명령은 내부적으로 다음 기본값을 사용합니다.

| 옵션 | 기본값 | 의미 |
|---|---|---|
| `--variants` | `G` | IR top-k 후보 안에서 Pro LLM linker가 최종 증상을 선택합니다. |
| `--top-k` | `20` | 후보 20개를 linker에게 전달합니다. |
| `--score-mode` | `rrf-hybrid` | BM25, Vector, label signal 순위를 RRF로 융합합니다. |
| `--embedding-provider` | `bedrock-titan` | 운영과 같은 Titan embedding을 사용합니다. |

빠르게 IR 후보군만 확인하고 싶으면 LLM linker를 끕니다.

```powershell
python evaluation\ir\run_ir_eval.py `
  --input evaluation\ir\outputs\pipeline\pipeline_ir_eval_cases.jsonl `
  --output-dir evaluation\ir\outputs\ir_candidate_only `
  --skip-llm-judge
```

`--skip-llm-judge`를 쓰고 variant를 지정하지 않으면 `C안`만 평가합니다.

## 비교 실험 명령

아래 명령은 후보 검색 방식만 비교할 때 사용합니다.

```powershell
python evaluation\ir\run_ir_eval.py `
  --input evaluation\ir\outputs\pipeline\pipeline_ir_eval_cases.jsonl `
  --output-dir evaluation\ir\outputs\ir_query_compare `
  --variants "A,B,C" `
  --top-k 20 `
  --score-mode rrf-hybrid `
  --skip-llm-judge
```

아래 명령은 G안과 fallback 실험안을 비교할 때만 사용합니다.
현재 MVP 채택안은 `G`이고, `H/I/J`는 성능 분석용입니다.

```powershell
python evaluation\ir\run_ir_eval.py `
  --input evaluation\ir\outputs\pipeline\pipeline_ir_eval_cases.jsonl `
  --output-dir evaluation\ir\outputs\ir_experimental_compare `
  --variants "G,H,I,J" `
  --top-k 20 `
  --score-mode rrf-hybrid
```

## Variant 설명

| Variant | 의미 | 현재 용도 |
|---|---|---|
| `A` | 원문 quote + 표준어 span + LLM 증상명으로 검색 | 비교 실험 |
| `B` | 표준어 span만 검색 | 비교 실험 |
| `C` | 표준어 span + LLM 증상명으로 검색 | IR 후보군 기준선 |
| `O` | gold 증상명을 query로 넣는 oracle 실험 | 데이터/문서 상한선 확인 |
| `D` | 표준어 span 검색 후 LLM 최종 판단 | 과거 실험 |
| `E` | C 검색 후 deterministic gate | 과거 실험 |
| `F` | E gate 후 LLM 최종 판단 | 과거 실험 |
| `G` | C 검색 후 top-k 후보 안에서 Pro LLM linker | MVP 채택안 |
| `H` | G 실패 시 전체 표준 증상 목록 fallback | 실험안 |
| `I` | IR 없이 전체 표준 증상 목록에서 Pro LLM linker | 상한선 비교 |
| `J` | A/B/C query union 후보를 합쳐 Pro LLM linker | 실험안 |

## 결과 해석

먼저 `summary.json`을 봅니다.

| 지표 | 의미 |
|---|---|
| `candidate_recall@20` | IR 후보 20개 안에 정답 증상이 들어왔는지 봅니다. |
| `candidate_negative_hit@20` | 들어오면 안 되는 부정/호전 증상이 후보에 섞였는지 봅니다. |
| `linker_micro_f1` | Pro linker가 최종 선택한 증상과 gold 증상을 전체 TP/FP/FN 기준으로 비교합니다. |
| `linker_macro_f1` | 케이스별 F1을 평균합니다. |
| `linker_exact_match_rate` | 예측 증상 집합과 정답 증상 집합이 완전히 같은 비율입니다. |
| `linker_false_positive_rate` | 최종 선택 중 오답 비율입니다. |
| `linker_false_negative_rate` | gold 중 놓친 증상 비율입니다. |

그다음 `failure_cases.csv`와 `candidates.csv`를 봅니다.

| 파일 | 보는 법 |
|---|---|
| `failure_cases.csv` | 정답이 top-k에 없어서 실패한 것인지, 후보 안에 있었는데 linker가 못 고른 것인지 구분합니다. |
| `candidates.csv` | 각 후보의 BM25, vector, label, rank score, linker 선택 여부와 이유를 확인합니다. |

## 현재 판단 기준

현재는 다음 조건을 만족하는 조합을 MVP 기준선으로 봅니다.

1. 후보군은 `top-20` 정도로 제한한다.
2. 후보 검색은 `RRF hybrid`를 사용한다.
3. LLM은 후보 밖 증상을 만들 수 없다.
4. full-list fallback은 기본 채택하지 않는다.
5. 평가 보고에서는 `candidate_recall@20`과 `linker_micro_f1`을 함께 제시한다.

이 기준은 의료 문진 서비스에서 중요한 두 가지를 지키기 위한 선택입니다.

- LLM hallucination을 줄이기 위해 closed-set 후보 안에서만 선택하게 합니다.
- 검색 성능과 최종 선택 성능을 분리해, 어디를 개선해야 하는지 설명 가능하게 만듭니다.

## Git 관리 기준

- 공개 가능한 샘플 데이터와 평가 코드만 커밋합니다.
- 실제 평가 데이터, Bedrock 응답 trace, 환자 발화 원문, 실행 결과물은 공개 저장소에 올리지 않습니다.
- `evaluation/ir/outputs/`와 `evaluation/ir/cache/`는 실행 산출물이므로 원칙적으로 커밋하지 않습니다.

# 런타임 데이터 배치 안내

이 폴더는 문진톡톡 백엔드가 질문셋, 방언 RAG, 표준 증상 IR을 수행할 때 참조하는 데이터 위치입니다.

## 현재 런타임 산출물 상태

오염 가능성이 있는 1차 런타임 학습/보강 데이터는 제거했고,
현재 포함된 도메인팩과 few-shot은 `evaluation/train_100_v2`의 승인된 100개 train 문장만 근거로 다시 생성했습니다.

현재 재생성된 항목:

- `domain_packs/respiratory.json`
- `fewshots/respiratory/*.json`
- 도메인팩 내부 alias, symptom rule, safety flag, few-shot 연결
- `evaluation/train_100_v2/artifact_provenance.json`에 산출 근거 case id와 acceptance reason 기록

`domain_packs/respiratory_fewshot.txt` 형식은 더 이상 사용하지 않고, stage별 JSON few-shot만 사용합니다.

## 유지하는 항목

| 경로 | 이유 |
| --- | --- |
| `question_sets/default.json` | 문진 화면의 질문 구조 |
| `dialect_packs/dialect_kangwon.json` | 강원도 사투리 렌더링/검증 참고 자료 |
| `dialect_packs/dialect_kangwon.csv` | 방언팩 원본 관리용 표 데이터 |

## 공개 저장소에 포함하지 않는 파일

| 파일 | 용도 | 제외 이유 |
| --- | --- | --- |
| `diseases_cleaned.json` | 질환 백과 원천 정리본 | 원천 본문과 파생 데이터의 공개 범위 검토 필요 |
| `symptom_index.json` | 표준 증상명과 질환 문서 연결 인덱스 | 원천 데이터 기반 파생 인덱스 |
| `symptom_embeddings_amazon.titan-embed-text-v2_0_512.json` | Titan embedding cache | 원천 증상 문서 기반 파생 벡터 |

## 재구축 원칙

1. `evaluation` 아래에서 생성 설계 문서를 먼저 확정합니다.
2. GPT/LLM으로 `train_100_v2`를 생성합니다.
3. `train_100_v2`만 보고 alias, domain pack, few-shot 후보를 만듭니다.
4. 후보에는 근거 case id와 이유를 남깁니다.
5. 그 뒤 별도 `test_1000`을 생성해 locked test로 평가합니다.

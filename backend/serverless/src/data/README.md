# 런타임 데이터 배치 안내

이 폴더에는 백엔드가 문진 증상 IR을 수행할 때 사용하는 데이터가 들어갑니다.

공개 GitHub에는 저작권 또는 이용 범위 검토가 필요한 원천 의료 백과 본문과 그 파생 데이터가 포함되지 않습니다. 배포 또는 로컬 검증을 진행할 때는 팀 내부에서 관리하는 비공개 데이터 저장소에서 아래 파일을 복사해 넣어야 합니다.

| 파일 | 용도 | 공개 저장소 포함 여부 |
| --- | --- | --- |
| `diseases_cleaned.json` | 질환 백과 원천 정리본 | 제외 |
| `symptom_index.json` | 증상명과 질환 문서 연결 인덱스 | 제외 |
| `symptom_embeddings_amazon.titan-embed-text-v2_0_512.json` | Titan 기반 표준 증상 문서 embedding cache | 제외 |
| `domain_packs/respiratory.json` | 문진톡톡 호흡기 MVP 도메인 설정 | 포함 |
| `domain_packs/respiratory_fewshot.txt` | LLM extraction few-shot 예시 | 포함 |
| `question_sets/default.json` | 초진/재진 문진 질문 세트 | 포함 |

비공개 데이터 파일은 Lambda 패키징 전에 이 폴더에 위치해야 합니다. 파일이 없으면 Hybrid IR 문서 생성 단계가 실행되지 않으므로, SAM 배포 전 반드시 데이터 배치 여부를 확인합니다.

```text
backend/serverless/src/data/
  diseases_cleaned.json
  symptom_index.json
  symptom_embeddings_amazon.titan-embed-text-v2_0_512.json
  domain_packs/
  question_sets/
```

저장소에 다시 추가되지 않도록 `.gitignore`에 위 3개 런타임 데이터 파일 패턴이 등록되어 있습니다.

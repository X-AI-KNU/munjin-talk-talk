# 문진톡톡 Hybrid IR 파이프라인 평가 브랜치

이 브랜치는 문진톡톡 공식 서비스 코드가 아니라, 증상 후보 검색과 Bedrock 기반 문진 분석 파이프라인을 분리해 점검한 평가 자료 브랜치입니다.

공식 서비스 설명과 실행 코드는 [main 브랜치](https://github.com/X-AI-KNU/munjin-talk-talk/tree/main)를 기준으로 봅니다. 이 브랜치는 해커톤 제출 시 "Hybrid IR 후보 검색, 사투리 RAG 힌트, LangGraph/Bedrock 파이프라인 점검 근거"를 따로 보여주기 위해 분리했습니다.

## 평가 질문

문진톡톡은 환자 발화를 바로 LLM 자유 생성 결과로 확정하지 않고, 표준 증상 후보 검색과 검증 단계를 거쳐 의료진 원페이퍼에 표시합니다. 이 브랜치는 그 과정에서 다음 질문을 확인합니다.

```text
환자 발화에서 정답 표준 증상 후보가 검색되는가?
사투리 RAG 힌트는 의도한 행에서만 검색되는가?
Bedrock 추출과 Hybrid IR 연결 후 최종 matched_slots가 기준 증상과 맞는가?
```

## 바로 보기

| 문서/파일 | 내용 |
| --- | --- |
| [평가팩 상세 설명](evaluation/hybrid_ir_pipeline/README.md) | 평가 트랙, 데이터 구조, 실행 방법, 지표 해석 |
| [요약 지표](evaluation/hybrid_ir_pipeline/reports/metrics_summary.json) | Track A/B/C 핵심 수치 |
| [분리 평가 리포트](evaluation/hybrid_ir_pipeline/reports/separated_evaluation_report.md) | Track별 실행 결과 |
| [파이프라인 오류 분석](evaluation/hybrid_ir_pipeline/reports/pipeline_error_analysis.md) | 남은 mismatch와 정책 해석 |
| [평가 설계 문서](evaluation/hybrid_ir_pipeline/design/README.md) | train/test 분리와 평가 원칙 |
| [blueprint 설명](evaluation/hybrid_ir_pipeline/blueprint/README.md) | train_100_v2 생성 설계 |
| [train_100_v2 설명](evaluation/hybrid_ir_pipeline/train_100_v2/README.md) | 렌더링 데이터와 런타임 산출물 |

## 평가 트랙

이 브랜치는 성능을 하나의 숫자로 섞지 않고 세 트랙으로 분리합니다.

| 트랙 | Bedrock 사용 | 확인하는 것 |
| --- | ---: | --- |
| Track A: Offline IR | 아니오 | alias, BM25, combined 후보 검색에 정답 증상이 들어오는지 |
| Track B: Dialect RAG | 아니오 | 강원 사투리 RAG pack에 anchor가 있는 행에서 기대 힌트가 검색되는지 |
| Track C: Pipeline Integration | 예 | 실제 LangGraph/Bedrock 추출, 스키마 검증, Hybrid IR linking이 끝까지 맞는지 |

Track A는 후보 검색 품질이고 최종 모델 F1이 아닙니다. Track C가 실제 파이프라인 동작을 더 가깝게 보여주지만, 현재 데이터는 `train_100_v2`이므로 held-out 성능으로 표현하면 안 됩니다.

## 현재 결과 요약

`evaluation/hybrid_ir_pipeline/reports/metrics_summary.json` 기준입니다.

| 항목 | 값 | 의미 |
| --- | ---: | --- |
| 데이터셋 | `train_100_v2.jsonl` | 100개 synthetic train/inspection set |
| held-out 여부 | false | 최종 테스트셋 아님 |
| Track A combined recall@1 | 0.8198 | top-1 후보에 정답 증상이 들어간 비율 |
| Track A combined recall@5 | 1.0000 | top-5 후보에 정답 증상이 들어간 비율 |
| Track B rag-pack anchored recall | 1.0000 | anchor가 있는 10개 행에서 기대 방언 힌트 검색 성공 |
| Track B non-anchor hint rate | 0.0000 | anchor가 아닌 강원체 행에서 불필요 힌트가 나온 비율 |
| Track C completed rows | 100/100 | 파이프라인 완료 행 수 |
| Track C precision | 1.0000 | 최종 matched_slots의 오탐 방지 |
| Track C recall | 0.9279 | 기준 active 증상 중 최종 매칭된 비율 |
| Track C F1 | 0.9626 | precision/recall 조화 평균 |
| schema/runtime failures | 0 | 스키마 또는 런타임 실패 없음 |
| source quote grounding rate | 1.0000 | source quote가 원문에 근거한 비율 |
| negative false-positive rate | 0.0000 | 부정 증상을 active 증상으로 잘못 올린 비율 |

Track A의 `negative_in_top5_rate`는 후보 목록 안에 부정 증상 후보가 들어오는지를 보는 진단 지표입니다. 최종 원페이퍼 오탐률은 Track C의 `negative_false_positive_rate`를 봐야 하며, 현재 값은 0.0000입니다.

## 남은 mismatch 해석

최종 run의 남은 mismatch는 8개 false negative이며, 모두 `progress_improved/status=없음` 계열입니다. 예를 들어 "호흡곤란이 조금 나아졌지만 여전히 힘들 때가 있음", "기운없음이 조금 나아짐" 같은 표현입니다.

현재 제품 정책은 `progress_improved`와 `symptom_absent`를 active symptom card나 IR `matched_slots`에 올리지 않고, follow-up context/clinical clue로 보존합니다. 따라서 남은 recall 손실은 후보 검색 실패라기보다 "평가 정답에는 포함됐지만 제품 정책상 active symptom으로 올리지 않는 항목"에서 생긴 scoring-policy mismatch입니다.

## 제출 시 해석 기준

다음처럼 표현하는 것은 적절합니다.

- train_100_v2 기준으로 후보 검색, 사투리 RAG, 실제 Bedrock 파이프라인을 분리 평가했다.
- Offline IR combined recall@5는 1.0이었고, 실제 Track C pipeline F1은 0.9626이었다.
- 남은 mismatch는 제품 정책상 active symptom으로 올리지 않는 개선/해소 계열에서 발생했다.
- 최종 held-out 성능은 별도 고정 테스트셋 생성 후 첫 실행 리포트가 필요하다.

다음처럼 표현하면 안 됩니다.

- Track A recall@5를 최종 모델 F1로 표현
- `train_100_v2` 결과를 held-out 성능으로 표현
- 임상 진단 정확도나 처방 성능으로 해석
- 전체 병원 실데이터에서 검증된 성능으로 주장

이 브랜치는 "최종 성능 자랑"이 아니라, 파이프라인의 어느 단계가 잘 되고 어디가 정책적으로 남는지 분해해서 보여주는 평가 기록입니다.

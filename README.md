# 문진톡톡 Hybrid IR 및 파이프라인 컴포넌트 분리 평가 명세

본 브랜치(`eval/hybrid-ir-pipeline`)는 문진톡톡 메인 서비스 코드와 분리되어, **증상 후보 검색 엔진(IR)** 과 **LLM 기반 구조화 파이프라인(Bedrock)** 의 성능 병목을 독립적으로 검증하기 위한 탐색적 평가(Exploratory Evaluation) 환경입니다.

공식 서비스 아키텍처 및 Held-out 벤치마크는 [main 브랜치](https://github.com/X-AI-KNU/munjin-talk-talk/tree/main)를 기준으로 합니다. 본 브랜치는 해커톤 심사 및 기술 검토 과정에서 **"Hybrid IR 엔진의 후보 풀링 성능, 사투리 RAG의 힌트 타당성, LangGraph 제어 흐름의 정합성"** 을 컴포넌트 단위로 분해하여 입증하기 위해 별도 구축되었습니다.

---

## 1. 컴포넌트 분리 평가 목적 (Evaluation Tracks)

문진톡톡은 환자의 모호한 발화를 LLM의 자의적 생성(Free-form generation)에 맡기지 않습니다. 본 평가는 파이프라인을 3개의 독립 트랙으로 해체하여, 각 구간이 설계 의도대로 작동하는지 정밀 타격하여 검증합니다.

| 트랙 구분 | 타깃 컴포넌트 | LLM 개입 | 검증 핵심 지표 |
| :---: | --- | :---: | --- |
| **Track A** | `Offline IR` | ❌ | BM25 + Vector 통합 검색 시 정답 표준 증상이 상위 후보군(Top-K) 내에 안정적으로 회수(Recall)되는가? |
| **Track B** | `Dialect RAG` | ❌ | 강원 사투리가 포함된 발화에서만 정확히 RAG 힌트가 트리거되며, 불필요한 일반 발화에서는 개입을 차단하는가? |
| **Track C** | `Pipeline Integration` | ⭕ | LLM 추출 $\rightarrow$ 스키마 검증 $\rightarrow$ IR 링킹으로 이어지는 전체 파이프라인이 임상 정책에 맞게 `matched_slots`를 최종 확정하는가? |

*(참고: Track A는 순수 검색 엔진의 품질(Pooling)을 재는 지표이며, 파이프라인의 최종 성능을 대변하지 않습니다. 실제 운영 성능과 가장 유사한 것은 LLM이 개입된 Track C입니다.)*

---

## 2. 참조 아티팩트 색인

| 문서/파일 링크 | 포함 내용 및 역할 |
| --- | --- |
| [평가팩 상세 설명](evaluation/hybrid_ir_pipeline/README.md) | 트랙별 아키텍처, 데이터 스키마, CLI 실행 방법, 지표 해석 가이드 |
| [요약 지표 스냅샷](evaluation/hybrid_ir_pipeline/reports/metrics_summary.json) | Track A/B/C 파이프라인 관통 후 산출된 핵심 정량 수치 |
| [분리 평가 리포트](evaluation/hybrid_ir_pipeline/reports/separated_evaluation_report.md) | 각 트랙별 세부 실행 로그 및 성공/실패 케이스 덤프 |
| [오류 분석 및 정책 해석](evaluation/hybrid_ir_pipeline/reports/pipeline_error_analysis.md) | 파이프라인 Mismatch 요인 분석 및 임상 정책 타당성 해설 |
| [데이터셋 설계 문서](evaluation/hybrid_ir_pipeline/design/README.md) | Train/Test 스플릿 원칙 및 합성 데이터 생성 방법론 |
| [평가 트랙 상세 설계](evaluation/hybrid_ir_pipeline/design/evaluation_tracks.md) | Offline IR, Dialect RAG, Pipeline Integration 트랙별 분리 평가 기준 |
| [train_100_v2 Blueprint 초안](evaluation/hybrid_ir_pipeline/design/train_100_v2_blueprint_draft.md) | 100건 개발용 벤치마크 데이터 생성 전 설계 명세 |
| [Blueprint 산출물 설명](evaluation/hybrid_ir_pipeline/blueprint/README.md) | 케이스 블루프린트, 분포 계획, 품질 게이트 리포트 설명 |
| [train_100_v2 명세](evaluation/hybrid_ir_pipeline/train_100_v2/README.md) | 본 평가에 사용된 100건의 개발용 벤치마크 데이터 스키마 |
| [평가 실행 스크립트](evaluation/hybrid_ir_pipeline/run_separated_evaluation.py) | Track A/B/C 분리 평가 실행 러너 |

---

## 3. 평가 지표 요약 (`metrics_summary.json` 기준)

본 지표는 파이프라인 최적화를 위해 구축된 `train_100_v2.jsonl` (100건) 데이터를 기준으로 산출되었습니다. 

| 평가 지표명 | 산출값 | 엔지니어링 및 임상적 의의 |
| --- | ---: | --- |
| **Track A: Combined Recall@5** | **1.0000** | 엔진이 상위 5개 후보 안에 정답 증상을 100% 가져옴 (IR 병목 해소) |
| **Track B: Anchored Recall** | **1.0000** | 사투리가 포함된 10개 타깃 행에서 기대 방언 힌트 주입 100% 성공 |
| **Track B: Non-anchor Hint Rate**| **0.0000** | 표준어 발화 행에서 불필요한 사투리 RAG 힌트가 개입한 비율 0% (노이즈 차단) |
| **Track C: Precision (오탐 방어)**| **1.0000** | AI가 최종 확정한 증상 슬롯 중 오진(False Positive) 비율 0% |
| **Track C: Recall (회수율)** | **0.9279** | 기준 Active 증상 중 최종 매칭된 비율 |
| **Track C: End-to-End F1 Score** | **0.9626** | **파이프라인 통합 조화 평균** |
| **Schema/Runtime Failures** | **0** | LLM 스키마 포맷 오류 및 런타임 크래시 발생 건수 0 |
| **Source Quote Grounding Rate** | **1.0000** | 생성된 모든 근거가 환자 원문 문자열에 100% 실재함 (환각 원천 차단) |

---

## 4. 의도된 False Negative의 해석 (Clinical Policy Mismatch)

Track C의 최종 파이프라인 실행 결과, 8건의 False Negative(Recall 손실)가 발생했습니다. 이 8건의 데이터는 모두 `"호흡곤란이 나아졌지만 여전히 힘들 때가 있다"`, `"기운 없음이 조금 나아졌다"`와 같은 **호전(progress_improved)** 맥락이 섞인 케이스입니다.

이는 검색 엔진의 성능 부족이나 LLM의 실패가 아닙니다. **현행 문진톡톡의 임상 안전 정책(Clinical Safety Policy)이 의도한 설계의 결과입니다.** 본 시스템은 부분적으로라도 호전된 증상(`progress_improved`)이나 현재 없어진 증상(`symptom_absent`)을 진료실 모니터 최상단의 **[오늘의 활성 증상 카드(Active Symptom)]** 로 띄우지 않습니다. 대신 이를 `clinical_clues` (임상 단서) 객체로 안전하게 격리하여 의료진이 후속 문맥으로만 참고하도록 라우팅합니다.

따라서 현재의 Recall 손실은 시스템의 오류가 아닌, **평가셋의 정답 레이블 기준과 프로덕션의 엄격한 라우팅 정책 간의 불일치(Policy Mismatch)** 로 해석하는 것이 타당합니다.

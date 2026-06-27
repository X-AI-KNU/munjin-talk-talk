# 문진톡톡 Hybrid IR 파이프라인 평가 아키텍처 가이드

이 문서는 `eval/hybrid-ir-pipeline` 브랜치 진입 시 가장 먼저 검토해야 하는 아키텍처 평가 설명서입니다.

> **💡 본 브랜치의 존재 의의**
> *"문진톡톡은 LLM에게 환자의 증상 판단을 블랙박스 형태로 전면 위임한 서비스가 아닙니다. 본 평가는 후보 검색, 사투리 힌트, Bedrock 구조화 파이프라인을 컴포넌트별로 철저히 분리 검증하여 시스템의 무결성을 입증하기 위한 엔지니어링 근거입니다."*

---

## 1. 컴포넌트 분리 평가의 당위성

문진톡톡은 환자 발화를 즉시 진단명이나 표준 증상명으로 확정 짓지 않습니다. 환자의 발화를 구조화한 뒤, 표준 증상 후보 검색을 수행하고, 최종적으로 임상 정책에 부합하는 슬롯만을 `matched_slots`로 승격시킵니다. 

LLM 기반 문진에서는 아래와 같은 다중 위험 지점이 존재하므로 하나의 점수(F1)로 뭉개어 평가하는 것은 위험합니다.

* 후보 검색(IR)이 정답 표준 증상을 아예 회수하지 못할 리스크
* 사투리 RAG가 불필요한 표준어 문장에 과도하게 개입할 리스크
* LLM이 지정된 JSON 스키마를 위반할 런타임 리스크
* 환자 원문에 존재하지 않는 환각 데이터를 `source_quote`로 날조할 리스크
* 호전되었거나 부재한 증상을 '활성 증상(Active Symptom)'으로 오분류할 리스크

따라서 본 브랜치는 **Track A(Offline IR)**, **Track B(Dialect RAG)**, **Track C(Pipeline Integration)** 로 구간을 분리하여 어느 단계가 방어에 성공하고 있는지 투명하게 증명합니다.

---

## 2. 벤치마크 데이터셋 스키마 요약

현재 산출된 결과는 `train_100_v2/train_100_v2.jsonl`에 수록된 100건의 합성(Synthetic) 문진 발화 데이터를 기준으로 합니다.

| 임상 분포 항목 | 설계 구성 비율 |
| --- | --- |
| **방문 및 문항 분포** | 초진 Q1 50건, 재진 Q3 50건 |
| **언어 스타일 분포** | 표준어 50건, 강원식 구어체 50건 |
| **방언 주입 레이어** | `none` 50건, `clinical_colloquial` 25건, `rag_pack_anchored` 10건, `light_dialect_style` 15건 |
| **임상 상태 패턴** | 활성(`active_current`), 재발/만성(`recurrent_or_persistent`), 호전(`improved_or_resolved`), 부재(`denied_negative_context`), 복합 맥락(`mixed_context`) |

*(⚠️ **데이터 해석 시 주의:** 강원식 구어체 50건 전체를 방언팩 근거 사례로 포장하지 않습니다. 실제 방언팩 앵커가 주입된 10건만을 `rag_pack_anchored`로 엄격히 격리하였으며, Track B는 오직 이 10건에서만 기대 힌트가 정확히 트리거되는지 검증합니다.)*

---

## 3. 남은 8건 Mismatch의 아키텍처적 해석

Track C 관통 후 발생한 8건의 False Negative(회수 손실)는 모두 `progress_improved`(호전) 또는 `symptom_absent`(부재) 계열입니다.

**[필터링된 원문 예시]**
* *"인후통은 조금 나아졌지만 여전히 힘들 때가 있음"* / *"열이 나아진 것 같음"*
* *"피로감은 완화됐지만 근육통은 현재 남음"* / *"목소리 변화가 조금 나아짐"*

이 결과는 검색 엔진이나 LLM의 실패가 아닙니다. 현행 제품 정책은 호전/해소된 증상을 진료실 화면의 Active Symptom 카드로 올리지 않고, `follow-up context`나 `clinical clue`로 격리하여 보존합니다. 즉, 이는 오류가 아니라 **평가 정답 레이블(개선 계열도 회수로 취급)과 제품의 안전 라우팅 정책(제외) 간의 Scoring-Policy Mismatch**입니다.

---

## 4. 디렉터리 레이아웃 및 구동 CLI

```text
evaluation/hybrid_ir_pipeline/
├── README.md                            # 본 마스터 규격서
├── run_separated_evaluation.py          # 평가 자동화 러너
├── blueprint/                           # 데이터 분포 기획 및 품질 게이트
├── train_100_v2/                        # 렌더링 완료된 100건 데이터셋 및 빌더
└── reports/                             # 고정 지표 스냅샷 및 오류 분석서
```

**[실행 스크립트]** (AWS 인증 프로필 사전 구성 필수)
```bash
python evaluation/hybrid_ir_pipeline/run_separated_evaluation.py \
  --dataset evaluation/hybrid_ir_pipeline/train_100_v2/train_100_v2.jsonl \
  --out-dir evaluation/hybrid_ir_pipeline/reports/run_latest
```
*(Track C는 Bedrock을 실제 호출하므로 실행별 Raw Trace 로그나 임시 디렉터리는 Git에 커밋하지 않습니다.)*

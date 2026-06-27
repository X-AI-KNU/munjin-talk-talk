# 문진톡톡 AI 성능 평가 프레임워크

이 디렉터리(`evaluation/`)는 문진톡톡 핵심 파이프라인의 임상적 정합성과 검색 성능을 정량적으로 측정하고, 이를 결정론적(Deterministic)으로 재현하기 위한 평가 패키지입니다.

문진톡톡의 성능 평가는 단순히 "LLM이 문장을 매끄럽게 생성하는가"를 보지 않습니다. 환자의 비정형 음성 발화를 구조화하고, 원문 인용 근거(`source_quote`)를 대조한 뒤, 서울아산병원 질병백과 기반 표준 증상 인덱스로 최종 매핑하는 **전체 흐름의 정답률**을 검증합니다. 

이에 따라 본 프레임워크는 평가 체계를 두 개의 독립 레이어로 분리하여 수행합니다.

| 평가 레이어 | 핵심 검증 질문 | 관점 및 목적 |
| --- | --- | --- |
| **End-to-End 문진 파이프라인** | 환자 발화에서 실제 증상을 누락 없이 추출하고 표준 증상명으로 정확히 연결했는가 | 실제 의료진 및 환자가 체감하는 최종 서비스 정합성 측정 |
| **Hybrid IR 후보 검색** | 정답 표준 증상이 상위 후보군(Top-K) 이내에 안정적으로 안착하는가 | LLM 추론 이후 단계인 검색 및 매칭 엔진의 병목 분리 측정 |

---

## 1. 브랜치 전략 및 거버넌스

공식 보고용 요약 데이터는 `main` 브랜치에 유지하며, 탐색적 성격이 강한 세부 파라미터 실험은 독립 브랜치로 격리하여 관리합니다.

| 자료 경로 | main과의 관계 | 주요 내용 및 역할 |
| --- | --- | --- |
| `main/evaluation` | **공식 기준(Master)** | 공식 End-to-End 벤치마크 요약, 재현 가능한 샘플셋, 표준 평가 스크립트 |
| [`eval/dialect-rag`](https://github.com/X-AI-KNU/munjin-talk-talk/tree/eval/dialect-rag) | 보조 실험 산출물 | 강원 사투리 및 구어체를 표준어 보조 문장으로 치환할 때의 의미 보존율 분석 |
| [`eval/hybrid-ir-pipeline`](https://github.com/X-AI-KNU/munjin-talk-talk/tree/eval/hybrid-ir-pipeline) | 보조 실험 산출물 | IR 후보군 검색 스코어링 튜닝 및 Bedrock 파이프라인 구간별 지연시간(Latency) 병목 분석 |
| [`test/add-coverage`](https://github.com/X-AI-KNU/munjin-talk-talk/tree/test/add-coverage) | 검증 인프라 근거 | 로컬 모의 객체(Stub) 테스트 및 AWS 런타임 통합 테스트 커버리지 확장 |

> **심사위원 안내:** 공식 피칭 및 제출 서류에 기재된 최종 성능 지표는 `main/evaluation`의 산출물을 기준으로 합니다. 세부 실험 브랜치는 아키텍처 설계의 의사결정 배경과 한계점 극복 과정을 입증하는 참고 자료입니다.

---

## 2. 공개 폴더 구조

```text
evaluation/
├── README.md                         # 평가 프레임워크 구조 및 지표 해석 가이드
├── requirements.txt                  # 평가 환경 구동용 독립 의존성 패키지
├── datasets/
│   └── eval_cases.sample.jsonl       # 외부 공개 및 재현 가능한 샘플 평가 입력셋
├── scripts/
│   ├── run_eval_suite.py             # E2E Span 추출 + IR 매칭 통합 벤치마크 실행기
│   ├── run_pipeline_eval.py          # 운영 파이프라인 기반 Span 생성 평가기
│   ├── run_ir_eval.py                # IR 후보 검색 및 Linker 매칭 정밀 평가기
│   └── embedding_providers.py        # Amazon Titan / Local 임베딩 연동 인터페이스
└── reports/
    └── performance_summary.md        # 공식 제출용 성능 평가 요약 보고서
```

본 공개 저장소에는 실행 스크립트, 검증용 샘플 데이터, 최종 보고서만 포함됩니다. 개인정보가 포함될 수 있는 대량 평가 데이터 원본, LLM Raw Response, Prompt 전문, 임베딩 캐시 파일은 보안 규정에 의해 원격 저장소에 업로드하지 않습니다.

---

## 3. 평가 데이터 규격

평가 입력셋에는 **환자의 발화 원문(`text`)**과 **전문 임상가가 레이블링한 표준 증상명(`gold_symptoms`)**만 기입합니다. 

`normalized_text`, `symptom_hint`, IR Query 등 중간 가공 텍스트는 평가셋에 미리 입력해 두지 않고 런타임 파이프라인이 직접 생성하도록 강제합니다. 이를 통해 실제 운영 환경에서 발생할 수 있는 LLM의 추출 오차와 IR 검색 오차를 벤치마크 지표에 온전히 반영합니다.

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
*(주의: `gold_symptoms` 및 `negative_symptoms`에 할당되는 문자열은 반드시 백엔드 런타임의 `symptom_index.json`에 정의된 표준 의학 증상명 규격과 정확히 일치해야 합니다.)*

---

## 4. 벤치마크 실행 방법

### Step 1. 의존성 설치
프로젝트 루트 경로에서 평가 전용 패키지를 설치합니다.

```powershell
pip install -r evaluation\requirements.txt
```

### Step 2. 통합 벤치마크 실행 (E2E + IR)
샘플 데이터셋을 기반으로 파이프라인 추론과 증상 매칭 평가를 연속 실행합니다.

```powershell
python evaluation\scripts\run_eval_suite.py `
  --input evaluation\datasets\eval_cases.sample.jsonl `
  --output-dir evaluation\outputs\sample_run `
  --top-k 20
```

### Step 3. 모듈별 분리 실행 (선택)
LLM 추출 구간과 IR 검색 구간을 개별 디버깅할 경우 아래 명령어를 사용합니다.

```powershell
# 1. 파이프라인 Span 생성 평가
python evaluation\scripts\run_pipeline_eval.py `
  --input evaluation\datasets\eval_cases.sample.jsonl `
  --output-dir evaluation\outputs\pipeline

# 2. 생성된 결과 기반 IR 후보 매칭 평가
python evaluation\scripts\run_ir_eval.py `
  --input evaluation\outputs\pipeline\pipeline_ir_eval_cases.jsonl `
  --output-dir evaluation\outputs\ir_g_rrf_top20 `
  --top-k 20
```

---

## 5. 핵심 평가 지표 지침

| 지표명 | 수식 및 정의 | 임상적 의의 |
| --- | --- | --- |
| `Precision` | $\text{True Positives} / (\text{True Positives} + \text{False Positives})$ | AI가 제시한 증상 중 실제 환자의 호소 증상이 맞은 비율 (과잉 진단 방어력) |
| `Recall` | $\text{True Positives} / (\text{True Positives} + \text{False Negatives})$ | 환자의 실제 증상 중 AI가 놓치지 않고 찾아낸 비율 (**진료 보조의 핵심 안전성**) |
| `F1 Score` | $2 \times (\text{Precision} \times \text{Recall}) / (\text{Precision} + \text{Recall})$ | 정밀도와 재현율의 조화 평균 |
| `candidate_recall@k` | 정답 표준 증상이 IR 검색 결과 상위 $k$개 후보 안에 포함된 비율 | 하이브리드 검색 엔진의 검색 공간 풀링(Pooling) 성능 측정 |
| `negative_hit@k` | 호전됨, 증상 없음 등 부정 맥락이 활성 후보군에 노이즈로 섞인 비율 | 문맥 필터링 로직의 오작동률 감시 |
| `exact_match_rate` | 케이스 단위로 정답 증상 리스트가 100% 완벽히 일치한 케이스의 비중 | 가장 보수적인 지표로서의 파이프라인 무결성 확인 |

---

## 6. 공식 성능 요약 및 해석 원칙

상세 벤치마크 리포트는 [reports/performance_summary.md](reports/performance_summary.md)에 수록되어 있습니다. 핵심 요약은 다음과 같습니다.

* **Focused Benchmark (150 cases):** 일반 외래 호흡기 문진 시나리오에 집중한 테스트셋에서 **End-to-End F1 0.8934**를 달성했습니다. 이는 본 솔루션이 타깃으로 하는 '외래 주호소 파악' 환경에서의 실질 정합성을 보여줍니다.
* **Held-out Benchmark (500 cases):** 복합 질환 Confounder, 중증 응급 징후, 모호한 구어체를 고도로 혼합한 통제 환경에서는 **End-to-End F1이 약 0.75 수준**으로 수렴합니다.

지표가 하락하는 가혹 조건(Held-out) 실험 수치를 투명하게 공개하는 이유는 명확합니다. 문진톡톡의 아키텍처는 **불확실한 상황에서 임의로 병명을 찍어내는 위험한 범용 진단기**가 되지 않도록 보수적으로 설계되었습니다. 매칭 확신이 부족할 때는 LLM이 억지로 표준 병명을 할당하지 않고 원문 발화(`unmatched_spans`) 상태로 남겨 의료진의 검토 대기열로 넘기는 안전장치가 작동하기 때문입니다.

---

## 7. `.gitignore` 통제 기준

평가 환경에서 생성되는 로컬 대량 데이터 및 파생 캐시는 형상 관리에서 엄격히 제외합니다.

```text
evaluation/datasets/eval_cases.jsonl
evaluation/outputs/
evaluation/cache/
evaluation/reports/generated/
```

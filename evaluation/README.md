# 문진톡톡 하이브리드 검증 프레임워크 (Evaluation Directory)

본 디렉터리는 `eval/hybrid-ir-pipeline` 브랜치에서 수행한 파이프라인 성능 검증 자료의 최상위 진입점입니다. 

공식 서비스 아키텍처, 배포 방법, 사용자 화면 흐름은 `main` 브랜치의 문서를 표준으로 삼습니다. 반면 본 브랜치의 `evaluation/` 디렉터리는 **Hybrid IR, 사투리 RAG, Bedrock 기반 구조화 파이프라인을 컴포넌트 단위로 분리하여 검증한 아키텍처 리포트**를 제공하기 위해 격리되었습니다.

> **💡 핵심 기준**
> LLM의 자의적 텍스트 생성(Free-form Generation) 결과를 맹신하지 않습니다. 후보 검색(IR), 방언 힌트 검색, Bedrock 추출/검증/링킹 과정을 **독립적인 컴포넌트로 디커플링(Decoupling)** 하여, 어느 구간이 안정적으로 작동하고 어느 구간에 보완이 필요한지 정밀 추적합니다.

---

## 1. 참조 아티팩트 색인 (Quick Links)

| 위치 | 역할 |
| --- | --- |
| [hybrid_ir_pipeline/README.md](hybrid_ir_pipeline/README.md) | Track A/B/C 평가 구조, 데이터셋, 지표, 실행 방법을 총망라한 평가팩 메인 문서 |
| [hybrid_ir_pipeline/reports/metrics_summary.json](hybrid_ir_pipeline/reports/metrics_summary.json) | 100건 `train_100_v2` 기준 요약 지표 스냅샷 |
| [hybrid_ir_pipeline/reports/separated_evaluation_report.md](hybrid_ir_pipeline/reports/separated_evaluation_report.md) | Track A/B/C 분리 평가 결과 리포트 |
| [hybrid_ir_pipeline/reports/pipeline_error_analysis.md](hybrid_ir_pipeline/reports/pipeline_error_analysis.md) | 남은 mismatch 8건의 원인 분석 및 임상 정책 해석 |
| [hybrid_ir_pipeline/design/README.md](hybrid_ir_pipeline/design/README.md) | 평가 재설계 배경, train/test 분리 원칙, 데이터 설계 기준 명세 |
| [hybrid_ir_pipeline/design/evaluation_tracks.md](hybrid_ir_pipeline/design/evaluation_tracks.md) | Offline IR, Dialect RAG, Pipeline Integration, Product E2E 트랙 정의서 |
| [hybrid_ir_pipeline/blueprint/README.md](hybrid_ir_pipeline/blueprint/README.md) | 100건 평가 데이터 생성 전 row-level 시나리오 분포 설계도 |
| [hybrid_ir_pipeline/train_100_v2/README.md](hybrid_ir_pipeline/train_100_v2/README.md) | 렌더링 완료된 100건 synthetic 문진 데이터 및 산출물 설명 |

---

## 2. 디렉터리 토폴로지

```text
evaluation/
└── hybrid_ir_pipeline/
    ├── README.md
    ├── run_separated_evaluation.py
    ├── blueprint/
    ├── design/
    ├── train_100_v2/
    └── reports/
```

---

## 3. 컴포넌트 분리 평가 파이프라인 시퀀스

데이터 설계부터 컴포넌트별 타격 검증까지 결정론적으로 수행되는 시퀀스입니다.

```text
blueprint 설계
  -> train_100_v2 문진 발화 렌더링
  -> 평가용 domain pack / few-shot 후보 산출
  -> Track A: Offline IR 후보 검색 평가
  -> Track B: Dialect RAG hint 검색 평가
  -> Track C: Bedrock/LangGraph 통합 파이프라인 평가
  -> reports 요약 및 mismatch 분석
```

---

## 4. Main 브랜치와의 아키텍처 책임 경계

`main` 브랜치는 실제 프로덕션 서비스 코드와 공식 설명 문서의 마스터 기준입니다. 본 브랜치는 운영 서비스 동작을 대체하지 않으며, 해커톤 심사 과정에서 제기될 수 있는 아래의 **아키텍처 검증 질문**에 명쾌하게 답하기 위한 엔지니어링 근거(Evidence)로 기능합니다.

| 아키텍처 검증 질문 | 해답을 제공하는 평가 트랙 및 문서 |
| --- | --- |
| 표준 증상 후보가 검색 단계에서 누락되지 않는가 | `Track A: Offline IR` |
| 사투리 힌트가 필요한 곳에서만 검색되는가 | `Track B: Dialect RAG Sanity` |
| Bedrock 추출과 IR 링킹을 거친 최종 결과가 안전한가 | `Track C: Pipeline Integration` |
| 남은 false negative가 시스템 오류인지 정책 차이인지 | `pipeline_error_analysis.md` |

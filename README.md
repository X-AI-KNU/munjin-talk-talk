# 문진톡톡 사투리 RAG 평가 브랜치

이 브랜치는 실제 서비스 공식 코드가 아니라 사투리 RAG 의미 보존 평가 자료를 정리한 브랜치입니다.

## 바로 보기

- [사투리 RAG 평가 설명](evaluation/dialect_rag/README.md)
- [평가 요약 지표](evaluation/dialect_rag/reports/summary.json)
- [실패 케이스](evaluation/dialect_rag/reports/failed_cases.csv)
- [평가 데이터](evaluation/dialect_rag/data/dialect_norm_eval_200.jsonl)

## 해석 기준

이 평가는 200개 synthetic/starter set에 대한 의미 보존 점검입니다. 병원 실데이터 전체 성능이나 임상 일반화 성능을 주장하는 벤치마크가 아닙니다.

공식 서비스 설명은 [main 브랜치](https://github.com/X-AI-KNU/munjin-talk-talk/tree/main)를 참고하세요.

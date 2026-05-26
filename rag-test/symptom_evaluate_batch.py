"""
run_batch_symptom_eval.py

20개 이상의 테스트 프롬프트를 자동 실행하고,
Bedrock RAG 증상 매핑 결과를 expected_symptoms와 비교해 JSON으로 저장한다.

필수 조건:
1. 이 파일, test_prompts.json, symptom_matcher_bedrock_with_log.py가 같은 폴더에 있어야 함.
2. PowerShell 환경변수 설정 필요:
   $env:AWS_REGION="ap-northeast-2"
   $env:BEDROCK_KB_ID="네_Knowledge_Base_ID"
   $env:BEDROCK_MODEL_ID="global.amazon.nova-2-lite-v1:0"

실행:
python run_batch_symptom_eval.py --test-file test_prompts.json --output symptom_eval_results.json

프롬프트까지 상세 저장:
python run_batch_symptom_eval.py --test-file test_prompts.json --output symptom_eval_results.json --include-prompts
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from symptom_matcher_bedrock_with_log import match_symptoms_with_trace


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_test_cases(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("test_prompts.json은 리스트 형태여야 합니다.")
    return data


def symptom_names(items: list[dict[str, Any]]) -> list[str]:
    names = []
    for item in items or []:
        name = item.get("symptom_name")
        if name and name not in names:
            names.append(name)
    return names


def evaluate(expected: list[str], predicted: list[str]) -> dict[str, Any]:
    expected_set = set(expected)
    predicted_set = set(predicted)

    correct = sorted(expected_set & predicted_set)
    missing = sorted(expected_set - predicted_set)
    extra = sorted(predicted_set - expected_set)

    precision = len(correct) / len(predicted_set) if predicted_set else 0.0
    recall = len(correct) / len(expected_set) if expected_set else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall > 0
        else 0.0
    )

    return {
        "expected": sorted(expected_set),
        "predicted": sorted(predicted_set),
        "correct": correct,
        "missing": missing,
        "extra": extra,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "exact_match": expected_set == predicted_set,
    }


def compact_record(record: dict[str, Any], include_prompts: bool) -> dict[str, Any]:
    """평가 파일이 너무 커지지 않도록 필요한 정보만 저장."""
    result = record.get("result") or {}
    retrieval = record.get("retrieval") or {}

    compact = {
        "record_id": record.get("record_id"),
        "status": record.get("status"),
        "started_at": record.get("started_at"),
        "completed_at": record.get("completed_at"),
        "duration_ms": record.get("duration_ms"),
        "input": record.get("input"),
        "config": record.get("config"),
        "retrieval": {
            "candidate_count": retrieval.get("candidate_count"),
            "candidate_names": retrieval.get("candidate_names"),
        },
        "result": result,
        "error": record.get("error"),
        "model": {
            "raw_output": (record.get("model") or {}).get("raw_output"),
        },
    }

    if include_prompts:
        compact["prompts"] = record.get("prompts", {})

    return compact


def run_batch(
    test_cases: list[dict[str, Any]],
    include_prompts: bool = False,
    number_of_results: int = 25,
) -> dict[str, Any]:
    records = []
    metrics = []

    for case in test_cases:
        case_id = case.get("id")
        input_text = case["input"]
        expected = case.get("expected_symptoms", [])

        print(f"[RUN] id={case_id} input={input_text}")

        record = match_symptoms_with_trace(
            user_text=input_text,
            number_of_results=number_of_results,
            include_prompts=include_prompts,
        )

        compact = compact_record(record, include_prompts=include_prompts)

        result = record.get("result") or {}
        predicted = symptom_names(result.get("matched_symptoms", []))
        possible = symptom_names(result.get("possible_symptoms", []))

        eval_result = evaluate(expected, predicted)

        compact["test_case"] = {
            "id": case_id,
            "expected_symptoms": expected,
        }
        compact["evaluation"] = eval_result
        compact["possible_symptom_names"] = possible

        records.append(compact)
        metrics.append(eval_result)

        print(
            f"  precision={eval_result['precision']} "
            f"recall={eval_result['recall']} "
            f"f1={eval_result['f1']} "
            f"exact={eval_result['exact_match']}"
        )

    total = len(records)
    exact_count = sum(1 for m in metrics if m["exact_match"])
    error_count = sum(1 for r in records if r.get("status") == "error")

    summary = {
        "total_cases": total,
        "success_cases": total - error_count,
        "error_cases": error_count,
        "exact_match_count": exact_count,
        "exact_match_rate": round(exact_count / total, 4) if total else 0.0,
        "avg_precision": round(statistics.mean(m["precision"] for m in metrics), 4) if metrics else 0.0,
        "avg_recall": round(statistics.mean(m["recall"] for m in metrics), 4) if metrics else 0.0,
        "avg_f1": round(statistics.mean(m["f1"] for m in metrics), 4) if metrics else 0.0,
    }

    return {
        "schema_version": "1.0",
        "created_at": now_iso(),
        "summary": summary,
        "records": records,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-file", default="test_prompts.json")
    parser.add_argument("--output", default="symptom_eval_results.json")
    parser.add_argument("--include-prompts", action="store_true")
    parser.add_argument("--number-of-results", type=int, default=25)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    test_cases = load_test_cases(args.test_file)
    result = run_batch(
        test_cases=test_cases,
        include_prompts=args.include_prompts,
        number_of_results=args.number_of_results,
    )

    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n[DONE]")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()

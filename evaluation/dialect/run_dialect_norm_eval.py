#!/usr/bin/env python3
"""문진톡톡 사투리→표준어 변환 성능 평가 스크립트.

평가 대상:
  backend/serverless/src/dialect_normalization.py 의 normalize_dialect_text()

주요 기능:
  - 사투리/구어체 문장과 gold 표준어 문장을 비교
  - 방언 치환 precision/recall/F1 계산
  - 선택적으로 Bedrock Nova Lite judge로 의미 보존/새 사실 추가 여부 판정
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_JUDGE_MODEL_ID = "apac.amazon.nova-lite-v1:0"
DEFAULT_JUDGE_MAX_TOKENS = 500

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = PROJECT_ROOT / "backend" / "serverless" / "src"
sys.path.insert(0, str(BACKEND_SRC))

try:
    from dialect_normalization import normalize_dialect_text  # type: ignore
except ModuleNotFoundError as exc:
    raise SystemExit(
        "backend/serverless/src 모듈을 import하지 못했습니다.\n"
        "이 파일을 munjin-talk-talk/evaluation/dialect/ 아래에 두고 실행하세요.\n"
        "또는 프로젝트 루트 구조를 확인하세요.\n"
        f"누락 모듈: {exc.name}"
    ) from exc


def main() -> int:
    args = parse_args()
    cases = load_cases(args.input)
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit(f"평가 case가 없습니다: {args.input}")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for idx, case in enumerate(cases, start=1):
        row = evaluate_case(
            case,
            idx,
            semantic_judge=args.semantic_judge,
            judge_model_id=args.judge_model_id,
            judge_max_tokens=args.judge_max_tokens,
        )
        rows.append(row)
        print(
            f"[{idx}/{len(cases)}] {row['case_id']} "
            f"validator={row['validator_passed']} "
            f"exact={row['exact_match']} "
            f"sim={row['char_similarity']:.4f} "
            f"replacement_f1={row['replacement_f1']:.4f} "
            f"judge={row['semantic_same_meaning']}"
        )

    summary = summarize(rows)
    summary["semantic_judge_enabled"] = bool(args.semantic_judge)
    summary["semantic_judge_model_id"] = args.judge_model_id if args.semantic_judge else ""
    summary["semantic_judge_max_tokens"] = args.judge_max_tokens if args.semantic_judge else 0

    write_json(args.output_dir / "dialect_eval_summary.json", summary)
    write_jsonl(args.output_dir / "dialect_eval_case_results.jsonl", rows)
    write_csv(args.output_dir / "dialect_eval_case_results.csv", rows)
    write_csv(args.output_dir / "dialect_eval_failed_cases.csv", [r for r in rows if r["failure_type"] != "ok"])

    print("\n사투리 표준어 변환 평가 요약")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    print(f"\n결과 저장: {args.output_dir}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="문진톡톡 사투리→표준어 변환 성능 평가")
    parser.add_argument("--input", type=Path, required=True, help="평가 JSONL 또는 JSON 배열/객체 파일")
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation/dialect/outputs"), help="결과 저장 폴더")
    parser.add_argument("--limit", type=int, default=0, help="앞에서 N개만 실행. 0이면 전체")
    parser.add_argument(
        "--semantic-judge",
        action="store_true",
        help=(
            "선택 옵션. Bedrock judge로 gold_standard_text와 predicted_standard_text의 의미 보존 여부를 평가합니다. "
            "문자열 exact match가 너무 엄격할 때 사용하세요. 추가 비용이 발생합니다."
        ),
    )
    parser.add_argument(
        "--judge-model-id",
        default=(
            os.environ.get("DIALECT_EVAL_JUDGE_MODEL_ID")
            or os.environ.get("DIALECT_NORMALIZER_MODEL_ID")
            or DEFAULT_JUDGE_MODEL_ID
        ),
        help=(
            "Bedrock judge에 사용할 모델 ID. 기본값은 DIALECT_EVAL_JUDGE_MODEL_ID, "
            "DIALECT_NORMALIZER_MODEL_ID, apac.amazon.nova-lite-v1:0 순서로 결정됩니다."
        ),
    )
    parser.add_argument(
        "--judge-max-tokens",
        type=int,
        default=int(os.environ.get("DIALECT_EVAL_JUDGE_MAX_TOKENS", str(DEFAULT_JUDGE_MAX_TOKENS))),
        help="Bedrock judge 응답 max tokens. 기본값 500",
    )
    return parser.parse_args()


def load_cases(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("[") or text.startswith("{"):
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("data") or data.get("cases") or []
        if not isinstance(data, list):
            raise ValueError("JSON 입력은 list 또는 {data:[...]} 형태여야 합니다.")
        return [x for x in data if isinstance(x, dict)]

    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} JSON 파싱 실패: {exc}") from exc
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def evaluate_case(
    case: dict[str, Any],
    idx: int,
    semantic_judge: bool = False,
    judge_model_id: str = DEFAULT_JUDGE_MODEL_ID,
    judge_max_tokens: int = DEFAULT_JUDGE_MAX_TOKENS,
) -> dict[str, Any]:
    case_id = str(case.get("case_id") or f"case_{idx:03d}")
    original = str(case.get("dialect_text") or case.get("text") or case.get("transcript") or "").strip()
    gold = normalize_ws(str(case.get("gold_standard_text") or case.get("standard_text") or "").strip())
    if not original:
        raise ValueError(f"{case_id}: dialect_text/text가 비어 있습니다.")
    if not gold:
        raise ValueError(f"{case_id}: gold_standard_text가 필요합니다.")

    try:
        result = normalize_dialect_text(original)
    except Exception as exc:  # pragma: no cover - AWS/runtime failure path
        result = {
            "validator_passed": False,
            "standardized_text": "",
            "replacements": [],
            "errors": [{"field": "runtime", "type": exc.__class__.__name__, "message": str(exc)}],
        }

    predicted = normalize_ws(str(result.get("standardized_text") or ""))
    exact = int(predicted == gold)
    char_sim = char_similarity(predicted, gold)

    expected_replacements = normalize_replacements(case.get("expected_replacements") or [])
    actual_replacements = normalize_replacements(result.get("replacements") or [])
    replacement_scores = replacement_metrics(expected_replacements, actual_replacements)

    semantic: dict[str, Any] = {}
    if semantic_judge:
        semantic = judge_semantic_equivalence(original, gold, predicted, judge_model_id, judge_max_tokens)

    failure_type = classify_failure(
        validator_passed=bool(result.get("validator_passed")),
        exact=bool(exact),
        char_similarity_value=char_sim,
        replacement_f1=replacement_scores["replacement_f1"],
        semantic=semantic,
    )

    return {
        "case_id": case_id,
        "source_case_id": case.get("source_case_id", ""),
        "dialect_type": case.get("dialect_type", ""),
        "original_text": original,
        "gold_standard_text": gold,
        "predicted_standard_text": predicted,
        "validator_passed": bool(result.get("validator_passed")),
        "exact_match": exact,
        "char_similarity": round(char_sim, 4),
        **replacement_scores,
        "expected_replacements": expected_replacements,
        "actual_replacements": actual_replacements,
        "semantic_same_meaning": semantic.get("same_meaning"),
        "semantic_added_fact": semantic.get("added_fact"),
        "semantic_omitted_fact": semantic.get("omitted_fact"),
        "semantic_reason": semantic.get("reason", ""),
        "semantic_judge_model_id": semantic.get("model_id", judge_model_id if semantic_judge else ""),
        "failure_type": failure_type,
        "errors": result.get("errors") or [],
        "raw_result": result,
    }


def normalize_replacements(items: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source = normalize_ws(str(item.get("source_quote") or item.get("dialect") or ""))
        standard = normalize_ws(str(item.get("standard_text") or item.get("standard") or ""))
        if source and standard:
            out.append({"source_quote": source, "standard_text": standard})

    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for item in out:
        key = (item["source_quote"], item["standard_text"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def replacement_metrics(expected: list[dict[str, str]], actual: list[dict[str, str]]) -> dict[str, Any]:
    exp = {(x["source_quote"], x["standard_text"]) for x in expected}
    act = {(x["source_quote"], x["standard_text"]) for x in actual}
    tp = len(exp & act)
    fp = len(act - exp)
    fn = len(exp - act)
    precision = 1.0 if not exp and not act else safe_div(tp, tp + fp)
    recall = 1.0 if not exp and not act else safe_div(tp, tp + fn)
    f1 = f1_score(precision, recall)
    return {
        "replacement_tp": tp,
        "replacement_fp": fp,
        "replacement_fn": fn,
        "replacement_precision": round(precision, 4),
        "replacement_recall": round(recall, 4),
        "replacement_f1": round(f1, 4),
    }


def judge_semantic_equivalence(
    original: str,
    gold: str,
    predicted: str,
    model_id: str = DEFAULT_JUDGE_MODEL_ID,
    max_tokens: int = DEFAULT_JUDGE_MAX_TOKENS,
) -> dict[str, Any]:
    """Nova Lite 기반 의미 보존 보조 판정.

    같은 계열 모델이 생성과 평가를 모두 맡으면 관대하게 평가할 수 있으므로,
    발표 전 실패/성공 케이스 일부는 사람이 샘플링 검토하는 것을 권장합니다.
    """
    try:
        from llm import call_bedrock_json_with_meta  # type: ignore
    except Exception as exc:
        return {
            "same_meaning": None,
            "added_fact": None,
            "omitted_fact": None,
            "reason": f"judge_import_error:{exc.__class__.__name__}",
            "model_id": model_id,
        }

    prompt = f"""
You are evaluating Korean dialect normalization for a clinic intake system.
Do NOT diagnose. Do NOT judge whether the medical statement is clinically correct.
Only compare whether the model output preserves the patient-stated meaning in the gold standard sentence.
Return strict JSON only.

Evaluation rules:
- same_meaning=true only when the model output preserves the same symptoms, negations, time course, severity, and patient question intent.
- added_fact=true if the model output adds a symptom, medication, diagnosis, date, severity, or certainty absent from the original/gold.
- omitted_fact=true if the model output drops a symptom, negation, time course, severity, or question intent present in the original/gold.
- Minor wording differences are acceptable if the meaning is preserved.

Original dialect/colloquial text:
{original}

Gold standard Korean:
{gold}

Model standardized Korean:
{predicted}

Return JSON:
{{
  "same_meaning": true or false,
  "added_fact": true or false,
  "omitted_fact": true or false,
  "reason": "short Korean reason"
}}
""".strip()
    try:
        obj, _raw, _meta = call_bedrock_json_with_meta(prompt, model_id, max_tokens)
    except Exception as exc:  # pragma: no cover - AWS failure path
        return {
            "same_meaning": None,
            "added_fact": None,
            "omitted_fact": None,
            "reason": f"judge_bedrock_error:{exc.__class__.__name__}",
            "model_id": model_id,
        }
    if not isinstance(obj, dict):
        return {
            "same_meaning": None,
            "added_fact": None,
            "omitted_fact": None,
            "reason": "judge_output_not_object",
            "model_id": model_id,
        }
    return {
        "same_meaning": coerce_bool(obj.get("same_meaning")),
        "added_fact": coerce_bool(obj.get("added_fact")),
        "omitted_fact": coerce_bool(obj.get("omitted_fact")),
        "reason": str(obj.get("reason") or ""),
        "model_id": model_id,
    }


def coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "y", "1", "맞음", "예"}:
            return True
        if lowered in {"false", "no", "n", "0", "아님", "아니오"}:
            return False
    return None


def classify_failure(
    validator_passed: bool,
    exact: bool,
    char_similarity_value: float,
    replacement_f1: float,
    semantic: dict[str, Any],
) -> str:
    if not validator_passed:
        return "validator_failed"
    if semantic:
        if semantic.get("added_fact") is True:
            return "added_fact"
        if semantic.get("omitted_fact") is True:
            return "omitted_fact"
        if semantic.get("same_meaning") is True:
            return "ok"
        if semantic.get("same_meaning") is False:
            return "semantic_mismatch"
    if exact:
        return "ok"
    if char_similarity_value >= 0.92 and replacement_f1 >= 0.80:
        return "near_match"
    if char_similarity_value < 0.75:
        return "low_text_similarity"
    return "string_mismatch"


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = max(1, len(rows))
    total_tp = sum(int(r["replacement_tp"]) for r in rows)
    total_fp = sum(int(r["replacement_fp"]) for r in rows)
    total_fn = sum(int(r["replacement_fn"]) for r in rows)
    rep_precision = safe_div(total_tp, total_tp + total_fp)
    rep_recall = safe_div(total_tp, total_tp + total_fn)
    rep_f1 = f1_score(rep_precision, rep_recall)
    semantic_rows = [r for r in rows if r.get("semantic_same_meaning") is not None]
    semantic_n = max(1, len(semantic_rows))
    return {
        "case_count": len(rows),
        "validator_pass_rate": round(sum(1 for r in rows if r["validator_passed"]) / n, 4),
        "exact_match_rate": round(sum(int(r["exact_match"]) for r in rows) / n, 4),
        "avg_char_similarity": round(sum(float(r["char_similarity"]) for r in rows) / n, 4),
        "replacement_precision": round(rep_precision, 4),
        "replacement_recall": round(rep_recall, 4),
        "replacement_f1": round(rep_f1, 4),
        "semantic_judged_case_count": len(semantic_rows),
        "semantic_same_meaning_rate": (
            round(sum(1 for r in semantic_rows if r.get("semantic_same_meaning") is True) / semantic_n, 4)
            if semantic_rows
            else None
        ),
        "no_added_fact_rate": (
            round(sum(1 for r in semantic_rows if r.get("semantic_added_fact") is False) / semantic_n, 4)
            if semantic_rows
            else None
        ),
        "no_omitted_fact_rate": (
            round(sum(1 for r in semantic_rows if r.get("semantic_omitted_fact") is False) / semantic_n, 4)
            if semantic_rows
            else None
        ),
        "failure_type_counts": count_by(rows, "failure_type"),
    }


def char_similarity(a: str, b: str) -> float:
    a = normalize_ws(a)
    b = normalize_ws(b)
    if not a and not b:
        return 1.0
    return 1.0 - safe_div(levenshtein(a, b), max(len(a), len(b), 1))


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def safe_div(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


def f1_score(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False, default=json_default) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case_id",
        "source_case_id",
        "dialect_type",
        "validator_passed",
        "exact_match",
        "char_similarity",
        "replacement_precision",
        "replacement_recall",
        "replacement_f1",
        "semantic_same_meaning",
        "semantic_added_fact",
        "semantic_omitted_fact",
        "semantic_judge_model_id",
        "failure_type",
        "original_text",
        "gold_standard_text",
        "predicted_standard_text",
        "expected_replacements",
        "actual_replacements",
        "semantic_reason",
        "errors",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: csv_value(row.get(k)) for k in fieldnames})


def csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def json_default(value: Any) -> Any:
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config


ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend" / "serverless" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from dialect_rag import retrieve_dialect_context  # noqa: E402


BLUEPRINT_PATH = ROOT / "evaluation" / "train_100_v2_blueprint" / "case_blueprint.jsonl"
OUT_DIR = Path(__file__).resolve().parent
TRAIN_PATH = OUT_DIR / "train_100_v2.jsonl"
REPORT_PATH = OUT_DIR / "quality_gate_report.json"

DEFAULT_MODEL_ID = os.environ.get("TRAIN_RENDER_MODEL_ID", "apac.amazon.nova-pro-v1:0")
DEFAULT_REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
MAX_TOKENS = int(os.environ.get("TRAIN_RENDER_MAX_TOKENS", "900"))
TEMPERATURE = float(os.environ.get("TRAIN_RENDER_TEMPERATURE", "0.7"))
MAX_ATTEMPTS = int(os.environ.get("TRAIN_RENDER_ATTEMPTS", "3"))

FORMAL_PATTERNS = ("습니다", "습니까", "합니다", "드립니다", "예정입니다")
POLITE_ENDING_RE = re.compile(r"요(?:[.!?。]|$)")
Q4_PATTERNS = ("궁금", "물어보고", "여쭤", "되나요", "될까요", "먹어도 되", "의사", "선생님")
MEDICATION_PATTERNS = ("약", "처방", "복용", "영양제", "한약", "진통제", "항생제")
EXACT_DURATION_PATTERNS = (
    "어제부터",
    "오늘부터",
    "아침부터",
    "저녁부터",
    "며칠",
    "몇일",
    "일주일",
    "한 달",
    "두 달",
    "언제부터",
)
IMPROVED_MARKERS = ("나아", "좋아", "괜찮", "덜", "사라", "없어졌", "줄", "가라앉", "들어오")
RECURRENT_MARKERS = ("계속", "아직", "다시", "또", "반복", "남아", "그대로", "여전", "후로", "지난번", "전번", "비슷", "심해")
NEGATION_MARKERS = ("없", "아니", "안 ", "안나", "안 나", "않", "전혀", "한 번도", "느껴지지", "제대로")


def load_blueprint() -> list[dict[str, Any]]:
    return [json.loads(line) for line in BLUEPRINT_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_existing(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows[row["case_id"]] = row
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def bedrock_client(region: str):
    return boto3.client(
        "bedrock-runtime",
        region_name=region,
        config=Config(connect_timeout=5, read_timeout=80, retries={"max_attempts": 3, "mode": "standard"}),
    )


def parse_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?", "", raw, flags=re.I).strip()
    raw = re.sub(r"```$", "", raw).strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass

    start = raw.find("{")
    if start < 0:
        return {}
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(raw)):
        char = raw[idx]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(raw[start : idx + 1])
                    return parsed if isinstance(parsed, dict) else {}
                except Exception:
                    return {}
    return {}


def call_bedrock_json(client, model_id: str, prompt: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"temperature": TEMPERATURE, "maxTokens": MAX_TOKENS},
    )
    raw_text = "".join(
        block.get("text", "")
        for block in response.get("output", {}).get("message", {}).get("content", [])
    )
    meta = {
        "model_id": model_id,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "raw_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        "stop_reason": response.get("stopReason"),
    }
    return parse_json_object(raw_text), raw_text, meta


def build_prompt(case: dict[str, Any], repair_note: str = "") -> str:
    anchor = case.get("dialect_anchor") or {}
    anchor_block = ""
    if anchor:
        anchor_block = f"""
Dialect anchor requirement:
- Include this Gangwon dialect expression naturally when possible: {anchor.get('dialect')}
- Meaning: {anchor.get('standard')}
- Usage guardrail: {anchor.get('usage')}
- Do not add a new symptom only because of the dialect anchor.
"""

    return f"""
You are generating one synthetic Korean patient answer for a medical intake evaluation dataset.

Return ONLY a JSON object. No markdown.

Global rules:
- Write like a real patient speaking casually in Korean.
- Do not use formal '-습니다' style.
- Use banmal casual speech. Do not end clauses with '-요'.
- Do not make it a doctor question.
- Do not ask whether medicines, supplements, or treatments are okay.
- Do not make onset timing or exact duration the main answer.
- Do not mention diagnoses.
- Make the answer natural, not a slot-filled template.
- Keep it short: one sentence or two short clauses.
- Preserve the blueprint's intended symptoms and negative context.

Question target:
- visit_type: {case['visit_type']}
- question_id: {case['question_id']}
- question_type: {case['question_type']}
- For initial Q1, answer what is uncomfortable now.
- For follow-up Q3, answer how symptoms have changed or continued since the previous visit, without exact dates.

Blueprint:
{json.dumps(case, ensure_ascii=False, indent=2)}
{anchor_block}
Output JSON schema:
{{
  "case_id": "{case['case_id']}",
  "utterance": "patient answer only",
  "rendering_notes": "brief reason why it matches the blueprint",
  "included_gold_symptoms": {json.dumps(case['gold_symptoms'], ensure_ascii=False)},
  "explicitly_negated_symptoms": {json.dumps(case['negative_symptoms'], ensure_ascii=False)}
}}

Repair note from previous failed attempt:
{repair_note}
""".strip()


def normalize_anchor_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").replace("?", ""))


def anchor_surface_candidates(anchor: dict[str, Any]) -> set[str]:
    dialect = str(anchor.get("dialect") or "").strip()
    if not dialect:
        return set()

    values = {dialect}
    values.add(re.sub(r"[()]", " ", dialect))
    values.add(re.sub(r"\([^)]*\)", " ", dialect))

    bracket = re.search(r"(.+?)\[(.+?)\]", dialect)
    if bracket:
        values.add(bracket.group(1))
        values.add(bracket.group(2))

    expanded = set(values)
    for value in list(values):
        cleaned = value.strip()
        if cleaned.endswith("하다"):
            stem = cleaned[:-2]
            expanded.update(
                stem + suffix
                for suffix in ("해", "해요", "해서", "하고", "하니", "하네", "했어", "했는데", "했던", "하던", "한")
            )
    return {normalize_anchor_text(value) for value in expanded if normalize_anchor_text(value)}


def validate_row(row: dict[str, Any], case: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    utterance = str(row.get("utterance") or "").strip()

    if row.get("case_id") != case["case_id"]:
        errors.append("case_id mismatch")
    if not utterance:
        errors.append("missing utterance")
        return errors, warnings
    if len(utterance) < 6:
        errors.append("utterance too short")
    if len(utterance) > 180:
        errors.append("utterance too long")
    if any(pattern in utterance for pattern in FORMAL_PATTERNS):
        errors.append("formal style detected")
    if POLITE_ENDING_RE.search(utterance):
        errors.append("polite -요 ending detected")
    if any(pattern in utterance for pattern in Q4_PATTERNS):
        errors.append("Q4-like doctor question detected")
    if any(pattern in utterance for pattern in MEDICATION_PATTERNS):
        errors.append("medication/supplement content detected")
    if any(pattern in utterance for pattern in EXACT_DURATION_PATTERNS):
        errors.append("exact onset/duration content detected")

    if case["language_style"] == "standard" and case["dialect_source_layer"] != "none":
        errors.append("standard row has dialect layer")
    if case["language_style"] == "gangwon" and case["dialect_source_layer"] == "none":
        errors.append("gangwon row missing dialect layer")

    anchor = case.get("dialect_anchor")
    if case["dialect_source_layer"] == "rag_pack_anchored":
        surfaces = anchor_surface_candidates(anchor or {})
        compact_utterance = normalize_anchor_text(utterance)
        if not any(surface in compact_utterance for surface in surfaces):
            errors.append("required dialect anchor surface missing")
        hints = retrieve_dialect_context(utterance, top_k=8).get("hints") or []
        expected_standard = (anchor or {}).get("standard")
        if expected_standard and not any(item.get("standard") == expected_standard for item in hints):
            errors.append("rendered utterance does not retrieve expected dialect RAG hint")

    status = case["status_pattern"]
    if status == "improved_or_resolved" and not any(marker in utterance for marker in IMPROVED_MARKERS):
        warnings.append("improved/resolved marker not obvious")
    if status == "recurrent_or_persistent" and not any(marker in utterance for marker in RECURRENT_MARKERS):
        warnings.append("recurrent/persistent marker not obvious")
    if case.get("negative_symptoms") and not any(marker in utterance for marker in NEGATION_MARKERS):
        errors.append("negative symptom marker missing")

    return errors, warnings


def render_case(client, model_id: str, case: dict[str, Any]) -> dict[str, Any]:
    repair_note = ""
    attempts = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        prompt = build_prompt(case, repair_note)
        parsed, raw_text, meta = call_bedrock_json(client, model_id, prompt)
        row = {
            **case,
            "utterance": str(parsed.get("utterance") or "").strip(),
            "rendering_notes": str(parsed.get("rendering_notes") or "").strip(),
            "included_gold_symptoms": parsed.get("included_gold_symptoms") or case["gold_symptoms"],
            "explicitly_negated_symptoms": parsed.get("explicitly_negated_symptoms") or case["negative_symptoms"],
            "render_meta": {
                **meta,
                "attempt": attempt,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            },
        }
        errors, warnings = validate_row(row, case)
        row["quality"] = {"passed": not errors, "errors": errors, "warnings": warnings}
        attempts.append(
            {
                "attempt": attempt,
                "errors": errors,
                "warnings": warnings,
                "raw_sha256": meta["raw_sha256"],
                "raw_preview": raw_text[:240],
            }
        )
        if not errors:
            row["render_attempts"] = attempts
            return row
        repair_note = (
            "Previous output failed validation. Fix these issues only: "
            + "; ".join(errors)
            + ". Return a new valid JSON object."
        )
        time.sleep(0.2)

    row["render_attempts"] = attempts
    return row


def build_report(rows: list[dict[str, Any]], blueprint: list[dict[str, Any]]) -> dict[str, Any]:
    errors = []
    if len(rows) != len(blueprint):
        errors.append(f"row count mismatch: rendered={len(rows)} blueprint={len(blueprint)}")

    row_by_id = {row.get("case_id"): row for row in rows}
    for case in blueprint:
        row = row_by_id.get(case["case_id"])
        if not row:
            errors.append(f"{case['case_id']} missing rendered row")
            continue
        row_errors = ((row.get("quality") or {}).get("errors") or [])
        if row_errors:
            errors.append(f"{case['case_id']} failed quality: {row_errors}")

    counts = {
        "visit_type": Counter(row.get("visit_type") for row in rows),
        "question_id": Counter(row.get("question_id") for row in rows),
        "language_style": Counter(row.get("language_style") for row in rows),
        "dialect_source_layer": Counter(row.get("dialect_source_layer") for row in rows),
        "symptom_group": Counter(row.get("symptom_group") for row in rows),
        "status_pattern": Counter(row.get("status_pattern") for row in rows),
        "quality_passed": Counter(bool((row.get("quality") or {}).get("passed")) for row in rows),
    }
    failed = [
        {
            "case_id": row.get("case_id"),
            "utterance": row.get("utterance"),
            "errors": (row.get("quality") or {}).get("errors") or [],
            "warnings": (row.get("quality") or {}).get("warnings") or [],
        }
        for row in rows
        if not (row.get("quality") or {}).get("passed")
    ]
    warnings = [
        {
            "case_id": row.get("case_id"),
            "warnings": (row.get("quality") or {}).get("warnings") or [],
        }
        for row in rows
        if (row.get("quality") or {}).get("warnings")
    ]
    return {
        "passed": not errors,
        "errors": errors,
        "counts": {key: dict(value) for key, value in counts.items()},
        "failed_cases": failed,
        "warning_cases": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Regenerate every row instead of resuming.")
    parser.add_argument("--limit", type=int, default=0, help="Render only the first N rows for smoke tests.")
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--region", default=DEFAULT_REGION)
    args = parser.parse_args()

    blueprint = load_blueprint()
    if args.limit:
        blueprint = blueprint[: args.limit]

    existing = {} if args.force else load_existing(TRAIN_PATH)
    rendered_by_id: dict[str, dict[str, Any]] = {}
    client = bedrock_client(args.region)

    for index, case in enumerate(blueprint, start=1):
        current = existing.get(case["case_id"])
        if current:
            errors, warnings = validate_row(current, case)
            current["quality"] = {"passed": not errors, "errors": errors, "warnings": warnings}
        if current and (current.get("quality") or {}).get("passed"):
            rendered_by_id[case["case_id"]] = current
            print(f"[{index:03d}/{len(blueprint):03d}] reuse {case['case_id']}")
            continue

        print(f"[{index:03d}/{len(blueprint):03d}] render {case['case_id']}")
        row = render_case(client, args.model_id, case)
        rendered_by_id[case["case_id"]] = row
        ordered = [rendered_by_id[item["case_id"]] for item in blueprint if item["case_id"] in rendered_by_id]
        write_jsonl(TRAIN_PATH, ordered)
        time.sleep(0.15)

    rows = [rendered_by_id[item["case_id"]] for item in blueprint if item["case_id"] in rendered_by_id]
    write_jsonl(TRAIN_PATH, rows)
    report = build_report(rows, blueprint)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

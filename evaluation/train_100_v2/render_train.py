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
TEMPERATURE = float(os.environ.get("TRAIN_RENDER_TEMPERATURE", "0.9"))
MAX_ATTEMPTS = int(os.environ.get("TRAIN_RENDER_ATTEMPTS", "8"))

FORMAL_PATTERNS = ("습니다", "습니까", "합니다", "드립니다", "예정입니다")
POLITE_ENDING_RE = re.compile(r"요(?:[.!?。]|$)")
Q4_PATTERNS = ("궁금", "물어보고", "여쭤", "되나요", "될까요", "먹어도 되", "의사", "선생님")
MEDICATION_PATTERNS = ("약", "처방", "복용", "영양제", "한약", "진통제", "항생제")
EXACT_DURATION_PATTERNS = (
    "어제부터",
    "오늘부터",
    "오늘 아침",
    "아침부터",
    "저녁부터",
    "몇 일",
    "며칠",
    "몇일",
    "일주일",
    "한 달",
    "두 달",
    "언제부터",
)
PATIENT_VOICE_BLOCKERS = (
    "증상",
    "병원 왔",
    "지난 방문 이후로",
    "지난번 방문 후로",
    "전 방문 후로",
    "왜 이래",
    "왜 그런",
    "뭐 때문",
)
IMPROVED_MARKERS = ("나아", "좋아", "괜찮", "덜", "사라", "없어졌", "줄", "가라앉", "들어오")
RECURRENT_MARKERS = ("계속", "아직", "다시", "또", "반복", "남아", "그대로", "여전", "후로", "지난번", "전번", "비슷", "심해")
NEGATION_MARKERS = ("없", "아니", "안 ", "안나", "안 나", "않", "전혀", "한 번도", "느껴지지", "제대로")

VOICE_DIRECTIONS = (
    "Start directly from the body sensation or body part. Do not use a time adverb opening.",
    "Sound worried but casual, like a patient trying to describe the feeling quickly.",
    "Use a contrast structure only if the blueprint has negative symptoms.",
    "For follow-up rows, describe change with words like still, better, worse, or not gone; avoid saying 'visit'.",
    "Use plain everyday words and avoid medical meta words like 'symptom'.",
    "Let the sentence feel spoken, slightly imperfect, and not polished.",
    "Start from what makes daily life uncomfortable, not from a generic intro phrase.",
    "Use a short first-person patient voice without explaining the dataset task.",
)

GOLD_EVIDENCE_PATTERNS = {
    "목의 통증": (r"목.*(아프|아푸|칼칼|따갑|쓰리|불편|힘들)",),
    "코막힘": (r"코.*(막|답답)",),
    "콧물": (r"콧물", r"코.*(흐르|줄줄|훌쩍)"),
    "재채기": (r"재채기",),
    "감기 증상": (r"감기",),
    "열": (r"열", r"뜨겁", r"미열"),
    "기침": (r"기침", r"콜록"),
    "가래": (r"가래", r"목.*(끼|걸)"),
    "화농성 객담": (r"(누렇|노랗|진하|걸쭉).*가래", r"가래.*(누렇|노랗|진하|걸쭉)"),
    "검은색 가래": (r"(검|까만).*가래", r"가래.*(검|까만)"),
    "거품이 섞인 가래": (r"거품.*가래", r"가래.*거품"),
    "천명음": (r"쌕쌕", r"숨.*소리", r"휘파람"),
    "호흡곤란": (r"숨.*(차|힘들|가쁘|막히|쉬기 힘)", r"호흡.*곤란", r"말하기.*힘"),
    "가슴 답답": (r"가슴.*답답", r"가슴.*막힌"),
    "흉통": (r"가슴.*(아프|통증|찌르|쑤시)",),
    "객혈": (r"피.*(가래|섞|나와)", r"가래.*피"),
    "청색증": (r"입술.*(파래|파랗|푸르)",),
    "오한": (r"춥", r"떨리", r"오한"),
    "근육통": (r"몸.*(쑤시|아프)", r"근육.*아프", r"몸살"),
    "피로감": (r"피곤", r"축.*처지", r"힘들", r"기운.*없"),
    "기운없음": (r"기운.*없", r"힘.*없", r"축.*처지"),
    "목소리 변화": (r"목소리.*(쉬|안 나오|잠기)",),
    "삼키기 곤란": (r"삼키.*(힘|어렵|불편)", r"넘기.*힘"),
    "사래걸림": (r"사래",),
    "눈의 충혈": (r"눈.*(빨갛|충혈)",),
    "눈곱": (r"눈곱", r"눈.*분비"),
    "어지러움": (r"어지럽", r"핑.*돌", r"빙글"),
    "가슴 두근거림": (r"두근", r"심장.*뛰", r"맥.*불규칙"),
    "하지부종": (r"다리.*(붓|부어)", r"발.*(붓|부어)", r"신발.*끼"),
    "근력 약화": (r"힘.*안.*들어", r"힘.*빠", r"팔다리.*힘"),
    "두통": (r"머리.*(아프|쑤시)", r"머리깽이.*아프"),
    "구토": (r"토하", r"구토", r"울렁"),
    "설사": (r"설사", r"묽은.*변", r"변.*묽"),
    "복부 통증": (r"배.*(아프|꼬이|통증)", r"복통", r"창지.*꼬"),
    "복부 팽만": (r"배.*(빵빵|더부룩|부풀)",),
    "식욕부진": (r"입맛.*없", r"못.*먹", r"잘.*안.*먹"),
}


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


def voice_direction(case: dict[str, Any]) -> str:
    number = int(str(case["case_id"]).rsplit("_", 1)[-1])
    return VOICE_DIRECTIONS[(number - 1) % len(VOICE_DIRECTIONS)]


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
- Keep the dialect expression close to the source surface. If it ends with '하다', use a spoken form such as '해', '했어', or '했던', not a noun form.
"""

    return f"""
You are generating one synthetic Korean patient answer for a medical intake evaluation dataset.
Imagine you are the patient sitting at the intake desk and answering out loud.

Return ONLY a JSON object. No markdown.

Global rules:
- Write like a real patient speaking casually in Korean.
- Do not use formal '-습니다' style.
- Use banmal casual speech. Do not end clauses with '-요'.
- Do not make it a doctor question.
- Do not ask whether medicines, supplements, or treatments are okay.
- Do not make onset timing or exact duration the main answer.
- Do not mention diagnoses.
- Do not use the word '증상'.
- Do not say '병원 왔어' or explain why the patient came.
- Do not start with repetitive boilerplate such as '요즘...', '지난 방문 이후로...', or '지난번 방문 후로...'.
- Make the answer natural, not a slot-filled template.
- Keep it short: one sentence or two short clauses.
- Every item in gold_symptoms must be expressed in patient language.
- Preserve the blueprint's negative context without turning negative symptoms into active complaints.

Patient voice direction for this row:
- {voice_direction(case)}

Question target:
- visit_type: {case['visit_type']}
- question_id: {case['question_id']}
- question_type: {case['question_type']}
- For initial Q1, answer what is uncomfortable now.
- For follow-up Q3, answer how the discomfort changed or continued since last time, without exact dates and without using the word 'visit'.

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


def has_gold_evidence(symptom: str, utterance: str) -> bool:
    patterns = GOLD_EVIDENCE_PATTERNS.get(symptom)
    if not patterns:
        return True
    return any(re.search(pattern, utterance) for pattern in patterns)


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
    first_token, _first_two = opening_tokens(utterance)
    if first_token == "요즘":
        errors.append("do not begin with 요즘; start with the body part, sensation, contrast, or change instead")
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
    if any(pattern in utterance for pattern in PATIENT_VOICE_BLOCKERS):
        errors.append("template-like or non-patient voice detected")
    missing_gold = [symptom for symptom in case.get("gold_symptoms") or [] if not has_gold_evidence(symptom, utterance)]
    if missing_gold:
        errors.append(f"missing patient-language evidence for gold symptoms: {missing_gold}")

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
        unexpected = [item for item in hints if expected_standard and item.get("standard") != expected_standard]
        if unexpected:
            errors.append(f"unexpected dialect RAG hints for anchored row: {unexpected}")
    elif case["dialect_source_layer"] in {"clinical_colloquial", "light_dialect_style"}:
        hints = retrieve_dialect_context(utterance, top_k=8).get("hints") or []
        if hints:
            errors.append(f"unexpected dialect RAG hints for non-anchored row: {hints}")

    status = case["status_pattern"]
    if status == "improved_or_resolved" and not any(marker in utterance for marker in IMPROVED_MARKERS):
        errors.append("improved/resolved marker missing")
    if status == "recurrent_or_persistent" and not any(marker in utterance for marker in RECURRENT_MARKERS):
        errors.append("recurrent/persistent marker missing")
    if case.get("negative_symptoms") and not any(marker in utterance for marker in NEGATION_MARKERS):
        errors.append("negative symptom marker missing")

    return errors, warnings


def opening_tokens(utterance: str) -> tuple[str, str]:
    cleaned = re.sub(r"[\"'“”‘’.,!?。…]", " ", str(utterance or "")).strip()
    parts = [part for part in cleaned.split() if part]
    first = parts[0] if parts else ""
    first_two = " ".join(parts[:2]) if len(parts) >= 2 else first
    return first, first_two


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

    first_counts = Counter()
    first_two_counts = Counter()
    for row in rows:
        first, first_two = opening_tokens(row.get("utterance") or "")
        if first:
            first_counts[first] += 1
        if first_two:
            first_two_counts[first_two] += 1

    overused_first = {key: value for key, value in first_counts.items() if value > 12}
    overused_first_two = {key: value for key, value in first_two_counts.items() if value > 6}
    if overused_first:
        errors.append(f"overused opening first tokens: {overused_first}")
    if overused_first_two:
        errors.append(f"overused opening two-token prefixes: {overused_first_two}")
    if first_counts.get("요즘", 0) > 10:
        errors.append(f"too many utterances start with 요즘: {first_counts.get('요즘', 0)}")
    if first_counts.get("지난", 0) + first_counts.get("지난번", 0) > 16:
        errors.append(
            "too many follow-up boilerplate openings: "
            f"지난={first_counts.get('지난', 0)}, 지난번={first_counts.get('지난번', 0)}"
        )

    counts = {
        "visit_type": Counter(row.get("visit_type") for row in rows),
        "question_id": Counter(row.get("question_id") for row in rows),
        "language_style": Counter(row.get("language_style") for row in rows),
        "dialect_source_layer": Counter(row.get("dialect_source_layer") for row in rows),
        "symptom_group": Counter(row.get("symptom_group") for row in rows),
        "status_pattern": Counter(row.get("status_pattern") for row in rows),
        "quality_passed": Counter(bool((row.get("quality") or {}).get("passed")) for row in rows),
        "opening_first_token_top10": Counter(dict(first_counts.most_common(10))),
        "opening_two_token_top10": Counter(dict(first_two_counts.most_common(10))),
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

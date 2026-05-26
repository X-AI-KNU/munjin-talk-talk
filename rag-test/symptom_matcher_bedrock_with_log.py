"""
symptom_matcher_bedrock_with_log.py

Goal:
- Match a free-form Korean text to standardized symptom names from a Bedrock Knowledge Base.
- Do NOT output diseases, diagnoses, treatment, or departments.
- Save every run to a JSON log file.

Required environment variables:
- AWS_REGION: e.g. ap-northeast-2
- BEDROCK_KB_ID: your Bedrock Knowledge Base ID
- BEDROCK_MODEL_ID: a Bedrock chat model ID or inference profile ID that supports Converse API
  Example for Seoul/global inference:
  $env:BEDROCK_MODEL_ID="global.amazon.nova-2-lite-v1:0"

Optional environment variables:
- DEBUG_RETRIEVE=1
- SYMPTOM_LOG_FILE=symptom_match_logs.json

Usage:
python symptom_matcher_bedrock_with_log.py "열이 나고 기침이 심하고 숨이 차요. 가래도 있어요."

With explicit log file:
python symptom_matcher_bedrock_with_log.py --log-file "logs/symptom_match_logs.json" "기침이 나고 열이 있어요"

Without logging:
python symptom_matcher_bedrock_with_log.py --no-log "기침"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3


SCRIPT_VERSION = "2026-05-26-log-v1"


def now_iso() -> str:
    """UTC ISO timestamp for reproducible logs."""
    return datetime.now(timezone.utc).isoformat()


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"환경변수 {name}가 설정되지 않았습니다. "
            f"PowerShell에서 `$env:{name}=\"...\"` 형태로 먼저 설정하세요."
        )
    return value


AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-2")
KNOWLEDGE_BASE_ID = get_required_env("BEDROCK_KB_ID")
MODEL_ID = get_required_env("BEDROCK_MODEL_ID")
DEBUG_RETRIEVE = os.getenv("DEBUG_RETRIEVE", "0") == "1"

kb_client = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
llm_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)


def retrieve_symptom_candidates(
    user_text: str,
    number_of_results: int = 25,
) -> list[dict[str, Any]]:
    """Retrieve candidate symptom rows from Bedrock Knowledge Base."""
    response = kb_client.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": user_text},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": number_of_results,
                "overrideSearchType": "SEMANTIC",
            }
        },
    )

    retrieval_results = response.get("retrievalResults", [])

    if DEBUG_RETRIEVE:
        print(f"[DEBUG] raw retrievalResults count = {len(retrieval_results)}", file=sys.stderr)
        for i, item in enumerate(retrieval_results[:3], start=1):
            metadata = item.get("metadata", {}) or {}
            content = item.get("content", {}) or {}
            print(f"[DEBUG] result {i} score = {item.get('score')}", file=sys.stderr)
            print(f"[DEBUG] result {i} metadata keys = {list(metadata.keys())}", file=sys.stderr)
            print(f"[DEBUG] result {i} content keys = {list(content.keys())}", file=sys.stderr)
            print(f"[DEBUG] result {i} metadata = {json.dumps(metadata, ensure_ascii=False)[:1000]}", file=sys.stderr)
            print(f"[DEBUG] result {i} content = {json.dumps(content, ensure_ascii=False)[:1500]}", file=sys.stderr)

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in retrieval_results:
        metadata = item.get("metadata", {}) or {}
        content = item.get("content", {}) or {}

        row_values = _extract_row_values(content)
        text = _extract_text(content)

        symptom_name = (
            _clean_value(metadata.get("symptom_name"))
            or _clean_value(row_values.get("symptom_name"))
            or _parse_symptom_from_text(text)
            or _parse_symptom_from_metadata(metadata)
        )

        if not symptom_name or symptom_name in seen:
            continue

        aliases = (
            _clean_value(metadata.get("aliases"))
            or _clean_value(row_values.get("aliases"))
            or _parse_aliases_from_text(text)
            or ""
        )

        seen.add(symptom_name)
        candidates.append(
            {
                "symptom_name": symptom_name,
                "symptom_id": _clean_value(metadata.get("symptom_id"))
                or _clean_value(row_values.get("symptom_id")),
                "aliases": aliases,
                "score": item.get("score"),
                "content": text or json.dumps(row_values or metadata, ensure_ascii=False),
                "source": {
                    "data_source_id": metadata.get("x-amz-bedrock-kb-data-source-id"),
                    "chunk_id": metadata.get("x-amz-bedrock-kb-chunk-id"),
                    "source_file_modality": metadata.get("x-amz-bedrock-kb-source-file-modality"),
                },
            }
        )

    return candidates


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_row_values(content: dict[str, Any]) -> dict[str, str]:
    """Handle content.row returned by Bedrock Retrieve API."""
    row_values: dict[str, str] = {}
    for col in content.get("row", []) or []:
        name = col.get("columnName")
        value = col.get("columnValue")
        if name and value is not None:
            row_values[str(name)] = str(value)
    return row_values


def _extract_text(content: dict[str, Any]) -> str:
    """Handle possible content shapes from Bedrock KB Retrieve."""
    if isinstance(content.get("text"), str):
        return content["text"]
    if isinstance(content.get("byteContent"), str):
        return content["byteContent"]
    if content.get("row"):
        row_values = _extract_row_values(content)
        return "\n".join(f"{k}: {v}" for k, v in row_values.items())
    return ""


def _parse_symptom_from_text(text: str) -> str | None:
    patterns = [
        r"표준\s*증상명\s*:\s*([^\n,|]+)",
        r"symptom_name\s*[:=]\s*([^\n,|]+)",
        r"증상명\s*[:=]\s*([^\n,|]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            return match.group(1).strip().strip('"')
    return None


def _parse_aliases_from_text(text: str) -> str | None:
    match = re.search(r"동의어/사용자 표현 예시\s*:\s*([^\n]+)", text or "")
    if match:
        return match.group(1).strip()
    return None


def _parse_symptom_from_metadata(metadata: dict[str, Any]) -> str | None:
    """Last-resort fallback if Bedrock stores metadata with prefixed or nested keys."""
    for key, value in metadata.items():
        key_lower = str(key).lower()
        if "symptom_name" in key_lower or key_lower.endswith("symptom"):
            return _clean_value(value)
    return None


def build_prompts(user_text: str, candidates: list[dict[str, Any]]) -> tuple[str, str]:
    candidate_block = "\n".join(
        f"- {c['symptom_name']} | aliases: {c.get('aliases', '')}" for c in candidates
    )

    system_prompt = """
너는 '증상명 표준화 매칭기'다.
입력 문장을 보고 후보 증상 목록 중 실제로 문장에 나타난 증상만 고른다.

절대 규칙:
- 질환명, 진단명, 원인, 치료법을 출력하지 않는다.
- 후보 목록에 없는 증상명을 새로 만들지 않는다.
- 출력은 JSON만 한다.
- matched_symptoms에는 후보 목록에 존재하는 symptom_name만 넣는다.
- 애매한 표현은 possible_symptoms에 넣고 confidence를 낮춘다.
""".strip()

    user_prompt = f"""
입력 문장:
{user_text}

후보 증상 목록:
{candidate_block}

반환 JSON 형식:
{{
  "input_text": "...",
  "matched_symptoms": [
    {{
      "symptom_name": "...",
      "evidence_text": "입력 문장에서 근거가 되는 짧은 표현",
      "confidence": 0.0
    }}
  ],
  "possible_symptoms": [
    {{
      "symptom_name": "...",
      "reason": "애매한 이유",
      "confidence": 0.0
    }}
  ],
  "unmatched_expressions": []
}}
""".strip()

    return system_prompt, user_prompt


def match_symptoms_with_trace(
    user_text: str,
    number_of_results: int = 25,
    include_prompts: bool = True,
) -> dict[str, Any]:
    """
    Run retrieval + LLM matching and return a full trace record.

    This function returns everything needed for experiment logs:
    - input text
    - Bedrock config
    - retrieved symptom candidates
    - prompts
    - raw model output
    - final whitelist-validated result
    """
    started_at = now_iso()
    started_perf = time.perf_counter()
    record_id = str(uuid.uuid4())

    base_record: dict[str, Any] = {
        "record_id": record_id,
        "script_version": SCRIPT_VERSION,
        "status": "running",
        "started_at": started_at,
        "completed_at": None,
        "duration_ms": None,
        "input": {
            "text": user_text,
        },
        "config": {
            "aws_region": AWS_REGION,
            "knowledge_base_id": KNOWLEDGE_BASE_ID,
            "model_id": MODEL_ID,
            "number_of_results": number_of_results,
            "retrieval_search_type": "SEMANTIC",
        },
        "retrieval": {
            "candidate_count": 0,
            "candidate_names": [],
            "candidates": [],
        },
        "prompts": {},
        "model": {
            "raw_output": None,
        },
        "result": None,
        "error": None,
    }

    try:
        candidates = retrieve_symptom_candidates(
            user_text=user_text,
            number_of_results=number_of_results,
        )

        candidate_names = [c["symptom_name"] for c in candidates]
        base_record["retrieval"] = {
            "candidate_count": len(candidates),
            "candidate_names": candidate_names,
            "candidates": candidates,
        }

        if not candidates:
            result = {
                "input_text": user_text,
                "matched_symptoms": [],
                "possible_symptoms": [],
                "unmatched_expressions": [user_text],
                "retrieved_candidates": [],
                "debug_hint": "Knowledge Base에서 후보 증상을 가져오지 못했습니다. DEBUG_RETRIEVE=1로 raw retrievalResults를 확인하세요.",
            }
            base_record["status"] = "success_no_candidates"
            base_record["result"] = result
            return _finalize_record(base_record, started_perf)

        system_prompt, user_prompt = build_prompts(user_text, candidates)

        if include_prompts:
            base_record["prompts"] = {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }

        response = llm_client.converse(
            modelId=MODEL_ID,
            system=[{"text": system_prompt}],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": user_prompt}],
                }
            ],
            inferenceConfig={
                "maxTokens": 1200,
                "temperature": 0,
                "topP": 1,
            },
        )

        output_text = response["output"]["message"]["content"][0]["text"]
        base_record["model"]["raw_output"] = output_text
        base_record["model"]["response_metadata"] = response.get("ResponseMetadata", {})

        parsed = _safe_json_loads(output_text)
        allowed = set(candidate_names)

        def keep_allowed(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            clean = []
            for item in items or []:
                name = item.get("symptom_name")
                if name in allowed:
                    clean.append(item)
            return clean

        parsed["input_text"] = user_text
        parsed["matched_symptoms"] = keep_allowed(parsed.get("matched_symptoms", []))
        parsed["possible_symptoms"] = keep_allowed(parsed.get("possible_symptoms", []))
        parsed["retrieved_candidates"] = candidate_names

        base_record["status"] = "success"
        base_record["result"] = parsed
        return _finalize_record(base_record, started_perf)

    except Exception as exc:
        base_record["status"] = "error"
        base_record["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        return _finalize_record(base_record, started_perf)


def match_symptoms(user_text: str, number_of_results: int = 25) -> dict[str, Any]:
    """Compatibility wrapper: return only final result."""
    record = match_symptoms_with_trace(
        user_text=user_text,
        number_of_results=number_of_results,
        include_prompts=False,
    )
    if record.get("result") is not None:
        return record["result"]
    return {
        "input_text": user_text,
        "matched_symptoms": [],
        "possible_symptoms": [],
        "unmatched_expressions": [user_text],
        "retrieved_candidates": record.get("retrieval", {}).get("candidate_names", []),
        "error": record.get("error"),
    }


def _finalize_record(record: dict[str, Any], started_perf: float) -> dict[str, Any]:
    record["completed_at"] = now_iso()
    record["duration_ms"] = round((time.perf_counter() - started_perf) * 1000, 2)
    return record


def _safe_json_loads(text: str) -> dict[str, Any]:
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    return {
        "input_text": "",
        "matched_symptoms": [],
        "possible_symptoms": [],
        "unmatched_expressions": [],
        "raw_model_output": text,
    }


def append_json_log(log_path: str | Path, record: dict[str, Any]) -> None:
    """
    Append one run record to a JSON file.

    File shape:
    {
      "schema_version": "1.0",
      "created_at": "...",
      "updated_at": "...",
      "records": [
        {...},
        {...}
      ]
    }
    """
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            backup_path = path.with_suffix(path.suffix + f".broken-{int(time.time())}.bak")
            path.rename(backup_path)
            data = {
                "schema_version": "1.0",
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "records": [],
                "note": f"기존 로그 파일이 JSON 파싱에 실패해 {backup_path.name}로 백업되었습니다.",
            }
    else:
        data = {
            "schema_version": "1.0",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "records": [],
        }

    if isinstance(data, list):
        # Old style fallback: plain list.
        data = {
            "schema_version": "1.0",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "records": data,
        }

    if "records" not in data or not isinstance(data["records"], list):
        data["records"] = []

    data["records"].append(record)
    data["updated_at"] = now_iso()

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bedrock RAG 기반 증상 매칭 실행 및 JSON 로그 저장"
    )
    parser.add_argument(
        "text",
        nargs="*",
        help="증상 매칭을 수행할 입력 문장",
    )
    parser.add_argument(
        "--log-file",
        default=os.getenv("SYMPTOM_LOG_FILE", "symptom_match_logs.json"),
        help="실행 기록을 저장할 JSON 파일 경로. 기본값: symptom_match_logs.json",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="JSON 로그 파일을 저장하지 않음",
    )
    parser.add_argument(
        "--no-prompts",
        action="store_true",
        help="로그에 system/user prompt를 저장하지 않음",
    )
    parser.add_argument(
        "--number-of-results",
        type=int,
        default=25,
        help="Knowledge Base에서 가져올 후보 증상 수. 기본값: 25",
    )
    parser.add_argument(
        "--print-record",
        action="store_true",
        help="최종 result만 출력하지 않고 전체 log record를 출력",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    text = " ".join(args.text).strip()

    if not text:
        text = "열이 나고 기침이 심하고 숨이 차요. 가래도 있어요."

    record = match_symptoms_with_trace(
        user_text=text,
        number_of_results=args.number_of_results,
        include_prompts=not args.no_prompts,
    )

    if not args.no_log:
        append_json_log(args.log_file, record)

    if args.print_record:
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        output = record.get("result")
        if output is None:
            output = {
                "input_text": text,
                "matched_symptoms": [],
                "possible_symptoms": [],
                "unmatched_expressions": [text],
                "retrieved_candidates": record.get("retrieval", {}).get("candidate_names", []),
                "error": record.get("error"),
            }
        print(json.dumps(output, ensure_ascii=False, indent=2))

    if record.get("status") == "error":
        print(
            f"\n[ERROR] 실행 중 오류가 발생했습니다. 로그 파일에 기록되었습니다: {args.log_file}",
            file=sys.stderr,
        )
        return 1

    if not args.no_log:
        print(f"\n[LOG] saved to: {args.log_file}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

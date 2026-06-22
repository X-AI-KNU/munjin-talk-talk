from __future__ import annotations

import hashlib
import json
from typing import Any

from dialect_rag import retrieve_dialect_context
from llm import call_bedrock_json_with_meta
from schemas.dialect import validate_dialect_payload
import os

DIALECT_NORMALIZER_MODEL_ID = os.environ.get("DIALECT_NORMALIZER_MODEL_ID", "apac.amazon.nova-lite-v1:0")
DIALECT_MAX_TOKENS = int(os.environ.get("DIALECT_MAX_TOKENS", "700"))


def normalize_dialect_text(transcript: str) -> dict[str, Any]:
    """
    환자 원문을 사투리 RAG + Bedrock Nova로 표준어 변환합니다.
    transcript 자체는 절대 바꾸지 않고, standardized_text를 별도 보조 텍스트로만 사용합니다.
    """
    raw = str(transcript or "").strip()
    if not raw:
        return empty_result(raw)

    dialect_context = retrieve_dialect_context(raw)

    try:
        prompt = build_dialect_normalization_prompt(raw, dialect_context)
        obj, raw_text, chain_meta = call_bedrock_json_with_meta(
            prompt,
            DIALECT_NORMALIZER_MODEL_ID,
            DIALECT_MAX_TOKENS,
        )
    except Exception as exc:
        return {
            **empty_result(raw),
            "validator_passed": False,
            "errors": [
                {
                    "field": "bedrock",
                    "type": exc.__class__.__name__,
                    "message": "Dialect normalization Bedrock call failed.",
                }
            ],
            "dialect_context": summarize_dialect_context(dialect_context),
        }

    validated, errors = validate_dialect_payload(obj, raw)
    if errors:
        return {
            **empty_result(raw),
            "validator_passed": False,
            "errors": errors[:5],
            "dialect_context": summarize_dialect_context(dialect_context),
            "llm_meta": {
                "model_id": DIALECT_NORMALIZER_MODEL_ID,
                "raw_sha256": hashlib.sha256(str(raw_text or "").encode("utf-8")).hexdigest(),
                "langchain": chain_meta,
            },
        }

    return {
        **validated,
        "validator_passed": True,
        "errors": [],
        "dialect_context": summarize_dialect_context(dialect_context),
        "llm_meta": {
            "model_id": DIALECT_NORMALIZER_MODEL_ID,
            "raw_sha256": hashlib.sha256(str(raw_text or "").encode("utf-8")).hexdigest(),
            "langchain": chain_meta,
        },
    }


def build_dialect_normalization_prompt(
    transcript: str,
    dialect_context: dict[str, Any],
) -> str:
    transcript_json = json.dumps(transcript, ensure_ascii=False)
    return f"""
You are a Korean dialect normalization component for a clinic intake system.

Goal:
Convert the patient's Gangwon/Gangneung dialect or colloquial Korean into standard Korean.

Critical rules:
- Return JSON only. No markdown.
- Never diagnose.
- Do not add symptoms, medications, dates, severity, disease names, tests, or facts absent from the original text.
- Keep the medical meaning unchanged.
- original_text MUST be exactly the same as the original patient text.
- source_quote MUST be copied as an exact continuous substring from original_text.
- Use Dialect RAG hints only as weak vocabulary reference.
- If no dialect expression needs conversion, standardized_text may equal original_text.
- Do NOT output score, confidence, probability, certainty, or risk percentage fields.

Original patient text:
{transcript}

{dialect_context.get("prompt_note") or ""}

Return exactly this JSON shape:
{{
  "original_text": {transcript_json},
  "standardized_text": "standard Korean sentence preserving the same meaning",
  "replacements": [
    {{
      "source_quote": "exact substring from original_text",
      "standard_text": "standard Korean replacement",
      "evidence_dialect": "dialect dictionary term if used, otherwise empty string",
      "evidence_standard": "standard Korean dictionary term if used, otherwise empty string",
      "match_type": "exact|partial|llm_context|unchanged"
    }}
  ],
  "unmatched_phrases": []
}}
""".strip()


def summarize_dialect_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "retriever": context.get("retriever"),
        "source_files": context.get("source_files") or [],
        "hints": [
            {
                "dialect": item.get("dialect"),
                "standard": item.get("standard"),
                "match_type": item.get("match_type"),
            }
            for item in (context.get("hints") or [])[:8]
        ],
    }


def empty_result(transcript: str) -> dict[str, Any]:
    return {
        "original_text": transcript or "",
        "standardized_text": transcript or "",
        "replacements": [],
        "unmatched_phrases": [],
        "validator_passed": True,
        "errors": [],
        "dialect_context": {
            "retriever": "local_dialect_rag",
            "source_files": ["dialect_packs/dialect_kangwon.json"],
            "hints": [],
        },
    }

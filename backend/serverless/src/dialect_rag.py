from __future__ import annotations

import os
from typing import Any

from dialect_config import load_dialect_entries
from utils import compact_ir, normalize_text


def _dialect_top_k() -> int:
    return int(os.environ.get("DIALECT_TOP_K", "8"))


def retrieve_dialect_context(text: str, top_k: int | None = None) -> dict[str, Any]:
    query = normalize_text(text or "")
    compact_query = compact_ir(query)
    limit = int(top_k or _dialect_top_k())

    if not query:
        return empty_dialect_context()

    rows = []

    for item in load_dialect_entries():
        dialect = normalize_text(item.get("dialect") or "")
        standard = normalize_text(item.get("standard") or "")
        if not dialect or not standard:
            continue

        compact_dialect = compact_ir(dialect)
        if not compact_dialect:
            continue

        if dialect in query or compact_dialect in compact_query:
            rows.append(
                {
                    "dialect": dialect,
                    "standard": standard,
                    "match_type": "exact",
                    "score": 1.0 + min(len(compact_dialect), 12) / 100,
                    "source_file": item.get("source_file") or "",
                }
            )
            continue

        if len(compact_dialect) >= 2:
            score = char_ngram_score(compact_query, compact_dialect)
            if score >= 0.72:
                rows.append(
                    {
                        "dialect": dialect,
                        "standard": standard,
                        "match_type": "partial",
                        "score": round(score, 4),
                        "source_file": item.get("source_file") or "",
                    }
                )

    rows.sort(key=lambda item: item.get("score", 0), reverse=True)
    hints = dedupe_hints(rows)[:limit]

    context = {
        "retriever": "local_dialect_rag",
        "source_files": ["dialect_packs/dialect_kangwon.json"],
        "hints": hints,
    }
    context["prompt_note"] = build_dialect_prompt_note(context)
    return context


def char_ngram_score(query: str, term: str, n: int = 2) -> float:
    if not query or not term:
        return 0.0

    q_grams = ngrams(query, n)
    t_grams = ngrams(term, n)

    if not q_grams or not t_grams:
        return 0.0

    overlap = len(q_grams & t_grams)
    return overlap / max(1, len(t_grams))


def ngrams(text: str, n: int) -> set[str]:
    if len(text) <= n:
        return {text}
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def dedupe_hints(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()

    for item in items:
        key = (item.get("dialect"), item.get("standard"))
        if key in seen:
            continue
        seen.add(key)

        cleaned = dict(item)
        cleaned.pop("score", None)
        out.append(cleaned)

    return out


def empty_dialect_context() -> dict[str, Any]:
    return {
        "retriever": "local_dialect_rag",
        "source_files": ["dialect_packs/dialect_kangwon.json"],
        "hints": [],
        "prompt_note": "",
    }


def build_dialect_prompt_note(context: dict[str, Any]) -> str:
    hints = context.get("hints") or []
    if not hints:
        return ""

    lines = [
        "Dialect RAG hints for standard Korean normalization.",
        "Use these only to understand dialect vocabulary.",
        "Do not add symptoms, diagnoses, medications, dates, severity, or facts absent from the original patient answer.",
        "The original patient answer remains the only source for source_quote/original_quote.",
        "Hints:",
    ]

    for item in hints:
        lines.append(
            f"- dialect '{item.get('dialect')}' means standard Korean '{item.get('standard')}' "
            f"(match_type={item.get('match_type')})."
        )

    return "\n".join(lines)

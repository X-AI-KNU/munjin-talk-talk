"""문진 extraction 전에 붙이는 경량 RAG 컨텍스트.

이 모듈은 환자 발화에서 증상을 직접 추출하지 않습니다. LLM이 표준화와
의미 분할을 할 때 참고할 수 있도록, 이미 보유한 원천 JSON 기반 증상 문서와
제한된 alias bridge에서 관련 문구를 검색해 prompt context로 제공합니다.

중요 원칙:
- RAG 결과는 "참고 근거"일 뿐 최종 추출값이 아닙니다.
- source_quote는 여전히 환자 원문에서만 나와야 합니다.
- 증상 매칭의 최종 결정은 뒤 단계의 Hybrid IR이 수행합니다.
"""

from __future__ import annotations

import re
from typing import Any

from clinical_terms import IR_TEXT_ALIASES
from domain_config import excluded_ir_symptom_names, selected_domain_pack_id
from retrieval_documents import get_ir_index
from settings import DISEASES_PATH, SYMPTOM_INDEX_PATH
from utils import clean_quote, normalize_text


EXCLUDED_IR_SYMPTOM_NAMES = excluded_ir_symptom_names()


def rag_source_files() -> list[str]:
    """현재 배포 패키지에 맞는 RAG 참조 출처를 trace에 남깁니다."""
    if DISEASES_PATH.exists() and SYMPTOM_INDEX_PATH.exists():
        return ["diseases_cleaned.json", "symptom_index.json", "clinical_terms.IR_TEXT_ALIASES"]
    return [f"domain_packs/{selected_domain_pack_id()}.json", "clinical_terms.IR_TEXT_ALIASES"]


def retrieve_intake_rag_context(
    transcript: str,
    question_type: str | None = None,
    top_k: int = 4,
) -> dict[str, Any]:
    """환자 발화와 가까운 표준 증상 문서와 구어체 힌트를 검색합니다."""
    query = normalize_text(transcript)
    if not query:
        return empty_rag_context()

    symptom_refs = retrieve_symptom_references(query, top_k=top_k)
    alias_hints = retrieve_alias_hints(query)
    context = {
        "retriever": "local_reference_rag",
        "source_files": rag_source_files(),
        "question_type": question_type or "",
        "query_chars": len(query),
        "alias_hints": alias_hints,
        "symptom_references": symptom_refs,
    }
    context["prompt_note"] = build_rag_prompt_note(context)
    return context


def empty_rag_context() -> dict[str, Any]:
    """검색할 원문이 없을 때도 trace 구조를 일정하게 유지합니다."""
    return {
        "retriever": "local_reference_rag",
        "source_files": rag_source_files(),
        "question_type": "",
        "query_chars": 0,
        "alias_hints": [],
        "symptom_references": [],
        "prompt_note": "",
    }


def retrieve_symptom_references(query: str, top_k: int = 4) -> list[dict[str, Any]]:
    """BM25로 원천 JSON 기반 증상 문서 중 관련 후보를 가져옵니다."""
    docs, bm25 = get_ir_index()
    scores = bm25.scores(query)
    ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
    refs: list[dict[str, Any]] = []
    for idx, score in ranked:
        if len(refs) >= max(0, top_k):
            break
        if score <= 0:
            continue
        doc = docs[idx]
        if doc.get("display_name") in EXCLUDED_IR_SYMPTOM_NAMES:
            continue
        refs.append(
            {
                "symptom_id": doc.get("symptom_id"),
                "display_name": doc.get("display_name"),
                "bm25_score": round(float(score), 4),
                "departments": doc.get("departments", [])[:3],
                "evidence": [
                    {
                        "disease_name": item.get("disease_name"),
                        "section": item.get("section"),
                        "text": item.get("text"),
                    }
                    for item in (doc.get("evidence") or [])[:2]
                ],
            }
        )
    return refs


def retrieve_alias_hints(query: str) -> list[dict[str, str]]:
    """표준명/alias bridge에서 환자 표현과 직접 닿는 힌트를 찾습니다."""
    hints = []
    for pattern, canonical_name in IR_TEXT_ALIASES:
        match = re.search(pattern, query)
        if not match:
            continue
        hints.append(
            {
                "matched_text": clean_quote(match.group(0)),
                "canonical_hint": canonical_name,
                "pattern": pattern,
            }
        )
    return hints[:5]


def build_rag_prompt_note(context: dict[str, Any]) -> str:
    """LLM prompt에 넣을 짧은 RAG 참고 문단을 만듭니다."""
    alias_hints = context.get("alias_hints") or []
    symptom_refs = context.get("symptom_references") or []
    if not alias_hints and not symptom_refs:
        return ""

    lines = [
        "Retrieved reference context for normalization. Use this only as weak context, not as patient facts.",
        "The patient transcript remains the only source for source_quote/original_quote.",
        "Do not add symptoms, diagnoses, tests, or medications just because they appear below.",
    ]
    if alias_hints:
        lines.append("Colloquial/alias hints:")
        for item in alias_hints:
            lines.append(f"- '{item.get('matched_text')}' may align with standard wording '{item.get('canonical_hint')}'.")
    if symptom_refs:
        lines.append("Nearby symptom reference documents from source JSON:")
        for item in symptom_refs:
            evidence_text = "; ".join(
                clean_quote(evidence.get("text"))
                for evidence in item.get("evidence", [])
                if clean_quote(evidence.get("text"))
            )
            if evidence_text:
                lines.append(f"- {item.get('display_name')}: {evidence_text}")
            else:
                lines.append(f"- {item.get('display_name')}")
    return "\n".join(lines)

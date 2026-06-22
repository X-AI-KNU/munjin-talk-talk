from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_dialect_pack_loads():
    from dialect_config import load_dialect_entries

    entries = load_dialect_entries("dialect_kangwon")

    assert isinstance(entries, list)
    assert entries
    assert all(item.get("dialect") and item.get("standard") for item in entries[:5])


def test_dialect_rag_returns_context_shape():
    from dialect_rag import retrieve_dialect_context

    context = retrieve_dialect_context("사투리 원문 테스트")

    assert context["retriever"] == "local_dialect_rag"
    assert "hints" in context
    assert "prompt_note" in context


def test_dialect_schema_rejects_ungrounded_quote():
    from schemas.dialect import validate_dialect_payload

    transcript = "코가 맥혀요"
    obj = {
        "original_text": transcript,
        "standardized_text": "코가 막혀요",
        "replacements": [
            {
                "source_quote": "없는 말",
                "standard_text": "막혀요",
                "evidence_dialect": "맥혀요",
                "evidence_standard": "막혀요",
                "match_type": "exact",
            }
        ],
        "unmatched_phrases": [],
    }

    normalized, errors = validate_dialect_payload(obj, transcript)

    assert normalized is None
    assert errors

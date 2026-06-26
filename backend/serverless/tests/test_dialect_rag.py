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
    assert entries[0]["dialect"] == "(때를)에우다"
    assert entries[0]["standard"] == "(끼니를) 잇다"


def test_dialect_rag_returns_context_shape():
    from dialect_rag import retrieve_dialect_context

    context = retrieve_dialect_context("여매방아라는 말을 들었습니다")

    assert context["retriever"] == "local_dialect_rag"
    assert "hints" in context
    assert "prompt_note" in context
    assert context["hints"][0]["dialect"] == "여매방아"
    assert context["hints"][0]["standard"] == "연자방아"
    assert all(len(item["dialect"]) >= 2 for item in context["hints"])


def test_dialect_rag_matches_parenthetical_and_conjugated_variants():
    from dialect_rag import retrieve_dialect_context

    context = retrieve_dialect_context("가슴이 제리제리해", top_k=3)
    pairs = {(item["dialect"], item["standard"]) for item in context["hints"]}

    assert ("가슴이 제리제리해", "저리다") in pairs


def test_dialect_schema_rejects_ungrounded_quote():
    from schemas.dialect import validate_dialect_payload

    transcript = "여매방아라고 했어요"
    obj = {
        "original_text": transcript,
        "standardized_text": "연자방아라고 했어요",
        "replacements": [
            {
                "source_quote": "없는 말",
                "standard_text": "연자방아",
                "evidence_dialect": "여매방아",
                "evidence_standard": "연자방아",
                "match_type": "exact",
            }
        ],
        "unmatched_phrases": [],
    }

    normalized, errors = validate_dialect_payload(obj, transcript)

    assert normalized is None
    assert errors

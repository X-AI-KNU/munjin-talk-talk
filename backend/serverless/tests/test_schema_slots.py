"""LLM extraction slot_ref 계약 테스트."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from domain_config import get_domain_pack, llm_symptom_slot_ids  # noqa: E402
from schemas.extraction import validate_extraction_payload  # noqa: E402


def payload_with_slot(slot_ref: str) -> dict:
    return {
        "spans": [
            {
                "source_quote": "기침이 나요",
                "type": "symptom",
                "slot_ref": slot_ref,
                "name": "기침",
                "normalized_text": "기침",
                "status": "있음",
                "alert": False,
                "explain": "환자가 기침을 말했습니다.",
            }
        ],
        "structured": {
            "standardized_text": "기침이 납니다.",
            "clinical_clues": [],
            "questions": [],
            "unresolved_items": [],
        },
    }


def assert_slot_error(slot_ref: str):
    _, errors = validate_extraction_payload(payload_with_slot(slot_ref), "기침이 나요")
    assert errors
    return " ".join(error.get("message", "") for error in errors)


def test_ir_only_slot_ref_is_rejected():
    pack = get_domain_pack()
    llm_slots = set(llm_symptom_slot_ids())
    ir_only_slots = sorted(set(pack.get("ir_slot_to_canonical_name") or {}) - llm_slots)
    if not ir_only_slots:
        pytest.skip("Current clean train-derived domain pack has no IR-only slots.")
    assert_slot_error(ir_only_slots[0])


def test_empty_slot_ref_is_rejected_without_defaulting_to_other():
    assert_slot_error("")


def test_unknown_slot_error_lists_allowed_values():
    message = assert_slot_error("zzz")
    assert "cough" in message
    assert "other" in message


def test_llm_slots_accept_cough_and_other():
    for slot_ref in ("cough", "other"):
        normalized, errors = validate_extraction_payload(payload_with_slot(slot_ref), "기침이 나요")
        assert errors == []
        assert normalized["spans"][0]["slot_ref"] == slot_ref

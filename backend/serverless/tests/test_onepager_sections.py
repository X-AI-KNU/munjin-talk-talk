"""Onepager section normalization tests."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from onepager_sections import normalize_agenda  # noqa: E402


def test_normalize_agenda_splits_multiple_patient_questions():
    q4 = {
        "structured": {
            "questions": [
                {
                    "category": "supplement_drug_interaction",
                    "summary": "홍삼과 약 병용 및 진통제 문의",
                    "original_quote": (
                        "뭐 홍삼같이 좀 약이랑 먹으라고 하는데 괜찮은 건지 좀 알고 싶고. "
                        "머리가 너무 아파가지고 진통제도 좀 줄 수 있나"
                    ),
                }
            ]
        }
    }

    agenda = normalize_agenda(q4)

    assert len(agenda) == 2
    assert agenda[0]["category"] == "supplement_drug_interaction"
    assert agenda[0]["type_label"] == "영양제 병용"
    assert "홍삼" in agenda[0]["original_quote"]
    assert "홍삼과 약" in agenda[0]["summary"]
    assert agenda[1]["category"] == "other"
    assert agenda[1]["type_label"] == "환자 질문"
    assert "진통제" in agenda[1]["original_quote"]
    assert "진통제" in agenda[1]["summary"]


def test_normalize_agenda_preserves_single_patient_question():
    q4 = {
        "structured": {
            "questions": [
                {
                    "category": "treatment_duration",
                    "summary": "약을 언제까지 먹어야 하는지 문의",
                    "original_quote": "이 약을 언제까지 먹어야 되나요",
                }
            ]
        }
    }

    agenda = normalize_agenda(q4)

    assert agenda == [
        {
            "type": "treatment_duration",
            "category": "treatment_duration",
            "type_label": "복약 기간",
            "summary": "약을 언제까지 먹어야 하는지 문의",
            "original_quote": "이 약을 언제까지 먹어야 되나요",
            "source_question": "Q4",
        }
    ]

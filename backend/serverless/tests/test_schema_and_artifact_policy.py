"""백엔드 핵심 안전장치 회귀 테스트.

이 테스트는 AWS에 접속하지 않고 Pydantic schema와 운영 artifact 정책만 확인합니다.
LLM 호출 품질은 실제 Bedrock 통합 테스트에서 봐야 하지만, 아래 조건은 로컬에서도
반드시 유지되어야 합니다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from artifact_policy import sanitize_matched_slot  # noqa: E402
from schemas.extraction import validate_extraction_payload  # noqa: E402


class ExtractionSchemaTest(TestCase):
    def test_source_quote_must_be_grounded_in_patient_answer(self):
        transcript = "어제부터 목이 칼칼하고 코가 막혀요."
        payload = {
            "spans": [
                {
                    "source_quote": "열이 많이 나요",
                    "type": "symptom",
                    "slot_ref": "fever",
                    "name": "발열",
                    "normalized_text": "열이 남",
                    "status": "있음",
                    "alert": False,
                    "explain": "환자가 열을 호소했습니다.",
                }
            ],
            "structured": {
                "standardized_text": transcript,
                "clinical_clues": [],
                "questions": [],
                "unresolved_items": [],
            },
        }

        normalized, errors = validate_extraction_payload(payload, transcript)

        self.assertIsNone(normalized)
        self.assertTrue(errors)

    def test_unknown_llm_field_is_rejected(self):
        transcript = "기침이 계속 나요."
        payload = {
            "spans": [
                {
                    "source_quote": "기침이 계속 나요",
                    "type": "symptom",
                    "slot_ref": "cough",
                    "name": "기침",
                    "normalized_text": "기침이 지속됨",
                    "status": "있음",
                    "alert": False,
                    "explain": "환자가 기침 지속을 말했습니다.",
                    "confidence": 0.92,
                }
            ],
            "structured": {
                "standardized_text": transcript,
                "clinical_clues": [],
                "questions": [],
                "unresolved_items": [],
            },
        }

        normalized, errors = validate_extraction_payload(payload, transcript)

        self.assertIsNone(normalized)
        self.assertTrue(any("confidence" in error.get("field", "") for error in errors))

    def test_domain_pack_slot_ref_is_accepted(self):
        transcript = "목이 칼칼하고 코가 막혀요."
        payload = {
            "spans": [
                {
                    "source_quote": "목이 칼칼하고",
                    "type": "symptom",
                    "slot_ref": "throat_irritation",
                    "name": "목 불편감",
                    "normalized_text": "목 자극감",
                    "status": "있음",
                    "alert": False,
                    "explain": "환자가 목 칼칼함을 말했습니다.",
                }
            ],
            "structured": {
                "standardized_text": transcript,
                "clinical_clues": [],
                "questions": [],
                "unresolved_items": [],
            },
        }

        normalized, errors = validate_extraction_payload(payload, transcript)

        self.assertFalse(errors)
        self.assertEqual(normalized["spans"][0]["slot_ref"], "throat_irritation")


class ArtifactPolicyTest(TestCase):
    def test_operational_symptom_slot_removes_numeric_scores_and_candidates(self):
        slot = {
            "slot_id": "cough",
            "name": "기침",
            "source_quote": "기침이 계속 나요",
            "score": 0.91,
            "rank_score": 1.28,
            "ir_trace": {"top_candidates": [{"name": "기침"}]},
            "ir_method": "bm25_titan_hybrid",
        }

        cleaned = sanitize_matched_slot(slot)

        self.assertEqual(cleaned["slot_id"], "cough")
        self.assertNotIn("score", cleaned)
        self.assertNotIn("rank_score", cleaned)
        self.assertNotIn("ir_trace", cleaned)

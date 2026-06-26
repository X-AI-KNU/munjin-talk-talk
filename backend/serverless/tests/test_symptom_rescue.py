"""Deterministic symptom rescue tests."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DATA = SRC / "data"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _NoNetworkBedrock:
    def invoke_model(self, **_kwargs):  # pragma: no cover
        raise RuntimeError("Bedrock must not be called in this unit test")


def install_settings_stub():
    for name in [
        "settings",
        "domain_config",
        "clinical_terms",
        "retrieval_documents",
        "retrieval_embeddings",
        "rag_context",
        "retrieval",
        "onepager",
        "pipeline_nodes",
    ]:
        sys.modules.pop(name, None)

    required = [
        DATA / "diseases_cleaned.json",
        DATA / "symptom_index.json",
        DATA / "symptom_embeddings_amazon.titan-embed-text-v2_0_512.json",
    ]
    missing = [path.name for path in required if not path.exists()]
    if missing:
        pytest.skip("private IR data missing: " + ", ".join(missing))

    settings = types.ModuleType("settings")
    settings.DATA_DIR = DATA
    settings.DISEASES_PATH = DATA / "diseases_cleaned.json"
    settings.SYMPTOM_INDEX_PATH = DATA / "symptom_index.json"
    settings.EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
    settings.EMBEDDING_DIMENSIONS = 512
    settings.EMBEDDING_CACHE_PATH = DATA / "symptom_embeddings_amazon.titan-embed-text-v2_0_512.json"
    settings.HYBRID_TOP_K = 5
    settings.HYBRID_CANDIDATE_K = 24
    settings.HYBRID_ACCEPT_THRESHOLD = 0.18
    settings.HYBRID_BM25_WEIGHT = 0.35
    settings.HYBRID_VECTOR_WEIGHT = 0.65
    settings.HYBRID_MIN_VECTOR_SCORE = 0.12
    settings.HYBRID_MIN_BM25_SCORE = 0.04
    settings.HYBRID_MIN_LABEL_SCORE = 0.55
    settings.MAX_LLM_TOKENS = 900
    settings.EXTRACTION_RETRY_ATTEMPTS = 2
    settings.LIGHT_MODEL_ID = "apac.amazon.nova-lite-v1:0"
    settings.STRONG_MODEL_ID = "apac.amazon.nova-pro-v1:0"
    settings.bedrock_runtime = _NoNetworkBedrock()
    sys.modules["settings"] = settings

    onepager = types.ModuleType("onepager")
    onepager.validate_and_save = lambda *_args, **_kwargs: ({}, None)
    sys.modules["onepager"] = onepager


def test_followup_q3_chest_tightness_rescue_reaches_ir():
    install_settings_stub()
    from pipeline_nodes import preserve_known_symptom_context  # noqa: E402
    from retrieval import match_slots  # noqa: E402

    state = {
        "question_id": "Q3",
        "question_type": "new_symptoms",
        "visit_type": "followup",
        "transcript": "요즘에는 가슴도 답답해지는 것 같아",
        "extraction_attempt": 2,
        "extraction_chain_meta": {"model_id": "unit-test"},
        "extraction_raw_text": "",
        "rag_context": {},
        "trace": [],
        "active_path": [],
    }

    rescued = preserve_known_symptom_context(
        state,
        reason="schema_quote_failed_after_retries",
        validation_errors=[{"loc": ["spans"], "msg": "missing"}],
    )

    assert rescued is not None
    extracted = rescued["extracted"]
    assert extracted["method"] == "deterministic_symptom_rescue"
    assert extracted["structured"]["standardized_text"] == "가슴이 답답해집니다."
    assert extracted["structured"]["clinical_clues"][0]["category"] == "재진경과"
    assert extracted["structured"]["clinical_clues"][0]["label"] == "새 증상"

    matched = match_slots({"spans": extracted["spans"]})
    assert matched["unmatched_spans"] == []
    assert matched["matched_slots"][0]["slot_id"] == "chest_discomfort"
    assert matched["matched_slots"][0]["name"] == "가슴 답답"


def test_safety_flag_routes_to_guardrail_when_semantic_extraction_fails():
    install_settings_stub()
    from pipeline_nodes import quick_safety_flag_node, schema_quote_validation_node  # noqa: E402

    base_state = {
        "question_id": "Q1",
        "question_type": "chief_complaint",
        "visit_type": "initial",
        "transcript": "가심이 답답허고 코물이 줄줄 나와요",
        "trace": [],
        "active_path": [],
    }

    safety_update = quick_safety_flag_node(base_state)
    assert safety_update["preliminary_safety_flag"]["category"] == "chest_discomfort"

    validation_update = schema_quote_validation_node({
        **base_state,
        **safety_update,
        "semantic_failed": True,
        "extracted": {"error": "bedrock_or_schema_failed"},
        "extraction_raw": None,
        "extraction_attempt": 3,
    })

    assert validation_update["safety_only"] is True
    assert "error_response" not in validation_update

"""IR 잡음 후보와 안전 플래그 도메인팩 계약 테스트."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DATA = SRC / "data"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _NoNetworkBedrock:
    """테스트 중 Bedrock 네트워크 호출이 일어나면 즉시 실패시키는 더미입니다."""

    def invoke_model(self, **_kwargs):  # pragma: no cover - 실패 방어용
        raise RuntimeError("Bedrock must not be called in this unit test")


def install_settings_stub():
    """검색 모듈이 실제 AWS settings.py를 읽지 않도록 필요한 값만 주입합니다."""
    for name in [
        "settings",
        "clinical_terms",
        "retrieval_documents",
        "retrieval_embeddings",
        "rag_context",
        "retrieval",
    ]:
        sys.modules.pop(name, None)
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
    settings.bedrock_runtime = _NoNetworkBedrock()
    sys.modules["settings"] = settings


def test_rag_references_exclude_operational_noise_symptoms():
    install_settings_stub()
    from rag_context import retrieve_symptom_references  # noqa: E402

    refs = retrieve_symptom_references("무증상 사망", top_k=10)
    display_names = {item["display_name"] for item in refs}

    assert "무증상" not in display_names
    assert "사망" not in display_names


def test_excluding_noise_does_not_change_packaged_embedding_docs_hash():
    install_settings_stub()
    from retrieval_documents import get_ir_index  # noqa: E402
    from retrieval_embeddings import docs_hash  # noqa: E402

    docs, _ = get_ir_index()
    packaged = json.loads((DATA / "symptom_embeddings_amazon.titan-embed-text-v2_0_512.json").read_text(encoding="utf-8"))

    assert packaged["docs_hash"] == docs_hash(docs)


def test_find_safety_flag_uses_domain_pack_alert_slots():
    install_settings_stub()
    from clinical_terms import find_safety_flag  # noqa: E402

    flag = find_safety_flag("", [{"slot_id": "dyspnea", "name": "호흡곤란"}])

    assert flag is not None
    assert flag["category"] == "dyspnea"
    assert flag["severity"] == "high"

"""IR 잡음 후보와 안전 플래그 도메인팩 계약 테스트."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DATA = SRC / "data"
PRIVATE_IR_FILES = [
    DATA / "diseases_cleaned.json",
    DATA / "symptom_index.json",
    DATA / "symptom_embeddings_amazon.titan-embed-text-v2_0_512.json",
]
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


def require_private_ir_data():
    """공개 저장소에서 제외한 IR 원천 데이터가 없으면 관련 테스트만 건너뜁니다."""
    missing = [path.name for path in PRIVATE_IR_FILES if not path.exists()]
    if missing:
        pytest.skip("비공개 IR 원천 데이터가 없는 환경에서는 IR 데이터 의존 테스트를 건너뜁니다: " + ", ".join(missing))


def test_rag_references_exclude_operational_noise_symptoms():
    require_private_ir_data()
    install_settings_stub()
    from rag_context import retrieve_symptom_references  # noqa: E402

    refs = retrieve_symptom_references("무증상 사망", top_k=10)
    display_names = {item["display_name"] for item in refs}

    assert "무증상" not in display_names
    assert "사망" not in display_names


def test_excluding_noise_does_not_change_packaged_embedding_docs_hash():
    require_private_ir_data()
    install_settings_stub()
    from retrieval_documents import get_ir_index  # noqa: E402
    from retrieval_embeddings import docs_hash  # noqa: E402

    docs, _ = get_ir_index()
    packaged = json.loads((DATA / "symptom_embeddings_amazon.titan-embed-text-v2_0_512.json").read_text(encoding="utf-8"))

    assert packaged["docs_hash"] == docs_hash(docs)


def test_ir_index_falls_back_to_domain_pack_when_source_json_missing(tmp_path):
    """공개 배포 패키지에 비공개 IR 원천 JSON이 없어도 최소 IR 문서가 만들어져야 합니다."""
    install_settings_stub()
    import settings  # noqa: E402

    settings.DISEASES_PATH = tmp_path / "missing_diseases_cleaned.json"
    settings.SYMPTOM_INDEX_PATH = tmp_path / "missing_symptom_index.json"

    from retrieval_documents import get_ir_index  # noqa: E402

    docs, bm25 = get_ir_index()
    display_names = {doc["display_name"] for doc in docs}
    sources = {doc.get("source") for doc in docs}

    assert "기침" in display_names
    assert "코막힘" in display_names
    assert "domain_pack_fallback" in sources
    assert max(bm25.scores("기침 콜록")) > 0


def test_find_safety_flag_uses_domain_pack_alert_slots():
    install_settings_stub()
    from clinical_terms import find_safety_flag  # noqa: E402

    flag = find_safety_flag("", [{"slot_id": "dyspnea", "name": "호흡곤란"}])

    assert flag is not None
    assert flag["category"] == "dyspnea"
    assert flag["severity"] == "high"


def test_safety_flag_rules_cover_six_domain_categories():
    install_settings_stub()
    from clinical_terms import find_safety_flag  # noqa: E402

    cases = [
        ("가래에 피가 섞여 나와요", "hemoptysis"),
        ("숨이 너무 차서 말을 못 하겠어요", "dyspnea"),
        ("가슴이 쥐어짜듯 아파요", "chest_pain"),
        ("입술이 파래졌어요", "cyanosis"),
        ("갑자기 기절하고 의식을 잃었어요", "consciousness"),
        ("열이 39도까지 올라요", "high_fever"),
    ]

    for text, category in cases:
        flag = find_safety_flag(text)
        assert flag is not None
        assert flag["category"] == category


def test_rag_alias_hint_maps_colloquial_nasal_obstruction():
    require_private_ir_data()
    install_settings_stub()
    from rag_context import retrieve_intake_rag_context  # noqa: E402

    context = retrieve_intake_rag_context("코가 맥혀요", top_k=3)
    hints = context["alias_hints"]

    assert any(item["canonical_hint"] == "코막힘" for item in hints)


def test_hybrid_ir_acceptance_gate_matrix():
    install_settings_stub()
    from retrieval import is_hybrid_candidate_accepted  # noqa: E402

    accepted_by_bm25, _ = is_hybrid_candidate_accepted({
        "vector_score": 0.12,
        "bm25_score": 0.04,
        "label_score": 0.0,
    })
    accepted_by_label, _ = is_hybrid_candidate_accepted({
        "vector_score": 0.20,
        "bm25_score": 0.0,
        "label_score": 0.55,
    })
    rejected_no_lexical, reason_no_lexical = is_hybrid_candidate_accepted({
        "vector_score": 0.20,
        "bm25_score": 0.0,
        "label_score": 0.0,
    })
    rejected_no_vector, reason_no_vector = is_hybrid_candidate_accepted({
        "vector_score": 0.01,
        "bm25_score": 0.80,
        "label_score": 1.0,
    })

    assert accepted_by_bm25 is True
    assert accepted_by_label is True
    assert rejected_no_lexical is False
    assert "hybrid_gate_failed" in reason_no_lexical
    assert rejected_no_vector is False
    assert "hybrid_gate_failed" in reason_no_vector


def test_missing_domain_pack_raises_clear_exception():
    install_settings_stub()
    from domain_config import get_domain_pack  # noqa: E402

    try:
        get_domain_pack("not-found-pack")
    except FileNotFoundError:
        # load_json_file가 실제 파일 없음 위치를 명확히 알려주면 충분히 실패-명시적입니다.
        return
    raise AssertionError("missing domain pack must fail loudly")

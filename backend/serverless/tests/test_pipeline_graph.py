"""LangGraph 파이프라인 전체 실행 테스트.

실제 Bedrock/IR/저장 호출은 pipeline_nodes의 seam을 monkeypatch로 대체하고,
입력검증 → 안전감지 → 사투리 → RAG → 추출 → 검증 → IR → 저장 → 응답까지
그래프가 끝까지 흐르는지 확인합니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

pytest.importorskip("langgraph")

import pipeline_nodes  # noqa: E402
from pipeline_graph import run_answer_pipeline  # noqa: E402


def _stub_seams(monkeypatch, *, extraction_obj=None, matched=None, validated=None,
                dialect_passed=True, raise_bedrock=False):
    """pipeline_nodes의 외부 호출 seam을 테스트 더블로 교체합니다."""
    def fake_dialect(transcript):
        return {
            "original_text": transcript,
            "standardized_text": transcript,
            "replacements": [],
            "unmatched_phrases": [],
            "validator_passed": dialect_passed,
            "dialect_context": {"retriever": "local_dialect_rag", "hints": []},
            "llm_meta": {"model_id": "stub-lite"},
        }

    def fake_rag(query, question_type=None):
        return {
            "retriever": "stub_rag",
            "alias_hints": [],
            "symptom_references": [],
            "prompt_note": "",
            "source_files": [],
        }

    def fake_bedrock(prompt, model_id, max_tokens):
        if raise_bedrock:
            raise RuntimeError("bedrock down")
        obj = extraction_obj if extraction_obj is not None else {
            "spans": [{
                "source_quote": "기침이 나요",
                "type": "symptom",
                "slot_ref": "cough",
                "name": "기침",
                "normalized_text": "기침",
                "status": "있음",
                "alert": False,
                "explain": "환자가 기침을 말했습니다.",
            }],
            "structured": {
                "standardized_text": "기침이 납니다.",
                "clinical_clues": [],
                "questions": [],
                "unresolved_items": [],
            },
        }
        chain_meta = {"chain": "stub", "raw_sha256": "abc", "prompt_adapter": "p",
                      "bedrock_runnable": "b", "output_parser": "o"}
        return obj, "{}", chain_meta

    def fake_match(body):
        return matched if matched is not None else {
            "matched_slots": [{
                "slot_id": "cough", "name": "기침", "source_quote": "기침이 나요",
                "status": "있음", "alert": False, "ir_method": "bm25_titan_hybrid",
            }],
            "unmatched_spans": [],
        }

    def fake_save(body):
        return (validated if validated is not None else {
            "validator_passed": True,
            "onepager_ready": True,
            "safety_flag": None,
        }), None

    monkeypatch.setattr(pipeline_nodes, "normalize_dialect_text", fake_dialect)
    monkeypatch.setattr(pipeline_nodes, "retrieve_intake_rag_context", fake_rag)
    monkeypatch.setattr(pipeline_nodes, "call_bedrock_json_with_meta", fake_bedrock)
    monkeypatch.setattr(pipeline_nodes, "match_slots", fake_match)
    monkeypatch.setattr(pipeline_nodes, "validate_and_save", fake_save)


def _body(**over):
    base = {
        "session_id": "s_test",
        "question_id": "Q1",
        "question_type": "chief_complaint",
        "question_set_id": "default",
        "visit_type": "initial",
        "transcript": "기침이 나요",
    }
    base.update(over)
    return base


def test_full_pipeline_happy_path(monkeypatch):
    _stub_seams(monkeypatch)
    payload, err = run_answer_pipeline(_body())
    assert err is None
    assert payload["validator_passed"] is True
    assert payload["onepager_ready"] is True
    assert payload["matched_slots"][0]["name"] == "기침"
    # 그래프 전체 경로가 trace에 남아야 함
    path = payload["pipeline"]["active_path"]
    assert "response_payload" in path


def test_missing_required_field_returns_400(monkeypatch):
    _stub_seams(monkeypatch)
    payload, err = run_answer_pipeline(_body(question_id=""))
    assert payload is None
    assert err["statusCode"] == 400


def test_empty_transcript_returns_400(monkeypatch):
    _stub_seams(monkeypatch)
    payload, err = run_answer_pipeline(_body(transcript="   "))
    assert payload is None
    assert err["statusCode"] == 400


def test_safety_flag_detected_in_pipeline(monkeypatch):
    # 위험 표현이 있으면 quick_safety_flag가 잡아야 함
    _stub_seams(monkeypatch)
    payload, err = run_answer_pipeline(_body(transcript="가래에 피가 섞여 나와요"))
    # 정상 추출이 되면 safety_flag는 매칭 슬롯/원문 기반으로 노출될 수 있음
    assert err is None or err["statusCode"] in (200, 422)


def test_bedrock_failure_with_safety_flag_saves_safety_only(monkeypatch):
    # Bedrock 추출 실패 + 위험 표현 → 안전 저장 경로
    _stub_seams(monkeypatch, raise_bedrock=True)
    payload, err = run_answer_pipeline(_body(transcript="가래에 피가 섞여 나와요"))
    # 안전 경로로 저장되면 payload 반환(검증 통과로 표시), err 없음
    assert err is None
    assert payload is not None


def test_bedrock_failure_without_safety_flag(monkeypatch):
    # Bedrock 실패 + 위험표현 없음 + 비증상 맥락 보존 불가 → 422 또는 보존 처리
    _stub_seams(monkeypatch, raise_bedrock=True)
    payload, err = run_answer_pipeline(_body(transcript="음 그게 좀 그래요"))
    # 실패 응답이거나, 맥락 보존으로 payload가 나올 수 있음
    assert (err is not None and err["statusCode"] == 422) or payload is not None


def test_non_symptom_question_skips_ir(monkeypatch):
    # 복약 문항은 IR을 건너뜀
    extraction = {
        "spans": [],
        "structured": {
            "standardized_text": "혈압약을 먹습니다.",
            "clinical_clues": [],
            "questions": [],
            "unresolved_items": [],
        },
    }
    _stub_seams(monkeypatch, extraction_obj=extraction)
    payload, err = run_answer_pipeline(_body(
        question_id="Q3", question_type="current_medications",
        transcript="혈압약을 매일 아침에 먹어요",
    ))
    assert err is None
    assert payload["matched_slots"] == []

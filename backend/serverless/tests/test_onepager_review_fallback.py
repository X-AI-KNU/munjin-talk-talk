from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def install_review_stubs():
    for name in ["settings", "llm"]:
        sys.modules.pop(name, None)

    settings = types.ModuleType("settings")
    settings.REVIEWER_MODEL_ID = "apac.amazon.nova-pro-v1:0"
    settings.REVIEW_MAX_TOKENS = 900
    settings.REVIEW_RETRY_ATTEMPTS = 1
    sys.modules["settings"] = settings

    llm = types.ModuleType("llm")

    def fail_review(*_args, **_kwargs):
        raise RuntimeError("bedrock unavailable")

    llm.call_bedrock_json_with_meta = fail_review
    sys.modules["llm"] = llm


def install_onepager_stubs():
    for name in ["settings", "artifact_store", "llm", "onepager_review", "sessions", "privacy", "onepager"]:
        sys.modules.pop(name, None)

    settings = types.ModuleType("settings")
    settings.REVIEWER_MODEL_ID = "apac.amazon.nova-pro-v1:0"
    settings.REVIEW_MAX_TOKENS = 900
    settings.REVIEW_RETRY_ATTEMPTS = 1
    sys.modules["settings"] = settings

    artifact_store = types.ModuleType("artifact_store")
    artifact_store.ONEPAPER_FILE = "onepaper.redacted.json"
    artifact_store.artifact_meta = lambda session_id, created_at=None: {"session_id": session_id, "created_at": created_at}
    artifact_store.get_json = lambda *_args, **_kwargs: {}
    artifact_store.load_answers = lambda _session: {}
    artifact_store.put_json = lambda *_args, **_kwargs: None
    artifact_store.save_answers = lambda *_args, **_kwargs: None
    artifact_store.save_trace = lambda *_args, **_kwargs: None
    sys.modules["artifact_store"] = artifact_store

    onepager_review = types.ModuleType("onepager_review")
    onepager_review.apply_bedrock_onepager_review = lambda _session, onepager: onepager
    sys.modules["onepager_review"] = onepager_review

    sessions = types.ModuleType("sessions")
    sessions.create_session = lambda _body: {}
    sessions.get_session = lambda _session_id: {}
    sessions.update_session = lambda _session_id, _updates: {}
    sys.modules["sessions"] = sessions

    privacy = types.ModuleType("privacy")
    privacy.safety_summary = lambda flag: flag
    sys.modules["privacy"] = privacy


def test_review_fallback_keeps_doctor_checklist_non_empty():
    install_review_stubs()
    sys.modules.pop("onepager_review", None)
    from onepager_review import apply_bedrock_onepager_review  # noqa: E402

    onepager = {
        "symptom_slots": [
            {"name": "흉통", "source_quote": "가슴이 답답함", "status": "있음"},
        ],
        "clinical_clues": [
            {"summary": "어제부터 시작", "action_hint": "시작 시점과 악화 여부 확인"},
        ],
        "agenda": [
            {"summary": "약을 같이 먹어도 되는지 문의", "original_quote": "약들 같이 다 먹어도 되지?"},
        ],
        "safety_flags": [
            {"label": "흉통", "category": "chest_pain", "matched_pattern": "가슴이 답답함"},
        ],
        "review_items": [],
        "transfer_text": "",
    }

    reviewed = apply_bedrock_onepager_review({"visit_type": "initial", "patient": {}, "responses": {}}, onepager)

    assert reviewed["review_items"]
    assert reviewed["review_item_generation"]["method"] == "rule_based_fallback"
    assert any(item.startswith("[우선]") for item in reviewed["review_items"])
    assert any("흉통" in item for item in reviewed["review_items"])


def test_transfer_text_filter_rejects_patient_facing_prose():
    install_review_stubs()
    sys.modules.pop("onepager_review", None)
    from onepager_review import is_transfer_text_safe  # noqa: E402

    onepager = {
        "patient_summary": {"age_text": "80세", "sex": "남성"},
        "symptom_slots": [{"name": "천명음", "source_quote": "쌕쌕 나와", "normalized_text": "천명음"}],
        "clinical_clues": [],
        "agenda": [],
        "safety_flags": [],
    }

    narrative = "S: 80세 남성 초진. 환자는 현재 가슴이 답답하다고 언급했습니다 | O: 문진 기반 객관소견 없음"
    chart_like = "S) 80세 남성 초진 / CC: 천명음 / 확인: 증상 지속시간/중증도"

    assert is_transfer_text_safe(narrative, onepager) is False
    assert is_transfer_text_safe(chart_like, onepager) is True


def test_safety_flag_is_preserved_as_symptom_card_when_ir_misses_it():
    install_onepager_stubs()
    from onepager import ensure_safety_matched_slot  # noqa: E402

    slots = ensure_safety_matched_slot([], {
        "category": "chest_discomfort",
        "label": "가슴 답답",
        "matched_pattern": "가심이 답답",
    })

    assert slots[0]["slot_id"] == "chest_discomfort"
    assert slots[0]["name"] == "가슴 답답"
    assert slots[0]["alert"] is True


def test_build_onepager_restores_safety_symptom_from_saved_answer():
    install_onepager_stubs()
    from onepager import build_onepager  # noqa: E402

    onepager = build_onepager({
        "visit_type": "initial",
        "patient": {"age": 80, "gender": "남성", "name": "홍*동"},
        "responses": {
            "Q1": {
                "text": "가심이 답답허고 코물이 줄줄 나와",
                "matched_slots": [],
                "structured": {"clinical_clues": [], "questions": []},
                "spans": [],
            }
        },
    })

    assert any(slot["name"] == "가슴 답답" for slot in onepager["symptom_slots"])
    assert any(flag["category"] == "chest_discomfort" for flag in onepager["safety_flags"])


def test_rerun_onepager_review_rebuilds_from_saved_answers_before_review():
    install_onepager_stubs()
    import onepager  # noqa: E402

    session = {
        "session_id": "s1",
        "visit_type": "initial",
        "patient": {"name": "김민수", "age": 70, "gender": "남성", "department": "이비인후과"},
    }
    answers = {
        "Q1": {
            "text": "코물이 나와",
            "dialect_normalization": {"standardized_text": "콧물이 나옵니다."},
            "matched_slots": [
                {
                    "slot_id": "rhinorrhea",
                    "name": "콧물",
                    "source_quote": "코물이 나와",
                    "normalized_text": "콧물이 나옵니다.",
                    "status": "있음",
                }
            ],
            "structured": {"standardized_text": "콧물이 나옵니다.", "clinical_clues": [], "questions": []},
            "spans": [],
        },
        "Q4": {
            "text": "궁금한 건 없어요",
            "matched_slots": [],
            "structured": {"standardized_text": "궁금한 점은 없습니다.", "clinical_clues": [], "questions": []},
            "spans": [],
        },
    }
    stale_onepager = {
        "symptom_slots": [{"name": "오래된 증상", "source_quote": "오래된 표현"}],
        "review_items": ["오래된 확인 항목"],
        "transfer_text": "S) 오래된 초안",
    }
    captured = {}

    def fake_get_json(*_args, **_kwargs):
        return captured.get("saved", stale_onepager)

    def fake_review(_session, draft):
        captured["draft"] = draft
        reviewed = dict(draft)
        reviewed["review_items"] = ["콧물 지속 정도 확인"]
        return reviewed

    onepager.get_session = lambda _session_id: session
    onepager.load_answers = lambda _session: answers
    onepager.get_json = fake_get_json
    onepager.put_json = lambda _session, _key, payload: captured.update({"saved": payload})
    onepager.update_session = lambda _session_id, updates: {**session, **updates}
    onepager.apply_bedrock_onepager_review = fake_review

    payload, err = onepager.rerun_onepager_review("s1")

    assert err is None
    assert captured["draft"]["symptom_slots"][0]["name"] == "콧물"
    assert captured["draft"]["symptom_slots"][0]["source_quote"] == "코물이 나와"
    assert captured["draft"]["transfer_text"] != stale_onepager["transfer_text"]
    assert captured["saved"]["review_items"] == ["콧물 지속 정도 확인"]
    assert payload["session"]["onepager"]["review_items"] == ["콧물 지속 정도 확인"]


def test_hongsam_medication_question_is_supplement_agenda():
    from onepager_sections import normalize_agenda  # noqa: E402

    agenda = normalize_agenda({
        "structured": {
            "questions": [
                {
                    "category": "other",
                    "summary": "홍삼과 약 병용 가능 여부 문의",
                    "original_quote": "홍삼이랑 약 주는 거 같이 타먹어도 되나",
                }
            ]
        }
    })

    assert agenda[0]["category"] == "supplement_drug_interaction"
    assert agenda[0]["type_label"] == "영양제 병용"


def test_clinical_clue_priority_requires_safety_evidence():
    from onepager_sections import normalize_clinical_clue  # noqa: E402

    normal = normalize_clinical_clue({
        "category": "증상맥락",
        "label": "현재양상",
        "summary": "몸에 힘이 없는 상태가 현재 있습니다.",
        "source_quote": "몸에 힘이 잘 안들어가고",
        "priority": "우선",
        "related_symptoms": ["기운없음"],
    }, "Q3")

    safety = normalize_clinical_clue({
        "category": "증상맥락",
        "label": "현재양상",
        "summary": "숨이 너무 찬 상태가 현재 있습니다.",
        "source_quote": "숨이 너무 차요",
        "priority": "우선",
        "related_symptoms": ["호흡곤란"],
    }, "Q1")

    assert normal["priority"] == "일반"
    assert safety["priority"] == "우선"

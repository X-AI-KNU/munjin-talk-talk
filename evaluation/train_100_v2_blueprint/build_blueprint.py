from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend" / "serverless" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from dialect_config import load_dialect_entries  # noqa: E402
from dialect_rag import retrieve_dialect_context  # noqa: E402


OUT_DIR = Path(__file__).resolve().parent


PLAN = {
    "version": "train_100_v2_blueprint_2026-06-26",
    "total_rows": 100,
    "visit_question_split": {"initial_Q1": 50, "followup_Q3": 50},
    "language_split": {"standard": 50, "gangwon": 50},
    "cross_split": {
        "initial_Q1_standard": 25,
        "initial_Q1_gangwon": 25,
        "followup_Q3_standard": 25,
        "followup_Q3_gangwon": 25,
    },
    "symptom_group_distribution": {
        "upper_airway_common": 18,
        "cough_sputum_lower_airway": 20,
        "dyspnea_chest_urgent": 18,
        "systemic_course": 14,
        "ent_swallow_eye_voice": 10,
        "cardio_neuro_edema": 10,
        "gi_nonspecific_confounders": 10,
    },
    "status_pattern_distribution": {
        "active_current": 45,
        "recurrent_or_persistent": 25,
        "improved_or_resolved": 10,
        "denied_negative_context": 15,
        "mixed_context": 5,
    },
    "expression_policy_distribution": {
        "direct_common": 35,
        "lay_paraphrase": 45,
        "technical_hidden": 20,
    },
    "gangwon_source_layer_distribution": {
        "rag_pack_anchored": 10,
        "clinical_colloquial": 25,
        "light_dialect_style": 15,
    },
    "hard_rules": [
        "No rendered patient text in blueprint rows.",
        "Rendered data must target only initial Q1 and follow-up Q3.",
        "Do not include Q2 onset/duration as the main answer.",
        "Do not include Q4 doctor questions or medication/supplement questions.",
        "All rendered patient utterances must be casual spoken Korean, not formal -습니다 style.",
        "RAG-pack anchored dialect rows must retrieve the expected dialect hint before acceptance.",
    ],
}


CELL_COUNTS = {
    "upper_airway_common": (5, 5, 4, 4),
    "cough_sputum_lower_airway": (5, 5, 5, 5),
    "dyspnea_chest_urgent": (5, 4, 5, 4),
    "systemic_course": (3, 4, 3, 4),
    "ent_swallow_eye_voice": (2, 3, 2, 3),
    "cardio_neuro_edema": (3, 2, 3, 2),
    "gi_nonspecific_confounders": (2, 2, 3, 3),
}


SYMPTOM_SPECS = {
    "upper_airway_common": [
        (["목의 통증"], [], "목이 아프거나 칼칼한 느낌을 환자 말투로 풀어 설명"),
        (["코막힘"], [], "코가 막혀 숨쉬기 답답한 느낌"),
        (["콧물"], [], "콧물이 흐르거나 훌쩍거리게 되는 불편"),
        (["재채기"], [], "재채기가 반복되는 불편"),
        (["감기 증상"], ["열"], "감기 기운은 있지만 열은 없다는 구분"),
        (["열"], ["기침"], "열은 있는데 기침은 없다는 부정 포함"),
        (["목의 통증", "코막힘"], [], "목 불편과 코막힘 동반"),
        (["콧물", "재채기"], [], "콧물과 재채기 동반"),
    ],
    "cough_sputum_lower_airway": [
        (["기침"], [], "기침이 현재 계속 나는 불편"),
        (["가래"], [], "목이나 가슴에 가래가 끼는 느낌"),
        (["기침", "가래"], [], "기침과 가래 동반"),
        (["화농성 객담"], [], "누렇고 진한 가래를 전문용어 없이 설명"),
        (["검은색 가래"], [], "가래 색이 검게 보이는 걱정"),
        (["거품이 섞인 가래"], ["객혈"], "거품 낀 가래는 있지만 피는 없다는 구분"),
        (["천명음"], [], "숨쉴 때 쌕쌕거리는 소리를 전문용어 없이 설명"),
        (["기침"], ["가래"], "기침은 있지만 가래는 없다는 부정 포함"),
    ],
    "dyspnea_chest_urgent": [
        (["호흡곤란"], [], "숨이 차거나 말하기 힘든 느낌"),
        (["가슴 답답"], [], "가슴이 꽉 막힌 듯 답답한 느낌"),
        (["흉통"], ["호흡곤란"], "가슴 통증은 있으나 숨참은 없다는 구분"),
        (["객혈"], [], "기침할 때 피가 섞여 나온 표현"),
        (["호흡곤란", "가슴 답답"], [], "숨참과 가슴 답답함 동반"),
        (["가슴 답답"], ["흉통"], "답답하지만 아픈 것은 아니라고 구분"),
        (["청색증"], [], "입술이 파래 보이는 우선 확인 표현"),
        (["호흡곤란"], ["객혈"], "숨참은 있지만 피 섞인 가래는 없다는 구분"),
    ],
    "systemic_course": [
        (["열"], [], "몸에 열감이 있거나 열이 나는 표현"),
        (["오한"], [], "춥고 떨리는 느낌"),
        (["근육통"], [], "몸살처럼 온몸이 쑤시는 느낌"),
        (["피로감"], [], "계속 피곤하고 축 처지는 느낌"),
        (["기운없음"], [], "몸에 힘이 빠지는 느낌"),
        (["열"], ["오한"], "열은 있는데 춥고 떠는 건 없다는 구분"),
        (["근육통", "피로감"], [], "몸살과 피로 동반"),
    ],
    "ent_swallow_eye_voice": [
        (["목소리 변화"], [], "목소리가 쉬거나 잘 나오지 않는 상태"),
        (["삼키기 곤란"], [], "음식이나 물을 삼키기 어려운 느낌"),
        (["사래걸림"], ["삼키기 곤란"], "사레는 들리지만 음식이 안 넘어가는 건 아님"),
        (["눈의 충혈"], [], "눈이 빨갛게 충혈되는 불편"),
        (["눈곱"], [], "눈곱이나 눈 분비물이 끼는 불편"),
    ],
    "cardio_neuro_edema": [
        (["어지러움"], [], "머리가 핑 돌거나 어지러운 느낌"),
        (["가슴 두근거림"], [], "가슴이 두근거리거나 맥이 불규칙한 느낌"),
        (["하지부종"], [], "다리나 발이 부어서 신발이 끼는 느낌"),
        (["근력 약화"], [], "팔다리에 힘이 잘 안 들어가는 느낌"),
        (["두통"], ["어지러움"], "머리는 아프지만 어지럽지는 않다는 구분"),
    ],
    "gi_nonspecific_confounders": [
        (["구토"], ["설사"], "속이 울렁이고 토했지만 설사는 없다는 구분"),
        (["설사"], [], "묽은 변이 반복되는 표현"),
        (["복부 통증"], [], "배가 꼬이거나 아픈 느낌"),
        (["복부 팽만"], [], "배가 빵빵하고 더부룩한 느낌"),
        (["식욕부진"], [], "입맛이 없고 잘 못 먹는 느낌"),
    ],
}


RAG_ANCHORS = {
    "upper_airway_common": [
        {"dialect": "코빼기", "standard": "코", "sample_query": "코빼기가 막혀", "usage": "코 증상에만 사용"},
        {"dialect": "아푸나?", "standard": "아프니?", "sample_query": "목이 아푸나 싶어", "usage": "아프다 계열 표현에만 사용"},
    ],
    "dyspnea_chest_urgent": [
        {
            "dialect": "(가슴이) 제리제리하다",
            "standard": "저리다",
            "sample_query": "가슴이 제리제리해",
            "usage": "가슴 저림 또는 이상감 표현에만 사용",
        },
    ],
    "systemic_course": [
        {"dialect": "몸땡이", "standard": "몸통", "sample_query": "몸땡이가 쑤셔", "usage": "몸살/몸통 불편 표현에만 사용"},
        {"dialect": "자우름", "standard": "졸음", "sample_query": "자우름이 와", "usage": "피로/졸림 동반 표현에만 사용"},
    ],
    "ent_swallow_eye_voice": [
        {"dialect": "잠구키다[장구키다]", "standard": "잠기다", "sample_query": "목소리가 장구키다", "usage": "목소리 잠김 표현에만 사용"},
    ],
    "cardio_neuro_edema": [
        {"dialect": "머리깽이", "standard": "머리", "sample_query": "머리깽이가 핑 돌아", "usage": "두통/어지러움 표현에만 사용"},
        {"dialect": "다리깽이", "standard": "다리", "sample_query": "다리깽이가 부었어", "usage": "하지부종/다리 불편 표현에만 사용"},
    ],
    "gi_nonspecific_confounders": [
        {"dialect": "창지", "standard": "창자", "sample_query": "창지가 꼬이는 느낌", "usage": "복부/장 불편 표현에만 사용"},
    ],
    "cough_sputum_lower_airway": [
        {"dialect": "줄구다", "standard": "줄이다", "sample_query": "기침이 좀 줄구다", "usage": "증상이 줄었다는 Q3 호전 표현에만 사용"},
    ],
}

RAG_ANCHOR_TARGETS = {
    "upper_airway_common": 2,
    "cough_sputum_lower_airway": 1,
    "dyspnea_chest_urgent": 2,
    "systemic_course": 2,
    "ent_swallow_eye_voice": 1,
    "cardio_neuro_edema": 1,
    "gi_nonspecific_confounders": 1,
}

TECHNICAL_SYMPTOMS = {
    "호흡곤란",
    "천명음",
    "객혈",
    "화농성 객담",
    "검은색 가래",
    "거품이 섞인 가래",
    "흉통",
    "가슴 답답",
    "청색증",
    "삼키기 곤란",
    "사래걸림",
    "하지부종",
    "근력 약화",
    "가슴 두근거림",
    "복부 팽만",
}

DIRECT_SYMPTOMS = {"기침", "콧물", "코막힘", "열", "가래", "재채기", "목의 통증", "어지러움", "두통", "설사", "구토"}


def choose_expression(cases: list[dict], gold: list[str]) -> str:
    counts = Counter(case["expression_policy"] for case in cases)
    if any(symptom in TECHNICAL_SYMPTOMS for symptom in gold) and counts["technical_hidden"] < 20:
        return "technical_hidden"
    if any(symptom in DIRECT_SYMPTOMS for symptom in gold) and counts["direct_common"] < 35:
        return "direct_common"
    for key, target in PLAN["expression_policy_distribution"].items():
        if counts[key] < target:
            return key
    return "lay_paraphrase"


def build_cases() -> list[dict]:
    cases: list[dict] = []
    case_no = 1
    status_q1 = ["active_current"] * 35 + ["denied_negative_context"] * 10 + ["mixed_context"] * 5
    status_q3 = ["recurrent_or_persistent"] * 25 + ["improved_or_resolved"] * 10 + ["active_current"] * 10 + ["denied_negative_context"] * 5
    q1_status_i = 0
    q3_status_i = 0
    clinical_budget = 25
    light_budget = 15
    anchor_used_by_group: Counter[str] = Counter()
    anchor_idx_by_group: defaultdict[str, int] = defaultdict(int)

    def choose_status(visit_type: str) -> str:
        nonlocal q1_status_i, q3_status_i
        if visit_type == "initial":
            value = status_q1[q1_status_i]
            q1_status_i += 1
            return value
        value = status_q3[q3_status_i]
        q3_status_i += 1
        return value

    def choose_layer(group: str) -> tuple[str, dict | None]:
        nonlocal clinical_budget, light_budget
        if anchor_used_by_group[group] < RAG_ANCHOR_TARGETS.get(group, 0):
            anchors = RAG_ANCHORS[group]
            anchor = anchors[anchor_idx_by_group[group] % len(anchors)]
            anchor_idx_by_group[group] += 1
            anchor_used_by_group[group] += 1
            return "rag_pack_anchored", anchor
        if clinical_budget > 0:
            clinical_budget -= 1
            return "clinical_colloquial", None
        light_budget -= 1
        return "light_dialect_style", None

    def make_case(group: str, visit_type: str, language_style: str, local_idx: int) -> dict:
        nonlocal case_no
        gold, negative, base_intent = SYMPTOM_SPECS[group][local_idx % len(SYMPTOM_SPECS[group])]
        question_id = "Q1" if visit_type == "initial" else "Q3"
        question_type = "chief_complaint" if visit_type == "initial" else "progress"
        layer = "none"
        anchor = None
        if language_style == "gangwon":
            layer, anchor = choose_layer(group)
        status = choose_status(visit_type)
        expression = choose_expression(cases, gold)
        difficulty = "hard" if expression == "technical_hidden" or status in {"mixed_context", "denied_negative_context"} else ("medium" if status != "active_current" else "easy")
        renderer_intent = base_intent
        if visit_type == "followup":
            renderer_intent = "지난 방문 이후 경과로 말하게 하되 Q2식 시작시점이 주 내용이 되지 않게 하기: " + renderer_intent
        if status == "improved_or_resolved":
            renderer_intent += "; 좋아졌거나 사라진 맥락으로 만들어 현재 증상 카드가 되지 않게 함"
        elif status == "denied_negative_context":
            renderer_intent += "; negative_symptoms는 명시적으로 없다고 말하게 함"
        elif status == "mixed_context":
            renderer_intent += "; 한 증상은 현재 있고 다른 증상은 없거나 좋아진 혼합 문맥"
        case = {
            "case_id": f"train_v2_{case_no:03d}",
            "visit_type": visit_type,
            "question_id": question_id,
            "question_type": question_type,
            "language_style": language_style,
            "dialect_source_layer": layer,
            "symptom_group": group,
            "gold_symptoms": gold,
            "negative_symptoms": negative,
            "status_pattern": status,
            "expression_policy": expression,
            "difficulty": difficulty,
            "renderer_intent": renderer_intent,
            "forbidden_content": [
                "Q2 onset/duration as main answer",
                "Q4 doctor question",
                "medication/supplement question as main answer",
                "formal -습니다 style",
            ],
            "expected_output_notes": "Rendered text must allow symptom extraction from Q1/Q3 only and must preserve negative/resolved context.",
        }
        if anchor:
            case["dialect_anchor"] = anchor
            case["dialect_anchor_acceptance"] = "Rendered text must include the dialect anchor naturally and retrieve it through retrieve_dialect_context()."
        case_no += 1
        return case

    for group, (q1_std, q1_gang, q3_std, q3_gang) in CELL_COUNTS.items():
        local_idx = 0
        for _ in range(q1_std):
            cases.append(make_case(group, "initial", "standard", local_idx))
            local_idx += 1
        for _ in range(q1_gang):
            cases.append(make_case(group, "initial", "gangwon", local_idx))
            local_idx += 1
        for _ in range(q3_std):
            cases.append(make_case(group, "followup", "standard", local_idx))
            local_idx += 1
        for _ in range(q3_gang):
            cases.append(make_case(group, "followup", "gangwon", local_idx))
            local_idx += 1
    return cases


ANCHOR_ASSIGNMENTS = {
    "train_v2_007": {
        "dialect": "아푸나?",
        "standard": "아프니?",
        "sample_query": "목이 아푸나 싶어",
        "usage": "목 통증처럼 아프다는 표현에만 사용",
    },
    "train_v2_010": {
        "dialect": "코빼기",
        "standard": "코",
        "sample_query": "코빼기가 막혀",
        "usage": "코막힘이나 콧물처럼 코 증상에만 사용",
    },
    "train_v2_015": {
        "dialect": "아푸나?",
        "standard": "아프니?",
        "sample_query": "목이 아푸나 싶어",
        "usage": "재진 Q3에서 목 통증 경과 표현에만 사용",
    },
    "train_v2_044": {
        "dialect": "(가슴이) 제리제리하다",
        "standard": "저리다",
        "sample_query": "가슴이 제리제리해",
        "usage": "가슴 답답함과 함께 말하는 가슴 이상감 표현에만 사용",
    },
    "train_v2_063": {
        "dialect": "몸땡이",
        "standard": "몸통",
        "sample_query": "몸땡이가 쑤셔",
        "usage": "몸살이나 근육통처럼 몸이 쑤시는 표현에만 사용",
    },
    "train_v2_067": {
        "dialect": "자우름",
        "standard": "졸음",
        "sample_query": "자우름이 와",
        "usage": "피로감이나 처지는 느낌을 말하는 경과 표현에만 사용",
    },
    "train_v2_085": {
        "dialect": "머리깽이",
        "standard": "머리",
        "sample_query": "머리깽이가 핑 돌아",
        "usage": "두통이나 어지러움처럼 머리 불편 표현에만 사용",
    },
    "train_v2_090": {
        "dialect": "머리깽이",
        "standard": "머리",
        "sample_query": "머리깽이가 핑 돌아",
        "usage": "재진 Q3에서 두통 경과 표현에만 사용",
    },
    "train_v2_093": {
        "dialect": "창지",
        "standard": "창자",
        "sample_query": "창지가 꼬이는 느낌",
        "usage": "복부 통증처럼 배나 장이 불편한 표현에만 사용",
    },
    "train_v2_098": {
        "dialect": "창지",
        "standard": "창자",
        "sample_query": "창지가 꼬이는 느낌",
        "usage": "재진 Q3에서 복부 통증 경과 표현에만 사용",
    },
}


LIGHT_DIALECT_CASE_IDS = {
    "train_v2_008",
    "train_v2_009",
    "train_v2_016",
    "train_v2_017",
    "train_v2_026",
    "train_v2_027",
    "train_v2_034",
    "train_v2_035",
    "train_v2_046",
    "train_v2_047",
    "train_v2_055",
    "train_v2_068",
    "train_v2_078",
    "train_v2_089",
    "train_v2_100",
}


def rebalance_dialect_layers(cases: list[dict]) -> None:
    """Keep the fixed 10/25/15 dialect split while anchoring only compatible rows."""
    by_id = {case["case_id"]: case for case in cases}
    missing = sorted(set(ANCHOR_ASSIGNMENTS) - set(by_id))
    if missing:
        raise RuntimeError(f"anchor assignments reference missing cases: {missing}")

    for case in cases:
        case.pop("dialect_anchor", None)
        case.pop("dialect_anchor_acceptance", None)
        if case["language_style"] == "standard":
            case["dialect_source_layer"] = "none"
            continue
        case["dialect_source_layer"] = "clinical_colloquial"

    for case_id, anchor in ANCHOR_ASSIGNMENTS.items():
        case = by_id[case_id]
        if case["language_style"] != "gangwon":
            raise RuntimeError(f"{case_id} is not a Gangwon row")
        case["dialect_source_layer"] = "rag_pack_anchored"
        case["dialect_anchor"] = anchor
        case["dialect_anchor_acceptance"] = (
            "Rendered text must include the dialect anchor naturally and retrieve it through retrieve_dialect_context()."
        )

    for case_id in LIGHT_DIALECT_CASE_IDS:
        case = by_id[case_id]
        if case["language_style"] != "gangwon":
            raise RuntimeError(f"{case_id} is not a Gangwon row")
        if case["dialect_source_layer"] == "rag_pack_anchored":
            raise RuntimeError(f"{case_id} cannot be both light_dialect_style and rag_pack_anchored")
        case["dialect_source_layer"] = "light_dialect_style"


def validate(cases: list[dict]) -> dict:
    errors: list[str] = []
    if len(cases) != 100:
        errors.append(f"expected 100 rows, got {len(cases)}")
    ids = [case["case_id"] for case in cases]
    if len(ids) != len(set(ids)):
        errors.append("duplicate case_id")

    counts = {
        "visit_type": Counter(case["visit_type"] for case in cases),
        "question_id": Counter(case["question_id"] for case in cases),
        "language_style": Counter(case["language_style"] for case in cases),
        "cross": Counter(f"{case['visit_type']}_{case['question_id']}_{case['language_style']}" for case in cases),
        "symptom_group": Counter(case["symptom_group"] for case in cases),
        "status_pattern": Counter(case["status_pattern"] for case in cases),
        "expression_policy": Counter(case["expression_policy"] for case in cases),
        "dialect_source_layer": Counter(case["dialect_source_layer"] for case in cases),
    }
    expected = {
        "visit_type": {"initial": 50, "followup": 50},
        "question_id": {"Q1": 50, "Q3": 50},
        "language_style": PLAN["language_split"],
        "cross": PLAN["cross_split"],
        "symptom_group": PLAN["symptom_group_distribution"],
        "status_pattern": PLAN["status_pattern_distribution"],
        "expression_policy": PLAN["expression_policy_distribution"],
        "dialect_source_layer": {"none": 50, **PLAN["gangwon_source_layer_distribution"]},
    }
    for name, expected_counts in expected.items():
        actual = dict(counts[name])
        if actual != expected_counts:
            errors.append(f"{name} mismatch: got {actual}, expected {expected_counts}")

    load_dialect_entries.cache_clear()
    for case in cases:
        if case["language_style"] == "standard" and case["dialect_source_layer"] != "none":
            errors.append(f"{case['case_id']} standard row has dialect layer")
        if case["language_style"] == "gangwon" and case["dialect_source_layer"] == "none":
            errors.append(f"{case['case_id']} gangwon row missing dialect layer")
        if case["question_id"] == "Q1" and case["question_type"] != "chief_complaint":
            errors.append(f"{case['case_id']} Q1 type mismatch")
        if case["question_id"] == "Q3" and case["question_type"] != "progress":
            errors.append(f"{case['case_id']} Q3 type mismatch")
        if case["dialect_source_layer"] == "rag_pack_anchored":
            anchor = case.get("dialect_anchor")
            if not anchor:
                errors.append(f"{case['case_id']} rag_pack_anchored without dialect_anchor")
                continue
            hints = retrieve_dialect_context(anchor["sample_query"], top_k=5).get("hints") or []
            if not any(item.get("standard") == anchor["standard"] for item in hints):
                errors.append(f"{case['case_id']} anchor query did not retrieve expected standard: {anchor}")

    return {
        "passed": not errors,
        "errors": errors,
        "counts": {key: dict(value) for key, value in counts.items()},
        "rag_pack_anchor_cases": [
            {"case_id": case["case_id"], "group": case["symptom_group"], "anchor": case.get("dialect_anchor")}
            for case in cases
            if case["dialect_source_layer"] == "rag_pack_anchored"
        ],
    }


def write_files(cases: list[dict], report: dict) -> None:
    readme = """# Train 100 v2 Blueprint

This folder contains the accepted row-level blueprint for `train_100_v2`.

It is not rendered patient text. It defines what the later LLM renderer must create.

## Files

- `distribution_plan.json`: fixed counts and hard rules.
- `case_blueprint.schema.json`: row schema.
- `case_blueprint.jsonl`: 100 planned rows.
- `quality_gate_report.json`: generated validation summary.

## Scope

Only these question targets are allowed:

- Initial visit Q1 chief complaint.
- Follow-up visit Q3 recurrence/course.

Q2 onset/duration and Q4 patient questions are intentionally excluded from this dataset.

## Rendering Rule

The renderer must create casual spoken Korean patient utterances from the blueprint.
It must not mechanically assemble templates or copy prior `train_100` text.
"""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": [
            "case_id",
            "visit_type",
            "question_id",
            "question_type",
            "language_style",
            "dialect_source_layer",
            "symptom_group",
            "gold_symptoms",
            "negative_symptoms",
            "status_pattern",
            "expression_policy",
            "difficulty",
            "renderer_intent",
            "forbidden_content",
        ],
        "properties": {
            "case_id": {"type": "string", "pattern": "^train_v2_[0-9]{3}$"},
            "visit_type": {"enum": ["initial", "followup"]},
            "question_id": {"enum": ["Q1", "Q3"]},
            "question_type": {"enum": ["chief_complaint", "progress"]},
            "language_style": {"enum": ["standard", "gangwon"]},
            "dialect_source_layer": {"enum": ["none", "rag_pack_anchored", "clinical_colloquial", "light_dialect_style"]},
            "symptom_group": {"type": "string"},
            "gold_symptoms": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "negative_symptoms": {"type": "array", "items": {"type": "string"}},
            "status_pattern": {"enum": ["active_current", "recurrent_or_persistent", "improved_or_resolved", "denied_negative_context", "mixed_context"]},
            "expression_policy": {"enum": ["direct_common", "lay_paraphrase", "technical_hidden"]},
            "difficulty": {"enum": ["easy", "medium", "hard"]},
            "renderer_intent": {"type": "string"},
            "forbidden_content": {"type": "array", "items": {"type": "string"}},
            "dialect_anchor": {"type": "object"},
        },
        "additionalProperties": True,
    }
    (OUT_DIR / "README.md").write_text(readme, encoding="utf-8")
    (OUT_DIR / "distribution_plan.json").write_text(json.dumps(PLAN, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / "case_blueprint.schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (OUT_DIR / "case_blueprint.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False, separators=(",", ":")) + "\n")
    (OUT_DIR / "quality_gate_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    cases = build_cases()
    rebalance_dialect_layers(cases)
    report = validate(cases)
    write_files(cases, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

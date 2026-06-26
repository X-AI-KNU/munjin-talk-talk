"""Build runtime artifacts from the accepted train_100_v2 dataset.

This script is intentionally deterministic. It reads only train_100_v2 and
writes the domain pack, alias bridges, few-shot files, and provenance report
used by the backend.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "evaluation" / "train_100_v2"
TRAIN_PATH = OUT_DIR / "train_100_v2.jsonl"
DATA_DIR = ROOT / "backend" / "serverless" / "src" / "data"
DOMAIN_PACK_PATH = DATA_DIR / "domain_packs" / "respiratory.json"
FEWSHOT_DIR = DATA_DIR / "fewshots" / "respiratory"
PROVENANCE_PATH = OUT_DIR / "artifact_provenance.json"
REPORT_PATH = OUT_DIR / "artifact_build_report.json"

VERSION = "respiratory_train_100_v2_2026-06-26"


SLOT_IDS = {
    "목의 통증": "throat_irritation",
    "코막힘": "nasal_obstruction",
    "콧물": "rhinorrhea",
    "재채기": "sneezing",
    "감기 증상": "cold_symptoms",
    "열": "fever",
    "기침": "cough",
    "가래": "sputum",
    "화농성 객담": "purulent_sputum",
    "검은색 가래": "black_sputum",
    "거품이 섞인 가래": "frothy_sputum",
    "천명음": "wheezing",
    "호흡곤란": "dyspnea",
    "가슴 답답": "chest_discomfort",
    "흉통": "chest_pain",
    "객혈": "hemoptysis",
    "청색증": "cyanosis",
    "오한": "chills",
    "근육통": "myalgia",
    "피로감": "fatigue",
    "기운없음": "low_energy",
    "목소리 변화": "voice_change",
    "삼키기 곤란": "dysphagia",
    "사래걸림": "choking",
    "눈의 충혈": "eye_redness",
    "눈곱": "eye_discharge",
    "어지러움": "dizziness",
    "가슴 두근거림": "palpitation",
    "하지부종": "leg_edema",
    "근력 약화": "muscle_weakness",
    "두통": "headache",
    "구토": "vomiting",
    "설사": "diarrhea",
    "복부 통증": "abdominal_pain",
    "복부 팽만": "abdominal_bloating",
    "식욕부진": "anorexia",
}


KEYWORD_CANDIDATES = {
    "목의 통증": ["목", "아프", "아푸", "칼칼"],
    "코막힘": ["코", "막혀", "막히", "답답"],
    "콧물": ["콧물", "코물이"],
    "재채기": ["재채기"],
    "감기 증상": ["감기"],
    "열": ["열"],
    "기침": ["기침"],
    "가래": ["가래"],
    "화농성 객담": ["누렇", "노랗", "짙은 가래"],
    "검은색 가래": ["검은 가래", "까만 가래"],
    "거품이 섞인 가래": ["거품", "거품 섞"],
    "천명음": ["쌕쌕", "휘파람"],
    "호흡곤란": ["숨", "숨쉬기", "숨 쉬기", "숨차"],
    "가슴 답답": ["가슴", "답답", "막혀"],
    "흉통": ["가슴", "아프", "통증"],
    "객혈": ["피", "피가 섞"],
    "청색증": ["입술", "파래"],
    "오한": ["춥고", "떨"],
    "근육통": ["쑤시", "몸살", "근육"],
    "피로감": ["피곤", "축 처지", "자우름"],
    "기운없음": ["기운", "힘이 없어"],
    "목소리 변화": ["목소리", "쉬"],
    "삼키기 곤란": ["삼키", "넘기"],
    "사래걸림": ["사래"],
    "눈의 충혈": ["눈", "빨갛", "충혈"],
    "눈곱": ["눈곱"],
    "어지러움": ["어지럽", "핑 돌"],
    "가슴 두근거림": ["두근", "맥이 불규칙"],
    "하지부종": ["다리", "발", "붓"],
    "근력 약화": ["팔다리", "힘이 잘 안"],
    "두통": ["머리", "머리깽이", "아프"],
    "구토": ["구토", "토했", "울렁"],
    "설사": ["설사", "묽은 변"],
    "복부 통증": ["배", "복통", "창지"],
    "복부 팽만": ["빵빵", "더부룩"],
    "식욕부진": ["입맛", "잘 못 먹"],
}


PATTERN_CANDIDATES = {
    "목의 통증": [r"목.{0,8}(아프|아푸|칼칼|따갑|쓰리)", r"목구멍.{0,8}(아프|칼칼|따갑)"],
    "코막힘": [r"코.{0,8}(막혀|막히|답답)", r"코도.{0,8}막"],
    "콧물": [r"콧물", r"코.{0,6}물.{0,4}(나|흐르|줄줄)"],
    "재채기": [r"재채기"],
    "감기 증상": [r"감기.{0,8}(같|걸린)"],
    "열": [r"열"],
    "기침": [r"기침"],
    "가래": [r"가래"],
    "화농성 객담": [r"(누렇|노랗|짙은).{0,8}가래", r"가래.{0,8}(누렇|노랗|짙)"],
    "검은색 가래": [r"(검은|까만).{0,8}가래", r"가래.{0,8}(검은|까만)"],
    "거품이 섞인 가래": [r"(거품|거품 섞).{0,8}가래", r"가래.{0,8}거품"],
    "천명음": [r"(쌕쌕|휘파람).{0,12}(소리|숨|나)"],
    "호흡곤란": [r"숨.{0,10}(힘들|차|가쁘)", r"숨\s*쉬기.{0,10}힘", r"숨쉬기.{0,10}힘"],
    "가슴 답답": [r"가슴.{0,10}(답답|막혀|막히|조이)"],
    "흉통": [r"가슴.{0,10}(아프|통증|찌르|쑤시)"],
    "객혈": [r"기침.{0,12}피", r"피.{0,8}(섞|가래|나오)"],
    "청색증": [r"입술.{0,8}(파래|파랗|푸르)"],
    "오한": [r"(춥고|추워).{0,8}(떨|떨리)", r"오한"],
    "근육통": [r"몸.{0,8}쑤시", r"근육.{0,8}아프", r"몸살"],
    "피로감": [r"피곤", r"축.{0,4}처지", r"자우름"],
    "기운없음": [r"기운.{0,6}없", r"힘이.{0,6}없"],
    "목소리 변화": [r"목소리.{0,8}(쉬|안 나오|변)", r"쉬인"],
    "삼키기 곤란": [r"삼키.{0,8}힘", r"(음식|물|알약).{0,12}(안 넘어|넘기 힘)"],
    "사래걸림": [r"사래.{0,8}(걸|들)"],
    "눈의 충혈": [r"눈.{0,8}(빨갛|충혈)"],
    "눈곱": [r"눈곱"],
    "어지러움": [r"어지럽", r"핑.{0,4}돌"],
    "가슴 두근거림": [r"두근", r"맥이.{0,8}불규칙", r"심장.{0,8}뛰"],
    "하지부종": [r"(다리|발).{0,8}붓", r"신발.{0,8}끼"],
    "근력 약화": [r"팔다리.{0,12}힘.{0,8}안", r"힘이.{0,8}안 들어"],
    "두통": [r"머리.{0,8}아프", r"머리깽이", r"두통"],
    "구토": [r"토했", r"구토", r"울렁.{0,8}토"],
    "설사": [r"설사", r"묽은 변", r"물변"],
    "복부 통증": [r"배.{0,8}아프", r"복통", r"창지.{0,8}꼬"],
    "복부 팽만": [r"배.{0,8}빵빵", r"더부룩"],
    "식욕부진": [r"입맛.{0,8}없", r"잘 못 먹"],
}


ALERT_SYMPTOMS = {"호흡곤란", "가슴 답답", "흉통", "객혈", "청색증"}


def read_rows() -> list[dict[str, Any]]:
    rows = []
    for line in TRAIN_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def unique(values: list[str]) -> list[str]:
    out = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def source_rows_by_symptom(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_symptom: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for symptom in row.get("gold_symptoms") or []:
            by_symptom[str(symptom)].append(row)
    return by_symptom


def pattern_sources(pattern: str, rows: list[dict[str, Any]], symptom: str) -> list[dict[str, str]]:
    compiled = re.compile(pattern)
    sources = []
    for row in rows:
        if symptom not in (row.get("gold_symptoms") or []):
            continue
        utterance = row.get("utterance") or ""
        match = compiled.search(utterance)
        if match:
            sources.append({"case_id": row["case_id"], "source_quote": match.group(0)})
    return sources


def keyword_sources(keyword: str, rows: list[dict[str, Any]], symptom: str) -> list[str]:
    sources = []
    for row in rows:
        if symptom in (row.get("gold_symptoms") or []) and keyword in (row.get("utterance") or ""):
            sources.append(row["case_id"])
    return sources


def build_symptom_rules(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_symptom = source_rows_by_symptom(rows)
    missing = sorted(set(by_symptom) - set(SLOT_IDS))
    if missing:
        raise RuntimeError(f"Missing slot id for symptoms: {missing}")

    rules = []
    provenance = {}
    for symptom in sorted(by_symptom, key=lambda item: SLOT_IDS[item]):
        case_rows = by_symptom[symptom]
        keywords = [symptom]
        for keyword in KEYWORD_CANDIDATES.get(symptom, []):
            if keyword_sources(keyword, rows, symptom):
                keywords.append(keyword)
        rules.append(
            {
                "name": symptom,
                "slot_id": SLOT_IDS[symptom],
                "keywords": unique(keywords),
                "alert": symptom in ALERT_SYMPTOMS,
            }
        )
        provenance[f"symptom_rule:{symptom}"] = {
            "artifact_type": "domain_pack.symptom_rule",
            "canonical_symptom": symptom,
            "slot_id": SLOT_IDS[symptom],
            "source_case_ids": [row["case_id"] for row in case_rows],
            "source_quotes": [row["utterance"] for row in case_rows[:6]],
            "acceptance_reason": "Gold symptom appears in accepted train_100_v2 rows.",
        }
    return rules, provenance


def build_aliases(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[str]], dict[str, Any]]:
    by_symptom = source_rows_by_symptom(rows)
    aliases = []
    quote_patterns: dict[str, list[str]] = defaultdict(list)
    provenance = {}

    for symptom in sorted(by_symptom, key=lambda item: SLOT_IDS[item]):
        canonical_entry = {
            "pattern": re.escape(symptom),
            "canonical_name": symptom,
            "source_case_ids": [row["case_id"] for row in by_symptom[symptom]],
            "source": "train_100_v2_gold_label",
        }
        aliases.append(canonical_entry)
        quote_patterns[SLOT_IDS[symptom]].append(re.escape(symptom))
        provenance[f"alias:{symptom}:canonical"] = {
            "artifact_type": "domain_pack.ir_text_alias",
            "canonical_symptom": symptom,
            "pattern": canonical_entry["pattern"],
            "source_case_ids": canonical_entry["source_case_ids"],
            "acceptance_reason": "Canonical label is present as a train_100_v2 gold symptom.",
        }

        for pattern in PATTERN_CANDIDATES.get(symptom, []):
            re.compile(pattern)
            sources = pattern_sources(pattern, rows, symptom)
            if not sources:
                continue
            entry = {
                "pattern": pattern,
                "canonical_name": symptom,
                "source_case_ids": [item["case_id"] for item in sources],
                "source": "train_100_v2_positive_utterance",
            }
            aliases.append(entry)
            quote_patterns[SLOT_IDS[symptom]].append(pattern)
            provenance[f"alias:{symptom}:{pattern}"] = {
                "artifact_type": "domain_pack.ir_text_alias",
                "canonical_symptom": symptom,
                "pattern": pattern,
                "source_case_ids": [item["case_id"] for item in sources],
                "source_quotes": [item["source_quote"] for item in sources[:8]],
                "acceptance_reason": "Regex matched at least one accepted train_100_v2 row where this symptom is gold.",
            }

    return aliases, {key: unique(value) for key, value in quote_patterns.items()}, provenance


def selected_row(rows: list[dict[str, Any]], case_id: str) -> dict[str, Any]:
    for row in rows:
        if row["case_id"] == case_id:
            return row
    raise RuntimeError(f"Missing few-shot source case: {case_id}")


def question_text(row: dict[str, Any]) -> str:
    if row.get("question_id") == "Q1":
        return "어디가 불편하셔서 오셨어요?"
    return "이전과 비교해서 증상이 어떻게 변했나요?"


def standardized_text(row: dict[str, Any]) -> str:
    replacements = {
        "목이 아푸나 싶고 코도 계속 막혀서 숨 쉬기가 불편해": "목이 아픈 것 같고 코도 계속 막혀서 숨 쉬기가 불편해",
        "머리깽이 좀 아프긴 한데 어지럽지는 않아": "머리가 좀 아프긴 한데 어지럽지는 않아",
        "자우름은 조금 나아졌지만, 아직도 가끔 축 처지는 느낌이 있어": "피로감은 조금 나아졌지만, 아직도 가끔 축 처지는 느낌이 있어",
        "창지가 꼬이는 느낌이랑 복통이 좀 있어": "배가 꼬이는 느낌이랑 복통이 좀 있어",
    }
    return replacements.get(row["utterance"], row["utterance"])


def expected_spans(row: dict[str, Any]) -> list[dict[str, Any]]:
    spans = []
    utterance = row["utterance"]
    for symptom in row.get("gold_symptoms") or []:
        spans.append(
            {
                "source_quote": utterance,
                "type": "progress_improved" if row.get("status_pattern") == "improved_or_resolved" else "symptom",
                "slot_ref": SLOT_IDS[symptom],
                "name": symptom,
                "normalized_text": standardized_text(row),
                "status": "있음",
                "alert": symptom in ALERT_SYMPTOMS,
                "explain": "환자 원문에서 해당 증상이 근거로 확인됨.",
            }
        )
    for symptom in row.get("explicitly_negated_symptoms") or row.get("negative_symptoms") or []:
        if symptom in SLOT_IDS:
            spans.append(
                {
                    "source_quote": utterance,
                    "type": "symptom_absent",
                    "slot_ref": SLOT_IDS[symptom],
                    "name": symptom,
                    "normalized_text": standardized_text(row),
                    "status": "없음",
                    "alert": False,
                    "explain": "환자 원문에서 부정 표현으로 확인됨.",
                }
            )
    return spans


def base_example(row: dict[str, Any], title: str) -> dict[str, Any]:
    return {
        "title": title,
        "source_case_ids": [row["case_id"]],
        "visit_type": row["visit_type"],
        "question_id": row["question_id"],
        "question_type": row["question_type"],
        "question": question_text(row),
        "patient_answer": row["utterance"],
    }


def build_fewshots(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    cases = {case_id: selected_row(rows, case_id) for case_id in [
        "train_v2_007",
        "train_v2_038",
        "train_v2_041",
        "train_v2_055",
        "train_v2_067",
        "train_v2_085",
        "train_v2_093",
    ]}
    fewshots: dict[str, dict[str, Any]] = {}
    provenance: dict[str, Any] = {}

    extraction_examples = []
    for case_id, title in [
        ("train_v2_007", "Gangwon Q1 with two active upper-airway symptoms"),
        ("train_v2_041", "Active chest pain with explicitly absent dyspnea"),
        ("train_v2_038", "Follow-up sputum character hidden behind lay wording"),
        ("train_v2_055", "Follow-up improvement still needs current-state care"),
    ]:
        row = cases[case_id]
        example = base_example(row, title)
        example["expected_json"] = {
            "spans": expected_spans(row),
            "structured": {
                "standardized_text": standardized_text(row),
                "clinical_clues": [],
                "questions": [],
                "unresolved_items": [],
            },
        }
        extraction_examples.append(example)
    fewshots["extraction"] = {
        "stage": "extraction",
        "source_dataset": "evaluation/train_100_v2/train_100_v2.jsonl",
        "selection_policy": "Sparse representative examples only; do not memorize the train set.",
        "examples": extraction_examples,
    }

    standardization_examples = []
    for case_id, title in [
        ("train_v2_007", "Normalize light Gangwon pronunciation without adding facts"),
        ("train_v2_085", "Normalize RAG-anchored dialect body term"),
        ("train_v2_067", "Normalize RAG-anchored fatigue word"),
        ("train_v2_093", "Normalize RAG-anchored abdominal wording"),
    ]:
        row = cases[case_id]
        example = base_example(row, title)
        example["original"] = row["utterance"]
        example["standardized"] = standardized_text(row)
        example["expected_json"] = {"standardized_text": standardized_text(row), "normalization_notes": []}
        standardization_examples.append(example)
    fewshots["standardization"] = {
        "stage": "standardization",
        "source_dataset": "evaluation/train_100_v2/train_100_v2.jsonl",
        "examples": standardization_examples,
    }

    semantic_examples = []
    for case_id, title in [
        ("train_v2_041", "Split active symptom and explicit absence"),
        ("train_v2_055", "Keep improved but still present course as one meaning unit"),
        ("train_v2_038", "Keep sputum color and character together"),
    ]:
        row = cases[case_id]
        example = base_example(row, title)
        example["input"] = row["utterance"]
        example["meaning_units"] = [
            {
                "source_quote": row["utterance"],
                "summary": standardized_text(row),
                "question_id": row["question_id"],
            }
        ]
        example["expected_output"] = "Meaning units must preserve negation, improvement, and modifiers as stated."
        semantic_examples.append(example)
    fewshots["semantic_unit"] = {
        "stage": "semantic_unit",
        "source_dataset": "evaluation/train_100_v2/train_100_v2.jsonl",
        "examples": semantic_examples,
    }

    tagging_examples = []
    for case_id, title in [
        ("train_v2_007", "Two active spans from one answer"),
        ("train_v2_041", "Do not turn absent dyspnea into an active card"),
        ("train_v2_085", "Dialect headache with absent dizziness"),
    ]:
        row = cases[case_id]
        example = base_example(row, title)
        example["input"] = row["utterance"]
        example["tagged_spans"] = expected_spans(row)
        tagging_examples.append(example)
    fewshots["span_tagging"] = {
        "stage": "span_tagging",
        "source_dataset": "evaluation/train_100_v2/train_100_v2.jsonl",
        "examples": tagging_examples,
    }

    hint_examples = []
    for case_id, title in [
        ("train_v2_007", "Map 아푸나 and 코 막힘 to canonical hints"),
        ("train_v2_038", "Map 누렇고 짙은 가래 to purulent sputum"),
        ("train_v2_041", "Map 가슴 아픔 while preserving absent 숨참"),
        ("train_v2_085", "Map 머리깽이 to headache and 어지럽지는 않아 to absent dizziness"),
        ("train_v2_093", "Map 창지 꼬임 to abdominal pain"),
    ]:
        row = cases[case_id]
        example = base_example(row, title)
        example["input"] = row["utterance"]
        example["expected_output"] = {
            "positive_symptoms": row.get("gold_symptoms") or [],
            "negative_symptoms": row.get("explicitly_negated_symptoms") or row.get("negative_symptoms") or [],
        }
        hint_examples.append(example)
    fewshots["symptom_hint"] = {
        "stage": "symptom_hint",
        "source_dataset": "evaluation/train_100_v2/train_100_v2.jsonl",
        "examples": hint_examples,
    }

    onepager_examples = []
    for case_id, title in [
        ("train_v2_041", "Safety-sensitive chest pain without unsupported dyspnea"),
        ("train_v2_055", "Follow-up improvement still requires current severity clarification"),
    ]:
        row = cases[case_id]
        example = base_example(row, title)
        example["expected_json"] = {
            "review_items": [
                f"{', '.join(row.get('gold_symptoms') or [])}의 현재 지속 여부와 심한 정도 확인",
            ],
            "transfer_text": f"S) 문진 답변 / CC: {', '.join(row.get('gold_symptoms') or [])} / PI: {standardized_text(row)} / 확인: 지속 여부와 악화 신호",
            "doctor_brief": {
                "근거": [
                    row["utterance"],
                ]
            },
        }
        onepager_examples.append(example)
    fewshots["onepager_review"] = {
        "stage": "onepager_review",
        "source_dataset": "evaluation/train_100_v2/train_100_v2.jsonl",
        "examples": onepager_examples,
    }

    for stage, payload in fewshots.items():
        for example in payload["examples"]:
            key = f"fewshot:{stage}:{example['source_case_ids'][0]}"
            provenance[key] = {
                "artifact_type": f"fewshots.{stage}",
                "source_case_ids": example["source_case_ids"],
                "source_quote": example["patient_answer"],
                "acceptance_reason": "Selected as a sparse representative example from accepted train_100_v2.",
            }
    return fewshots, provenance


def build_domain_pack(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    symptom_rules, rule_provenance = build_symptom_rules(rows)
    aliases, quote_patterns, alias_provenance = build_aliases(rows)

    pack = {
        "version": VERSION,
        "description": "Train-derived respiratory/ENT/general symptom support pack built only from train_100_v2.",
        "source_dataset": "evaluation/train_100_v2/train_100_v2.jsonl",
        "fewshot_id": "respiratory",
        "fewshot_sets": {
            stage: f"fewshots/respiratory/{stage}.json"
            for stage in [
                "extraction",
                "standardization",
                "semantic_unit",
                "span_tagging",
                "symptom_hint",
                "onepager_review",
            ]
        },
        "symptom_rules": symptom_rules,
        "symptom_quote_patterns": quote_patterns,
        "ir_stable_slot_ids": {item["name"]: item["slot_id"] for item in symptom_rules},
        "ir_slot_to_canonical_name": {item["slot_id"]: item["name"] for item in symptom_rules},
        "ir_text_aliases": aliases,
        "ir_red_flag_names": sorted(ALERT_SYMPTOMS),
        "safety_flags": [
            {
                "category": "dyspnea",
                "label": "호흡곤란",
                "severity": "high",
                "pattern": r"숨.{0,10}(힘들|차|가쁘|안 쉬)",
            },
            {
                "category": "chest_pain",
                "label": "흉통",
                "severity": "high",
                "pattern": r"가슴.{0,10}(아프|통증|찌르|쑤시)",
            },
            {
                "category": "hemoptysis",
                "label": "객혈",
                "severity": "high",
                "pattern": r"(기침.{0,12}피|피.{0,8}(섞|가래|나오))",
            },
            {
                "category": "cyanosis",
                "label": "청색증",
                "severity": "high",
                "pattern": r"입술.{0,8}(파래|파랗|푸르)",
            },
        ],
        "excluded_ir_symptom_names": [],
        "alert_slot_ids": [SLOT_IDS[name] for name in sorted(ALERT_SYMPTOMS)],
        "reviewer_domain_rules": {
            "rule5": "5. Do NOT add fever/temperature tasks unless fever, heat, chill, high fever, antipyretic use, or body temperature appears in evidence.",
            "rule6": "6. Do NOT add X-ray, TB, pneumonia, cancer, antibiotics, or lab/test tasks unless safety_flags, patient wording, or clinician agenda explicitly supports them.",
            "rule11_suffix": "Ordinary sore throat, nasal obstruction, cough, runny nose, fatigue, or GI discomfort must not be marked urgent unless a safety flag is present.",
        },
        "agenda_category_rules": [
            {"category": "drug_drug_interaction", "all_of": [["약", "처방", "복용"], ["같이", "함께", "먹어도"]]},
            {"category": "supplement_drug_interaction", "all_of": [["영양제", "한약", "홍삼"], ["같이", "함께", "먹어도"]]},
            {"category": "food_drug_interaction", "all_of": [["음식", "술", "커피"], ["약", "먹어도", "피해야"]]},
            {"category": "treatment_duration", "all_of": [["언제까지", "얼마나", "며칠"], ["약", "치료", "복용"]]},
            {"category": "followup_visit", "all_of": [["다시", "재진", "방문"], ["언제", "가야"]]},
            {"category": "test_question", "all_of": [["검사", "엑스레이", "CT"], ["언제", "필요", "괜찮"]]},
            {"category": "lifestyle", "all_of": [["운동", "일", "생활", "샤워"], ["해도", "가능", "괜찮"]]},
        ],
    }
    provenance = {**rule_provenance, **alias_provenance}
    return pack, provenance


def validate_pack(pack: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    train_symptoms = sorted({symptom for row in rows for symptom in row.get("gold_symptoms") or []})
    pack_symptoms = sorted(item["name"] for item in pack["symptom_rules"])
    if train_symptoms != pack_symptoms:
        raise RuntimeError("Domain pack symptom rules do not match train gold symptom set.")
    for item in pack["ir_text_aliases"]:
        re.compile(item["pattern"])
    for patterns in pack["symptom_quote_patterns"].values():
        for pattern in patterns:
            re.compile(pattern)
    fewshot_sources = []
    return {
        "train_rows": len(rows),
        "train_gold_symptoms": len(train_symptoms),
        "symptom_rules": len(pack["symptom_rules"]),
        "alias_patterns": len(pack["ir_text_aliases"]),
        "quote_pattern_slots": len(pack["symptom_quote_patterns"]),
        "alert_slot_ids": pack["alert_slot_ids"],
        "fewshot_source_cases": fewshot_sources,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    rows = read_rows()
    pack, provenance = build_domain_pack(rows)
    fewshots, fewshot_provenance = build_fewshots(rows)
    provenance.update(fewshot_provenance)

    report = validate_pack(pack, rows)
    report.update(
        {
            "version": VERSION,
            "source_dataset": str(TRAIN_PATH.relative_to(ROOT)).replace("\\", "/"),
            "language_style_counts": dict(Counter(row["language_style"] for row in rows)),
            "question_counts": dict(Counter(row["question_id"] for row in rows)),
            "dialect_source_layer_counts": dict(Counter(row["dialect_source_layer"] for row in rows)),
            "fewshot_counts": {stage: len(payload["examples"]) for stage, payload in fewshots.items()},
            "provenance_entries": len(provenance),
            "test_data_used": False,
        }
    )

    write_json(DOMAIN_PACK_PATH, pack)
    for stage, payload in fewshots.items():
        write_json(FEWSHOT_DIR / f"{stage}.json", payload)
    write_json(PROVENANCE_PATH, provenance)
    write_json(REPORT_PATH, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

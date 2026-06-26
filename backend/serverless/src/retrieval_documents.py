"""아산백과 기반 표준 증상 검색 문서 생성.

이 파일은 LLM이 만든 데이터를 새로 섞지 않습니다. `diseases_cleaned.json`과
`symptom_index.json` 두 원천 JSON만 읽어서 Hybrid IR이 검색할 문서를 만듭니다.
"""

import hashlib
import re
from collections import Counter

from clinical_terms import (
    IR_SLOT_TO_CANONICAL_NAME,
    IR_STABLE_SLOT_IDS,
    IR_TEXT_ALIASES,
    SYMPTOM_RULES,
)
from domain_config import get_domain_pack
from settings import DISEASES_PATH, SYMPTOM_INDEX_PATH
from retrieval_scoring import BM25Index
from utils import (
    compact_ir,
    load_json_file,
    normalize_text,
    sentence_directly_mentions_symptom,
    split_sentences_ir,
    trim_snippet,
)

_IR_DOCS = None
_IR_BM25 = None
_IR_ID_TO_NAME = {}
_IR_NAME_TO_ID = {}


def make_symptom_id(symptom_name):
    """표준 증상명에 안정적인 slot_id를 부여합니다."""
    if symptom_name in IR_STABLE_SLOT_IDS:
        return IR_STABLE_SLOT_IDS[symptom_name]
    digest = hashlib.sha1(symptom_name.encode("utf-8")).hexdigest()[:10]
    return f"symptom:{digest}"


def _candidate_names_from_domain_pack():
    """공개 가능한 domain pack만으로 최소 IR 후보명을 구성합니다."""
    names = set(IR_STABLE_SLOT_IDS.keys())
    names.update(name for name in IR_SLOT_TO_CANONICAL_NAME.values() if name)
    names.update(name for name, _, _, _ in SYMPTOM_RULES if name)
    return sorted(names)


def _aliases_for_domain_name(symptom_name):
    """domain pack의 rule keyword와 alias pattern을 한 증상 후보의 검색 텍스트로 묶습니다."""
    aliases = []
    canonical_slot_ids = {
        slot_id
        for slot_id, canonical_name in IR_SLOT_TO_CANONICAL_NAME.items()
        if canonical_name == symptom_name
    }
    stable_slot_id = IR_STABLE_SLOT_IDS.get(symptom_name)
    if stable_slot_id:
        canonical_slot_ids.add(stable_slot_id)
    for rule_name, slot_id, keywords, _alert in SYMPTOM_RULES:
        if rule_name == symptom_name or slot_id in canonical_slot_ids:
            aliases.extend(keywords)
    for pattern, canonical_name in IR_TEXT_ALIASES:
        if canonical_name == symptom_name:
            aliases.append(pattern)
    return sorted({normalize_text(alias) for alias in aliases if normalize_text(alias)})


def build_symptom_docs_from_domain_pack():
    """비공개 원천 JSON이 없을 때 사용하는 공개 domain-pack 기반 IR 문서입니다.

    이 폴백은 새 증상을 환자 발화에서 규칙으로 추출하지 않습니다. LLM이 만든 span을
    표준 증상 후보와 비교하기 위한 최소 검색 표면만 제공하며, 전체 성능 고도화는
    비공개 참조 JSON 또는 별도 private layer/S3 번들에서 담당합니다.
    """
    pack = get_domain_pack()
    docs = []
    for symptom_name in _candidate_names_from_domain_pack():
        symptom_id = make_symptom_id(symptom_name)
        aliases = _aliases_for_domain_name(symptom_name)
        alias_text = " ".join(aliases)
        retrieval_text = normalize_text(
            " ".join(
                [
                    f"표준 증상명 {symptom_name}.",
                    f"도메인팩 기반 공개 증상 후보 {symptom_name}.",
                    f"관련 표현 {alias_text}.",
                ]
            )
        )
        docs.append({
            "symptom_id": symptom_id,
            "display_name": symptom_name,
            "bm25_text": normalize_text(" ".join([symptom_name, alias_text])),
            "retrieval_text": retrieval_text,
            "embedding_text": retrieval_text,
            "evidence": [
                {
                    "content_id": pack.get("version", "domain_pack"),
                    "disease_name": "domain_pack",
                    "section": "domain_alias",
                    "text": normalize_text(" ".join([symptom_name, alias_text])),
                }
            ],
            "evidence_refs": [],
            "linked_disease_names": [],
            "domain_candidates": [pack.get("description", "domain_pack")],
            "departments": [],
            "source": "domain_pack_backup",
        })
    return docs


def build_symptom_docs_from_sources():
    """diseases_cleaned + symptom_index만으로 검색 문서를 생성합니다.

    여기서 말하는 rule-base는 "새 증상 추출"이 아니라 원천 JSON을 검색 가능한
    문서 형태로 접는 작업입니다. 환자 발화에서 증상을 뽑는 일은 LLM이 담당합니다.
    """
    if not DISEASES_PATH.exists() or not SYMPTOM_INDEX_PATH.exists():
        return build_symptom_docs_from_domain_pack()

    diseases = load_json_file(DISEASES_PATH)
    symptom_index = load_json_file(SYMPTOM_INDEX_PATH)
    disease_by_content_id = {}
    disease_rows = diseases if isinstance(diseases, list) else []
    for disease in disease_rows:
        cid = str(disease.get("content_id", ""))
        if cid:
            disease_by_content_id[cid] = disease

    docs = []
    for symptom_name in sorted(symptom_index.keys()):
        refs = symptom_index.get(symptom_name) or []
        symptom_id = make_symptom_id(symptom_name)
        evidence_refs = []
        direct_snippets = []
        linked_disease_names = []
        departments_counter = Counter()
        categories_counter = Counter()
        seen_content_ids = set()

        for ref in refs:
            cid = str(ref.get("content_id", ""))
            if not cid or cid in seen_content_ids:
                continue
            seen_content_ids.add(cid)
            disease = disease_by_content_id.get(cid)
            if not disease:
                continue
            name_ko = normalize_text(disease.get("name_ko") or ref.get("name_ko") or "")
            category = normalize_text(disease.get("category") or "")
            if name_ko:
                linked_disease_names.append(name_ko)
            if category:
                categories_counter[category] += 1
            for dep in disease.get("departments") or ref.get("departments") or []:
                dep = normalize_text(dep)
                if dep:
                    departments_counter[dep] += 1

            sections = disease.get("sections") or {}
            definition = normalize_text(sections.get("definition", ""))
            symptom_section = normalize_text(sections.get("symptom", ""))
            evidence_refs.append({
                "content_id": cid,
                "disease_name": name_ko,
                "source_url": disease.get("source_url", ref.get("source_url", "")),
                "category": category,
                "departments": disease.get("departments") or ref.get("departments") or [],
                "symptom_in_list": symptom_name in (disease.get("symptoms") or []),
            })

            for section_name, text in (("symptom", symptom_section), ("definition", definition)):
                for sent in split_sentences_ir(text):
                    if sentence_directly_mentions_symptom(sent, symptom_name):
                        snippet = trim_snippet(sent)
                        key = (cid, section_name, snippet)
                        if not any((x["content_id"], x["section"], x["text"]) == key for x in direct_snippets):
                            direct_snippets.append({
                                "content_id": cid,
                                "disease_name": name_ko,
                                "section": section_name,
                                "text": snippet,
                            })
                    if len(direct_snippets) >= 8:
                        break
                if len(direct_snippets) >= 8:
                    break

        top_diseases = [name for name in linked_disease_names if name][:8]
        top_departments = [name for name, _ in departments_counter.most_common(6)]
        top_categories = [name for name, _ in categories_counter.most_common(4)]
        direct_text = " ".join(item["text"] for item in direct_snippets[:5])
        disease_text = ", ".join(top_diseases)
        dept_text = ", ".join(top_departments)
        alias_text = " ".join(_aliases_for_domain_name(symptom_name))
        retrieval_parts = [
            f"표준 증상명: {symptom_name}.",
            f"아산백과 증상 목록에서 '{symptom_name}'으로 기록된 표준 증상 후보.",
        ]
        if alias_text:
            retrieval_parts.append(f"도메인 alias 표현: {alias_text}.")
        if direct_text:
            retrieval_parts.append(f"증상 직접 근거 문장: {direct_text}")
        if disease_text:
            retrieval_parts.append(f"관련 아산백과 문서명: {disease_text}.")
        if dept_text:
            retrieval_parts.append(f"관련 진료과: {dept_text}.")
        embedding_parts = [
            f"{symptom_name}.",
            f"환자 발화에서 '{symptom_name}'과 의미가 가까운 증상 표현을 표준 증상 후보로 매칭하기 위한 문서.",
        ]
        if direct_text:
            embedding_parts.append(direct_text)
        docs.append({
            "symptom_id": symptom_id,
            "display_name": symptom_name,
            "bm25_text": normalize_text(" ".join([symptom_name, f"표준 증상명 {symptom_name}", alias_text, direct_text])),
            "retrieval_text": normalize_text("\n".join(retrieval_parts)),
            "embedding_text": normalize_text(" ".join(embedding_parts)),
            "evidence": direct_snippets[:8],
            "evidence_refs": evidence_refs,
            "linked_disease_names": top_diseases,
            "domain_candidates": top_categories,
            "departments": top_departments,
            "source": "diseases_cleaned+symptom_index",
        })
    return docs


def get_ir_index():
    """Cold start 이후 재사용할 증상 문서와 BM25 index를 lazy-load합니다."""
    global _IR_DOCS, _IR_BM25, _IR_ID_TO_NAME, _IR_NAME_TO_ID
    if _IR_DOCS is None:
        docs = build_symptom_docs_from_sources()
        _IR_DOCS = docs
        _IR_BM25 = BM25Index(docs)
        _IR_ID_TO_NAME = {doc["symptom_id"]: doc["display_name"] for doc in docs}
        _IR_NAME_TO_ID = {doc["display_name"]: doc["symptom_id"] for doc in docs}
    return _IR_DOCS, _IR_BM25


def get_symptom_name_by_id(slot_id):
    """검색 인덱스에 들어 있는 slot_id를 표준 증상명으로 되돌립니다."""
    get_ir_index()
    return _IR_ID_TO_NAME.get(slot_id)


def preferred_canonical_name(slot_id, *texts):
    """LLM slot_ref/name이 명확할 때 IR 후보에 가벼운 힌트를 줍니다."""
    docs, _ = get_ir_index()
    valid_names = {doc["display_name"] for doc in docs}
    joined = normalize_text(" ".join(text for text in texts if text))
    compact_joined = compact_ir(joined)
    for pattern, name in IR_TEXT_ALIASES:
        if name in valid_names and re.search(pattern, joined):
            return name
    for name in sorted(valid_names, key=lambda item: len(compact_ir(item)), reverse=True):
        compact_name = compact_ir(name)
        if compact_name and compact_name in compact_joined:
            return name
    mapped = IR_SLOT_TO_CANONICAL_NAME.get(str(slot_id or ""))
    if mapped in valid_names:
        return mapped
    return ""

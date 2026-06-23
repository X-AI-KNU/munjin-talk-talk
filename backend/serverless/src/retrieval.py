"""Symptom retrieval and scoring.

LLM이 추출한 symptom span을 그대로 믿지 않고, Asan-derived source JSON에서 만든
증상 문서를 대상으로 BM25 lexical score, Titan embedding vector score, label/alias
hint를 조합해 표준 증상명으로 매칭합니다.
"""

import re
from decimal import Decimal

from clinical_state import is_non_active_symptom_state
from clinical_terms import (
    ALERT_SLOT_IDS,
    IR_RED_FLAG_NAMES,
    SYMPTOM_RULES,
    is_symptom_like_span,
)
from settings import (
    HYBRID_ACCEPT_THRESHOLD,
    HYBRID_BM25_WEIGHT,
    HYBRID_CANDIDATE_K,
    HYBRID_MIN_BM25_SCORE,
    HYBRID_MIN_LABEL_SCORE,
    HYBRID_MIN_VECTOR_SCORE,
    HYBRID_TOP_K,
    HYBRID_VECTOR_WEIGHT,
)
from domain_config import excluded_ir_symptom_names
from retrieval_documents import get_ir_index, get_symptom_name_by_id, preferred_canonical_name
from retrieval_embeddings import embed_text, get_doc_embeddings
from retrieval_scoring import cosine, direct_label_score, minmax_norm
from utils import (
    normalize_text,
)


EXCLUDED_IR_SYMPTOM_NAMES = excluded_ir_symptom_names()

# LLM이 검색 힌트로 쓸 수는 있지만, IR query에 붙이면 오히려 검색을 흐리는 표현입니다.
# 예를 들어 "목이 칼칼하다 + 불편함"보다 "목이 칼칼하다"만 검색하는 편이 안정적입니다.
GENERIC_SYMPTOM_HINTS = {
    "불편",
    "불편함",
    "불편 증상",
    "증상",
    "증세",
    "문제",
    "이상",
    "느낌",
    "몸살",
    "몸살 느낌",
    "일반적인 불편함",
    "환자 질문",
    "통증",
    "아픔",
}
GENERIC_SYMPTOM_HINT_PATTERNS = [
    r"^(일반적인\s*)?불편(함|감| 증상)?$",
    r"^(증상|증세|문제|이상|느낌)$",
    r"^몸살(\s*느낌)?$",
    r"^환자\s*질문$",
    r"^(통증|아픔)$",
]

IR_QUERY_NOISE_PATTERNS = [
    r"\[[^\]]+\]",
    r"\b(환자|보호자|딸|아들|배우자)\b",
    r"(의사에게|선생님께|추가로|따로|궁금한|궁금합니다|질문|문의|여쭤보고|싶습니다|싶어요)",
]


def retrieve_symptom_docs(source_quote, normalized_text, span_name="", preferred_slot_id=""):
    """하나의 symptom span에 대해 BM25/vector/label 후보를 모아 상위 증상을 반환합니다."""
    docs, bm25 = get_ir_index()
    query = build_symptom_query(source_quote, normalized_text, span_name)
    if not query:
        return []
    preferred_name = preferred_canonical_name(preferred_slot_id, span_name, normalized_text, source_quote)

    bm25_raw = bm25.scores(query)
    bm25_norm = minmax_norm(bm25_raw)
    q_emb = None
    vector_raw = [0.0] * len(docs)
    vector_error = ""
    try:
        q_emb = embed_text(query)
    except Exception as exc:
        # 운영 trace에는 원문 예외 메시지를 남기지 않는다.
        # AWS/라이브러리 예외에는 요청 본문 일부가 섞일 수 있어 타입만 보존한다.
        vector_error = f"embedding_exception:{exc.__class__.__name__}"

    doc_embeddings = get_doc_embeddings(docs) if q_emb is not None else {}
    if q_emb is not None and doc_embeddings:
        for idx, doc in enumerate(docs):
            vector_raw[idx] = max(0.0, cosine(q_emb, doc_embeddings.get(doc["symptom_id"])))
    vector_norm = minmax_norm(vector_raw)

    candidate_k = max(HYBRID_CANDIDATE_K, HYBRID_TOP_K * 3)
    bm25_top = set(sorted(range(len(docs)), key=lambda i: bm25_norm[i], reverse=True)[:candidate_k])
    vector_top = set(sorted(range(len(docs)), key=lambda i: vector_norm[i], reverse=True)[:candidate_k]) if doc_embeddings else set()
    label_top = {
        idx
        for idx, doc in enumerate(docs)
        if direct_label_score(query, doc["display_name"]) >= 0.55 or doc["display_name"] == preferred_name
    }
    candidate_ids = bm25_top | vector_top | label_top
    if q_emb is not None and not doc_embeddings:
        # 배포 패키지에 사전 계산 vector index가 없으면 BM25/label 후보만 대상으로
        # Titan embedding을 즉시 계산해 semantic 비교를 이어갑니다.
        for idx in list(candidate_ids):
            try:
                emb = embed_text(docs[idx].get("embedding_text", ""))
                vector_raw[idx] = max(0.0, cosine(q_emb, emb))
            except Exception as exc:
                # 재시도 실패도 같은 정책으로 예외 타입만 남긴다.
                vector_error = f"embedding_retry_exception:{exc.__class__.__name__}"
        candidate_vectors = [vector_raw[idx] for idx in candidate_ids]
        norm_lookup = dict(zip(candidate_ids, minmax_norm(candidate_vectors)))
        vector_norm = [norm_lookup.get(idx, 0.0) for idx in range(len(docs))]

    rows = []
    intersection_ids = bm25_top & (vector_top or candidate_ids)
    for idx in candidate_ids:
        doc = docs[idx]
        if doc["display_name"] in EXCLUDED_IR_SYMPTOM_NAMES:
            # 인덱스/embedding hash는 유지하고, 운영 후보 채택에서만 제외합니다.
            continue
        label = direct_label_score(query, doc["display_name"])
        preferred_hit = doc["display_name"] == preferred_name
        if preferred_hit:
            label = max(label, 1.0)
        if bm25_norm[idx] <= 0 and vector_norm[idx] <= 0 and label <= 0:
            continue
        branch = "both" if idx in intersection_ids else ("bm25_only" if idx in bm25_top else "vector_only")
        rank_score = HYBRID_BM25_WEIGHT * bm25_norm[idx] + HYBRID_VECTOR_WEIGHT * vector_norm[idx] + 0.25 * label
        if preferred_hit:
            branch = "preferred_alias"
            rank_score += 0.45
        if branch == "both":
            rank_score += 0.08
        elif branch == "bm25_only" and vector_raw[idx] < 0.12:
            rank_score *= 0.55

        vector_conf = max(0.0, min(1.0, vector_raw[idx] / 0.30))
        match_score = 0.50 * bm25_norm[idx] + 0.50 * vector_conf
        if preferred_hit:
            match_score = max(match_score, 0.90)
        if branch == "both":
            match_score = min(1.0, match_score + 0.08)
        elif branch == "bm25_only" and vector_raw[idx] < 0.12:
            match_score *= 0.70
        elif branch == "vector_only" and bm25_norm[idx] == 0 and vector_raw[idx] < 0.16:
            match_score *= 0.85

        rows.append({
            "slot_id": doc["symptom_id"],
            "display_text": doc["display_name"],
            "score": round(float(match_score), 4),
            "rank_score": round(float(rank_score), 4),
            "bm25_score": round(float(bm25_norm[idx]), 4),
            "vector_score": round(float(vector_raw[idx]), 4),
            "vector_norm": round(float(vector_norm[idx]), 4),
            "label_score": round(float(label), 4),
            "retrieval_branch": branch,
            "source": doc.get("source", "diseases_cleaned+symptom_index"),
            "evidence": doc.get("evidence", [])[:3],
            "linked_disease_names": doc.get("linked_disease_names", [])[:8],
            "domain_candidates": doc.get("domain_candidates", []),
            "vector_error": vector_error,
        })

    rows.sort(key=lambda item: item["rank_score"], reverse=True)
    return rows[:HYBRID_TOP_K]


def is_hybrid_candidate_accepted(candidate):
    """표준 증상 확정에는 Titan 의미 신호와 lexical/label 근거가 함께 필요합니다."""
    bm25 = float(candidate.get("bm25_score") or 0)
    vector = float(candidate.get("vector_score") or 0)
    label = float(candidate.get("label_score") or 0)
    if vector >= HYBRID_MIN_VECTOR_SCORE and (bm25 >= HYBRID_MIN_BM25_SCORE or label >= HYBRID_MIN_LABEL_SCORE):
        return True, "vector_plus_lexical_or_label"
    return False, (
        "hybrid_gate_failed:"
        f" vector={vector}, bm25={bm25}, label={label}"
    )

def match_slots(body):
    """LangGraph 내부 IR 단계. LLM span을 원페이퍼에 표시할 matched_slots로 변환합니다."""
    spans = body.get("spans") or []
    matched = []
    unmatched = []
    for span in spans:
        slot_id = span.get("slot_ref") or "other"
        span_type = span.get("type", "symptom")
        if not has_ir_eligible_symptom_span(span):
            unmatched.append(span)
            continue
        candidates = retrieve_symptom_docs(
            span.get("source_quote", ""),
            span.get("normalized_text") or span.get("name") or "",
            span.get("name") or slot_to_name(slot_id),
            slot_id,
        )
        if not candidates:
            unmatched.append(span)
            continue
        top = candidates[0]
        score = Decimal(str(top.get("score", 0)))
        accepted, accept_reason = is_hybrid_candidate_accepted(top)
        if not accepted:
            rejected = dict(span)
            rejected["ir_rejected"] = True
            rejected["ir_reject_reason"] = accept_reason
            rejected["top_candidates"] = candidates[:3]
            unmatched.append(rejected)
            continue
        status = span.get("status") if span.get("status") in ("있음", "없음", "확인필요") else "있음"
        if status == "있음" and float(score) < HYBRID_ACCEPT_THRESHOLD:
            status = "확인필요"
        name = top.get("display_text") or span.get("name") or slot_to_name(top.get("slot_id"))
        alert = bool(
            span.get("alert")
            or top.get("slot_id") in ALERT_SLOT_IDS
            or name in IR_RED_FLAG_NAMES
        )
        matched.append({
            "slot_id": top.get("slot_id"),
            "name": name,
            "score": score,
            "source_quote": span.get("source_quote", ""),
            "span_type": span_type,
            "alert": alert,
            "normalized_text": span.get("normalized_text") or span.get("name") or name,
            "status": status,
            "explain": make_symptom_match_explain(span, top),
            "ir_method": "bm25_titan_hybrid",
            "ir_trace": {
                "query": normalize_text(" ".join([
                    span.get("source_quote", ""),
                    span.get("normalized_text") or span.get("name") or "",
                ])),
                "bm25_score": top.get("bm25_score"),
                "vector_score": top.get("vector_score"),
                "vector_norm": top.get("vector_norm"),
                "label_score": top.get("label_score"),
                "rank_score": top.get("rank_score"),
                "retrieval_branch": top.get("retrieval_branch"),
                "accept_reason": accept_reason,
                "source": top.get("source"),
                "linked_disease_names": top.get("linked_disease_names", []),
                "evidence": top.get("evidence", []),
                "top_candidates": [
                    {
                        "slot_id": cand.get("slot_id"),
                        "name": cand.get("display_text"),
                        "score": cand.get("score"),
                        "bm25_score": cand.get("bm25_score"),
                        "vector_score": cand.get("vector_score"),
                        "rank_score": cand.get("rank_score"),
                    }
                    for cand in candidates[:3]
                ],
            },
        })
    return {"matched_slots": matched, "unmatched_spans": unmatched}


def should_skip_active_symptom_ir(span):
    """호전/부재로 검증된 span은 현재 불편함 카드용 IR에서 제외합니다.

    LLM이 "열은 내렸다", "두통은 없어졌다", "지금 열은 없다"처럼
    호전/부재 맥락을 `progress_improved`, `symptom_absent`, `status=없음`
    조합으로 태깅했다면, 해당 표현은 "오늘 말한 불편함" 카드로 올리지 않습니다.
    대신 answers artifact와 clinical_clues에서 재진 경과/현재 부재 단서로 확인합니다.
    """
    return is_non_active_symptom_state(span)


def has_ir_eligible_symptom_span(span):
    """현재 증상으로 태깅된 span이면 문항 종류와 무관하게 IR 대상으로 봅니다.

    Q3 복약 문항처럼 질문 의도는 복약 확인이어도 환자가 "약은 없고 숨이 차다"처럼
    현재 증상을 함께 말할 수 있습니다. 이때 question_type으로 먼저 거르면 실제 증상을
    놓치므로, span 자체가 active symptom인지 여부를 IR 실행 기준으로 사용합니다.
    """
    if not isinstance(span, dict):
        return False
    slot_id = span.get("slot_ref") or "other"
    span_type = span.get("type", "symptom")
    if should_skip_active_symptom_ir(span):
        return False
    return is_symptom_like_span(span_type, slot_id)


def build_symptom_query(source_quote, normalized_text, span_name=""):
    """IR query를 표준화 span과 LLM 증상 힌트 중심으로 구성합니다.

    IR 평가에서 원문 방언 quote까지 섞은 A안보다 `normalized_text + name`을 쓰는
    C안이 더 안정적이었습니다. 따라서 source_quote는 검증/trace에는 남기되,
    검색어에는 표준화된 의미와 LLM의 자연어 증상 힌트를 우선 사용합니다.
    표준화 결과가 비어 있는 예외 상황에서만 원문 quote를 보조 query로 사용합니다.
    """
    normalized = clean_ir_query_component(normalized_text)
    hint = clean_ir_query_component(span_name)
    if normalized and hint and not is_generic_symptom_hint(hint):
        return normalize_text(f"{normalized} {hint}")
    if normalized:
        return normalized
    if hint and not is_generic_symptom_hint(hint):
        return hint
    return clean_ir_query_component(source_quote)


def clean_ir_query_component(value):
    """IR 검색에 방해되는 speaker/meta 표현만 제거합니다.

    증상 단어 자체를 새로 만들거나 alias를 추가하지 않습니다. 환자/보호자 표식,
    "궁금합니다" 같은 agenda 표현처럼 검색 의도를 흐리는 주변 말만 걷어내어
    BM25와 vector가 실제 증상 표현에 더 집중하도록 합니다.
    """
    text = normalize_text(value or "")
    if not text:
        return ""
    for pattern in IR_QUERY_NOISE_PATTERNS:
        text = re.sub(pattern, " ", text)
    return normalize_text(text)


def is_generic_symptom_hint(span_name):
    """IR query에 붙이면 검색 품질을 떨어뜨리는 너무 일반적인 LLM hint인지 판단합니다.

    이 함수는 증상 정답을 새로 추정하지 않습니다. 단지 "불편함", "증상",
    "몸살 느낌"처럼 거의 모든 후보에 붙을 수 있는 단어를 query 확장에 쓰지 않도록
    막는 필터입니다. 구체 판단은 이후 BM25/vector와 linker가 담당합니다.
    """
    hint = normalize_text(span_name or "")
    if not hint:
        return True
    if hint in GENERIC_SYMPTOM_HINTS:
        return True
    if any(re.fullmatch(pattern, hint) for pattern in GENERIC_SYMPTOM_HINT_PATTERNS):
        return True
    tokens = [token for token in re.split(r"[\s,/|]+", hint) if token]
    return bool(tokens) and all(token in GENERIC_SYMPTOM_HINTS for token in tokens)


def slot_to_name(slot_id):
    if slot_id:
        indexed_name = get_symptom_name_by_id(slot_id)
        if indexed_name:
            return indexed_name
    mapping = {slot_id: name for name, slot_id, _, _ in SYMPTOM_RULES}
    return mapping.get(slot_id, slot_id or "-")


def make_symptom_match_explain(span, top):
    branch = top.get("retrieval_branch") or "hybrid"
    if branch == "safety_alias_override":
        return "안전 관련 핵심 표현이 있어 표준 증상 후보를 우선 매칭했습니다."
    return (
        "환자 표현을 아산백과 기반 증상 인덱스와 비교했고, "
        "어휘 근거와 Titan 의미 벡터 근거가 함께 충족되어 표준 증상으로 매칭했습니다."
    )

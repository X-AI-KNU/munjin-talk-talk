#!/usr/bin/env python3
"""문진톡톡 증상 IR 성능 평가 도구.

이 스크립트는 운영 Lambda를 호출하지 않고, backend/serverless/src의 IR 인덱스와
scoring 함수를 직접 불러와 표준 증상 후보 검색과 Pro linker 성능을 확인합니다.
기본 실행은 제출 기준으로 채택한 G안입니다.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = PROJECT_ROOT / "backend" / "serverless" / "src"
sys.path.insert(0, str(BACKEND_SRC))

try:
    from retrieval import build_symptom_query  # noqa: E402
    from retrieval_documents import get_ir_index, preferred_canonical_name  # noqa: E402
    from retrieval_scoring import cosine, direct_label_score, minmax_norm  # noqa: E402
    from clinical_state import is_non_active_symptom_state  # noqa: E402
    from embedding_providers import build_embedding_provider  # noqa: E402
    from settings import (  # noqa: E402
        HYBRID_BM25_WEIGHT,
        HYBRID_CANDIDATE_K,
        HYBRID_TOP_K,
        HYBRID_VECTOR_WEIGHT,
        REVIEWER_MODEL_ID,
    )
    from utils import normalize_text  # noqa: E402
except ModuleNotFoundError as exc:
    raise SystemExit(
        "평가 실행에 필요한 Python 패키지가 없습니다. "
        "프로젝트 루트에서 `pip install -r evaluation\\ir\\requirements.txt`를 먼저 실행하세요. "
        f"누락 패키지: {exc.name}"
    ) from exc


VARIANTS = {
    "A": "원문 quote + 표준어 span + LLM 증상명",
    "B": "표준어 span만",
    "C": "표준어 span + LLM 증상명",
    "O": "oracle 정답 증상명",
    "D": "표준어 span 검색 후 LLM 최종 판단",
    "E": "표준어 span + LLM 증상명 검색 후 deterministic gate",
    "F": "표준어 span + LLM 증상명 검색 후 gate + LLM 최종 판단",
    "G": "MVP 채택안: 표준어 span + LLM 증상명 검색 후 top-k 후보 Pro LLM linker",
}

LLM_LINKER_VARIANTS = {"D", "F", "G"}
TOP_K_LINKER_VARIANTS = {"G"}
IR_PRIMARY_K = 3
IR_SECONDARY_K = 5
IR_REPORT_CUTOFFS = (3, 5, 10, 20, 30)

# Gate는 후보 선택 전 검증용 방어막입니다.
# LLM 추출 span을 IR 후보로 좁힌 뒤, 후보와 원문 근거가 지나치게 멀지 않은지 확인합니다.
GATE_RETRIEVAL_TOP_K = 5
GATE_MIN_RANK_SCORE = 0.34
GATE_MIN_SUPPORT_SCORE = 0.24
GATE_MIN_VECTOR_NORM = 0.16
GATE_GENERIC_LABELS = {"통증", "불편감", "증상", "감기 증상"}
KOREAN_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")
RRF_K = 60
RRF_BM25_WEIGHT = 1.0
RRF_VECTOR_WEIGHT = 1.1
RRF_LABEL_WEIGHT = 1.8
RRF_MULTI_SIGNAL_BONUS = 0.008


def metric_cutoffs(top_k: int) -> list[int]:
    """평가 실행의 top-k 범위 안에서 보고할 컷오프 목록을 정합니다."""
    cutoffs = [k for k in IR_REPORT_CUTOFFS if k <= top_k]
    if top_k not in cutoffs:
        cutoffs.append(top_k)
    return sorted(set(cutoffs))


def ir_metric_names(top_k: int) -> list[str]:
    """summary.json/summary.csv에 기록할 IR 지표 이름을 동적으로 만듭니다."""
    names: list[str] = []
    for cutoff in metric_cutoffs(top_k):
        names.extend([
            f"recall@{cutoff}",
            f"mrr@{cutoff}",
            f"ndcg@{cutoff}",
            f"hitrate@{cutoff}",
            f"negative_hit@{cutoff}",
        ])
    return names


def candidate_metric_names(top_k: int) -> list[str]:
    """linker 전 IR 후보군 성능을 final 선택 성능과 분리하기 위한 지표 이름입니다."""
    return [f"candidate_{name}" for name in ir_metric_names(top_k)]


def main() -> int:
    args = parse_args()
    cases = load_cases(args.input)
    if not cases:
        raise SystemExit(f"평가 case가 없습니다: {args.input}")
    if args.limit > 0:
        cases = cases[:args.limit]
    if args.top_k < IR_SECONDARY_K:
        raise SystemExit(f"IR 평가는 최소 top-k={IR_SECONDARY_K} 후보가 필요합니다. --top-k 5 이상으로 실행하세요.")

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    embedder = build_embedding_provider(
        provider=args.embedding_provider,
        model_name=args.embedding_model,
        device=args.embedding_device,
        batch_size=args.embedding_batch_size,
        cache_dir=args.embedding_cache_dir,
    )

    all_case_rows: list[dict[str, Any]] = []
    all_candidate_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    active_variants = parse_requested_variants(args)

    for variant in active_variants:
        variant_case_rows = []
        for case in cases:
            case_result, candidate_rows = evaluate_case(
                case,
                variant,
                args.top_k,
                args.use_slot_hint,
                args.include_non_active_spans,
                embedder,
                args.score_mode,
            )
            variant_case_rows.append(case_result)
            all_candidate_rows.extend(candidate_rows)
        all_case_rows.extend(variant_case_rows)
        summary_rows.append(summarize_variant(variant, variant_case_rows, args.top_k))

    failure_rows = build_failure_rows(all_case_rows, args.top_k)
    final_matching = summarize_final_matching(cases)
    for row in summary_rows:
        row["embedding_provider"] = args.embedding_provider
        row["embedding_model"] = embedder.model_name
        row["score_mode"] = args.score_mode

    write_json(
        output_dir / "summary.json",
        {
            "top_k": args.top_k,
            "ir_metrics": ir_metric_names(args.top_k),
            "candidate_metrics": candidate_metric_names(args.top_k),
            "variants": summary_rows,
            "final_matching": final_matching.get("summary"),
            "embedding": {
                "provider": args.embedding_provider,
                "model": embedder.model_name,
                "description": embedder.description,
                "score_mode": args.score_mode,
            },
            "failure_report": {
                "path": "failure_cases.csv",
                "case_count": len(failure_rows),
            },
        },
    )
    write_summary_csv(output_dir / "summary.csv", summary_rows)
    write_jsonl(output_dir / "case_results.jsonl", all_case_rows)
    write_candidates_csv(output_dir / "candidates.csv", all_candidate_rows)
    write_failure_csv(output_dir / "failure_cases.csv", failure_rows)
    if final_matching.get("summary"):
        write_json(output_dir / "final_matching_summary.json", final_matching["summary"])
        write_jsonl(output_dir / "final_matching_case_results.jsonl", final_matching["case_rows"])

    print(f"Embedding: {embedder.description} / score_mode={args.score_mode}")
    print_summary(summary_rows, args.top_k)
    if final_matching.get("summary"):
        print_final_matching_summary(final_matching["summary"])
    print(f"\n결과 저장: {output_dir}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="문진톡톡 IR 후보 검색 및 Pro linker 성능 평가")
    parser.add_argument("--input", type=Path, required=True, help="평가 JSONL 또는 JSON 배열 파일")
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation/ir/outputs"), help="결과 저장 폴더")
    parser.add_argument(
        "--top-k",
        type=int,
        default=20,
        help="평가할 top-k 후보 수. 기본값 20은 현재 MVP 채택안(G안)의 기준값",
    )
    parser.add_argument("--limit", type=int, default=0, help="앞에서부터 N개 case만 평가. 0이면 전체 평가")
    parser.add_argument(
        "--variants",
        default="",
        help="평가할 variant 목록. 예: A,B,C 또는 G. 비우면 G안을 기본 실행",
    )
    parser.add_argument(
        "--skip-llm-judge",
        action="store_true",
        help="LLM linker를 건너뛰고 IR 후보군만 빠르게 확인. variants를 비우면 C안만 평가",
    )
    parser.add_argument(
        "--use-slot-hint",
        action="store_true",
        help="평가 시 slot_ref를 preferred hint로 사용. 순수 query 비교가 목적이면 기본값(false) 유지",
    )
    parser.add_argument(
        "--include-non-active-spans",
        action="store_true",
        help="status=없음/호전 span도 검색에 넣어 false-positive 여부를 점검",
    )
    parser.add_argument(
        "--embedding-provider",
        choices=["bedrock-titan", "sentence-transformers"],
        default="bedrock-titan",
        help="vector 검색에 사용할 embedding provider. 기본값은 운영과 같은 Bedrock Titan",
    )
    parser.add_argument(
        "--embedding-model",
        default="",
        help="sentence-transformers 모델명. 예: BAAI/bge-m3, intfloat/multilingual-e5-base",
    )
    parser.add_argument(
        "--embedding-device",
        default="auto",
        help="sentence-transformers 실행 장치. auto, cpu, cuda 중 하나를 주로 사용",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=8,
        help="로컬 embedding 모델 batch size. GPU 4GB 환경은 1~4부터 권장",
    )
    parser.add_argument(
        "--embedding-cache-dir",
        type=Path,
        default=PROJECT_ROOT / "evaluation" / "ir" / "cache" / "embeddings",
        help="로컬 문서 embedding cache 저장 폴더",
    )
    parser.add_argument(
        "--score-mode",
        choices=["hybrid", "rrf-hybrid", "quota-rrf", "vector-only"],
        default="rrf-hybrid",
        help="hybrid는 BM25+vector+label 점수합, rrf-hybrid는 순위 융합(MVP 채택), quota-rrf는 신호별 후보 보존, vector-only는 embedding 단독 비교",
    )
    return parser.parse_args()


def parse_requested_variants(args: argparse.Namespace) -> list[str]:
    """명령행에서 지정한 variant를 검증하고 실행 순서를 결정합니다."""
    if args.variants.strip():
        variants = [item.strip().upper() for item in args.variants.split(",") if item.strip()]
    elif args.skip_llm_judge:
        variants = ["C"]
    else:
        variants = ["G"]

    unknown = [variant for variant in variants if variant not in VARIANTS]
    if unknown:
        allowed = ", ".join(VARIANTS)
        raise SystemExit(f"지원하지 않는 variant입니다: {unknown}. 사용 가능: {allowed}")
    if args.skip_llm_judge and any(variant in LLM_LINKER_VARIANTS for variant in variants):
        raise SystemExit("--skip-llm-judge와 D/F/G variant는 함께 사용할 수 없습니다.")
    return variants


def load_cases(path: Path) -> list[dict[str, Any]]:
    """JSONL, JSON 배열, {"data": [...]} 래퍼 파일을 모두 지원합니다."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("[") or text.startswith("{"):
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"]
        return []
    rows = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} JSON 파싱 실패: {exc}") from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


def evaluate_case(
    case: dict[str, Any],
    variant: str,
    top_k: int,
    use_slot_hint: bool,
    include_non_active_spans: bool,
    embedder: Any,
    score_mode: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """하나의 case를 variant 방식으로 평가합니다."""
    spans = oracle_case_spans(case) if variant == "O" else normalize_case_spans(case)
    candidate_rows: list[dict[str, Any]] = []
    candidate_pool_merged: dict[str, dict[str, Any]] = {}
    merged_candidates: dict[str, dict[str, Any]] = {}
    queries_used: list[str] = []
    skipped_span_count = 0
    active_span_count = 0
    span_names: list[str] = []
    span_statuses: list[str] = []
    span_types: list[str] = []
    linker_used_count = 0
    linker_no_match_count = 0
    linker_invalid_count = 0
    linker_selected_slot_ids: list[str] = []

    for span_idx, span in enumerate(spans):
        if not include_non_active_spans and is_non_active_symptom_state(span):
            skipped_span_count += 1
            continue
        query = build_query(case, span, variant)
        if not query:
            continue
        active_span_count += 1
        queries_used.append(query)
        span_names.append(str(span.get("name") or ""))
        span_statuses.append(str(span.get("status") or ""))
        span_types.append(str(span.get("type") or ""))
        retrieval_top_k = max(top_k, GATE_RETRIEVAL_TOP_K) if variant in {"E", "F"} else top_k
        candidates = retrieve_by_query(
            query=query,
            top_k=retrieval_top_k,
            preferred_slot_id=span.get("slot_ref", "") if use_slot_hint else "",
            preferred_texts=[span.get("name", ""), span.get("normalized_text", ""), span.get("source_quote", "")],
            embedder=embedder,
            score_mode=score_mode,
        )
        for pool_rank, cand in enumerate(candidates[:top_k], start=1):
            merge_candidate(candidate_pool_merged, cand, pool_rank)
        if variant in {"E", "F"}:
            candidates = apply_deterministic_gate(
                span,
                candidates,
                query,
                top_k,
                allow_semantic_review=variant == "F",
            )
        if variant == "D":
            selected_names = judge_top_candidates(case, span, candidates, top_k)
            candidates = [cand for cand in candidates if cand["display_text"] in selected_names]
        elif variant == "F":
            selected_names = judge_top_candidates(case, span, candidates, top_k)
            candidates = [cand for cand in candidates if cand["display_text"] in selected_names]

        linker_result: dict[str, Any] | None = None
        selected_slot_ids: set[str] = set()

        if variant in TOP_K_LINKER_VARIANTS:
            linker_result = link_top_candidates(case, span, candidates, top_k)
            linker_used_count += 1

        if linker_result is not None:
            selected_slot_ids = set(linker_result["selected_slot_ids"])
            linker_selected_slot_ids.extend(linker_result["selected_slot_ids"])
            if not selected_slot_ids:
                linker_no_match_count += 1
            if linker_result.get("invalid_selection"):
                linker_invalid_count += 1

        for rank, cand in enumerate(candidates[:top_k], start=1):
            linker_decision = ""
            linker_reason = ""
            linker_selected = ""
            linker_scope = ""
            if linker_result is not None:
                linker_decision = str(linker_result.get("decision") or "")
                linker_reason = str(linker_result.get("reason") or "")
                linker_selected = "true" if cand.get("slot_id") in selected_slot_ids else "false"
                linker_scope = str(linker_result.get("scope") or "")
            row = {
                "variant": variant,
                "case_id": case.get("case_id", ""),
                "span_index": span_idx,
                "query": query,
                "rank": rank,
                "candidate": cand.get("display_text"),
                "slot_id": cand.get("slot_id"),
                "rank_score": cand.get("rank_score"),
                "bm25_score": cand.get("bm25_score"),
                "vector_score": cand.get("vector_score"),
                "label_score": cand.get("label_score"),
                "retrieval_branch": cand.get("retrieval_branch"),
                "embedding_provider": embedder.provider_name,
                "embedding_model": embedder.model_name,
                "score_mode": score_mode,
                "gate_decision": cand.get("gate_decision", ""),
                "gate_reason": cand.get("gate_reason", ""),
                "gate_support_score": cand.get("gate_support_score", ""),
                "gate_specificity_score": cand.get("gate_specificity_score", ""),
                "linker_decision": linker_decision,
                "linker_reason": linker_reason,
                "linker_selected": linker_selected,
                "linker_scope": linker_scope,
            }
            candidate_rows.append(row)
            if variant != "G" or cand.get("slot_id") in selected_slot_ids:
                merge_candidate(merged_candidates, cand, rank)

    candidate_pool_ranked = sorted(
        candidate_pool_merged.values(),
        key=lambda item: (-float(item.get("rank_score") or 0), int(item.get("best_rank") or 999)),
    )[:top_k]
    candidate_pool_names = [item["display_text"] for item in candidate_pool_ranked]
    ranked_predictions = sorted(
        merged_candidates.values(),
        key=lambda item: (-float(item.get("rank_score") or 0), int(item.get("best_rank") or 999)),
    )[:top_k]
    predicted_names = [item["display_text"] for item in ranked_predictions]
    gold = canonical_name_set(case.get("gold_symptoms", []), case.get("gold_slot_ids", []))
    negative = canonical_name_set(case.get("negative_symptoms", []), case.get("negative_slot_ids", []))
    metric_values: dict[str, Any] = {}
    for cutoff in metric_cutoffs(top_k):
        candidate_cutoff = set(candidate_pool_names[:cutoff])
        predicted_cutoff = set(predicted_names[:cutoff])
        metric_values[f"candidate_hit_count@{cutoff}"] = len(candidate_cutoff & gold)
        metric_values[f"candidate_negative_hit_count@{cutoff}"] = len(candidate_cutoff & negative)
        metric_values[f"candidate_hitrate@{cutoff}"] = hitrate_at_k(candidate_pool_names, gold, cutoff)
        metric_values[f"candidate_recall@{cutoff}"] = recall_at_k(candidate_pool_names, gold, cutoff)
        metric_values[f"candidate_mrr@{cutoff}"] = mrr_at_k(candidate_pool_names, gold, cutoff)
        metric_values[f"candidate_ndcg@{cutoff}"] = ndcg_at_k(candidate_pool_names, gold, cutoff)
        metric_values[f"candidate_negative_hit@{cutoff}"] = 1.0 if candidate_cutoff & negative else 0.0
        metric_values[f"hit_count@{cutoff}"] = len(predicted_cutoff & gold)
        metric_values[f"negative_hit_count@{cutoff}"] = len(predicted_cutoff & negative)
        metric_values[f"hitrate@{cutoff}"] = hitrate_at_k(predicted_names, gold, cutoff)
        metric_values[f"recall@{cutoff}"] = recall_at_k(predicted_names, gold, cutoff)
        metric_values[f"mrr@{cutoff}"] = mrr_at_k(predicted_names, gold, cutoff)
        metric_values[f"ndcg@{cutoff}"] = ndcg_at_k(predicted_names, gold, cutoff)
        metric_values[f"negative_hit@{cutoff}"] = 1.0 if predicted_cutoff & negative else 0.0
    final_set_metrics = (
        symptom_set_metrics(predicted_names, gold)
        if linker_used_count > 0
        else empty_symptom_set_metrics()
    )

    return {
        "variant": variant,
        "variant_description": VARIANTS[variant],
        "case_id": case.get("case_id", ""),
        "gold_symptoms": sorted(gold),
        "negative_symptoms": sorted(negative),
        "candidate_pool_top_k": candidate_pool_names,
        "predicted_top_k": predicted_names,
        "queries_used": queries_used,
        "active_span_count": active_span_count,
        "skipped_span_count": skipped_span_count,
        "span_names": span_names,
        "span_statuses": span_statuses,
        "span_types": span_types,
        "linker_used_count": linker_used_count,
        "linker_no_match_count": linker_no_match_count,
        "linker_invalid_count": linker_invalid_count,
        "linker_selected_slot_ids": linker_selected_slot_ids,
        **final_set_metrics,
        **metric_values,
    }, candidate_rows


def normalize_case_spans(case: dict[str, Any]) -> list[dict[str, Any]]:
    """평가 데이터에 spans가 없으면 case 전체를 하나의 span으로 평가합니다."""
    spans = case.get("spans")
    if isinstance(spans, list) and spans:
        return [span for span in spans if isinstance(span, dict)]
    return [{
        "source_quote": case_text(case),
        "normalized_text": case_standard_text(case),
        "name": case.get("llm_symptom_name", ""),
        "status": "있음",
        "type": "symptom",
    }]


def oracle_case_spans(case: dict[str, Any]) -> list[dict[str, Any]]:
    """정답 증상명을 query로 넣어 IR 문서/모델 조합의 상한을 확인합니다.

    이 variant는 실제 서비스에서 사용할 수 없습니다. LLM 추출 결과와 무관하게
    gold label을 직접 넣었을 때도 검색이 실패하는지 확인하는 진단용 평가입니다.
    """
    gold_names = sorted(canonical_name_set(case.get("gold_symptoms", []), case.get("gold_slot_ids", [])))
    if not gold_names:
        return []
    gold_query = " ".join(gold_names)
    return [{
        "source_quote": case_text(case),
        "normalized_text": gold_query,
        "name": gold_query,
        "status": "있음",
        "type": "oracle_gold",
    }]


def build_query(case: dict[str, Any], span: dict[str, Any], variant: str) -> str:
    """멘토링에서 비교하기로 한 query 구성을 생성합니다."""
    source_quote = span.get("source_quote") or case_text(case)
    normalized = span.get("normalized_text") or case_standard_text(case)
    span_name = span.get("name") or case.get("llm_symptom_name") or ""

    if variant == "A":
        parts = [source_quote, normalized, span_name]
    elif variant == "B":
        parts = [normalized]
    elif variant == "C":
        return build_symptom_query(source_quote, normalized, span_name)
    elif variant == "O":
        parts = [normalized, span_name]
    elif variant == "D":
        parts = [normalized]
    elif variant in {"E", "F", "G"}:
        return build_symptom_query(source_quote, normalized, span_name)
    else:
        raise ValueError(f"지원하지 않는 variant: {variant}")
    return normalize_text(" ".join(part for part in parts if part))


def case_text(case: dict[str, Any]) -> str:
    """평가 데이터가 `text`만 가진 단순 형식이어도 IR 평가에 사용할 수 있게 합니다."""
    return str(
        case.get("raw_text")
        or case.get("text")
        or case.get("transcript")
        or case.get("standard_text")
        or ""
    )


def case_standard_text(case: dict[str, Any]) -> str:
    """표준어가 별도로 없으면 입력 문장을 표준어 query로 간주합니다."""
    return str(case.get("standard_text") or case.get("text") or case.get("transcript") or case.get("raw_text") or "")


def positive_rank_map(scores: list[float], candidate_k: int, min_score: float = 0.0) -> dict[int, int]:
    """양수 점수를 가진 문서의 순위를 계산합니다.

    RRF는 점수 크기 자체보다 순위를 합치는 방식이라, BM25/vector/label처럼 스케일이
    다른 검색 신호를 비교적 안정적으로 섞을 수 있습니다.
    """
    ranked = [
        idx
        for idx in sorted(range(len(scores)), key=lambda item: scores[item], reverse=True)
        if scores[idx] > min_score
    ]
    return {idx: rank for rank, idx in enumerate(ranked[:candidate_k], start=1)}


def rrf_component(rank_map: dict[int, int], idx: int, weight: float) -> float:
    """특정 검색 신호에서의 rank를 RRF 점수로 바꿉니다."""
    rank = rank_map.get(idx)
    if not rank:
        return 0.0
    return weight / (RRF_K + rank)


def select_quota_rrf_rows(rows: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """RRF 후보군에서 label/vector/BM25 신호를 일정량씩 보존합니다.

    이 함수는 서비스 코드를 바꾸기 위한 최종 랭킹 로직이 아니라, 평가용 비교 기준입니다.
    기존 RRF가 한 신호에 치우쳐 정답 후보를 top-k 밖으로 밀어내는지 확인하기 위해
    직접 표준명/alias 신호, vector 신호, BM25 신호를 각각 일정 개수씩 먼저 담고
    남은 자리는 RRF 순위로 채웁니다.
    """
    if not rows or top_k <= 0:
        return []

    label_quota = min(top_k, max(2, round(top_k * 0.20)))
    vector_quota = min(top_k, max(4, round(top_k * 0.40)))
    bm25_quota = min(top_k, max(3, round(top_k * 0.30)))

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def take(sorted_rows: list[dict[str, Any]], quota: int, source: str) -> None:
        for row in sorted_rows:
            if len(selected) >= top_k or quota <= 0:
                return
            slot_id = str(row.get("slot_id") or "")
            if not slot_id or slot_id in seen:
                continue
            copied = dict(row)
            copied["retrieval_branch"] = f"quota_{source}:{row.get('retrieval_branch', '')}"
            copied["quota_source"] = source
            selected.append(copied)
            seen.add(slot_id)
            quota -= 1

    label_rows = sorted(
        [row for row in rows if float(row.get("label_score") or 0) >= 0.55],
        key=lambda row: (float(row.get("label_score") or 0), float(row.get("rank_score") or 0)),
        reverse=True,
    )
    vector_rows = sorted(
        [row for row in rows if float(row.get("vector_norm") or 0) > 0],
        key=lambda row: (float(row.get("vector_norm") or 0), float(row.get("rank_score") or 0)),
        reverse=True,
    )
    bm25_rows = sorted(
        [row for row in rows if float(row.get("bm25_score") or 0) > 0],
        key=lambda row: (float(row.get("bm25_score") or 0), float(row.get("rank_score") or 0)),
        reverse=True,
    )
    rrf_rows = sorted(rows, key=lambda row: float(row.get("rank_score") or 0), reverse=True)

    take(label_rows, label_quota, "label")
    take(vector_rows, vector_quota, "vector")
    take(bm25_rows, bm25_quota, "bm25")
    take(rrf_rows, top_k - len(selected), "rrf_fill")

    return selected[:top_k]


def retrieve_by_query(
    query: str,
    top_k: int,
    preferred_slot_id: str = "",
    preferred_texts: list[str] | None = None,
    embedder: Any | None = None,
    score_mode: str = "hybrid",
) -> list[dict[str, Any]]:
    """운영 IR과 같은 문서/점수 함수를 사용하되, query 문자열만 평가 variant별로 바꿉니다."""
    if embedder is None:
        raise ValueError("embedding provider가 필요합니다.")
    docs, bm25 = get_ir_index()
    query = normalize_text(query)
    if not query:
        return []

    preferred_texts = preferred_texts or []
    preferred_name = preferred_canonical_name(preferred_slot_id, *preferred_texts) if preferred_slot_id else ""
    bm25_raw = bm25.scores(query)
    bm25_norm = minmax_norm(bm25_raw)

    q_emb = embedder.embed_text(query)
    doc_embeddings = embedder.get_doc_embeddings(docs) if q_emb is not None else {}
    vector_raw = [0.0] * len(docs)
    if q_emb is not None and doc_embeddings:
        for idx, doc in enumerate(docs):
            vector_raw[idx] = max(0.0, cosine(q_emb, doc_embeddings.get(doc["symptom_id"])))
    vector_norm = minmax_norm(vector_raw)

    candidate_k = max(HYBRID_CANDIDATE_K, top_k * 3, HYBRID_TOP_K)
    bm25_top = set(sorted(range(len(docs)), key=lambda idx: bm25_norm[idx], reverse=True)[:candidate_k])
    vector_top = set(sorted(range(len(docs)), key=lambda idx: vector_norm[idx], reverse=True)[:candidate_k])
    label_scores = []
    for doc in docs:
        label = direct_label_score(query, doc["display_name"])
        if preferred_name and doc["display_name"] == preferred_name:
            label = max(label, 1.0)
        label_scores.append(label)
    label_top = {
        idx
        for idx, score in enumerate(label_scores)
        if score >= 0.55
    }
    if score_mode == "vector-only":
        candidate_ids = vector_top
    else:
        candidate_ids = bm25_top | vector_top | label_top
    intersection_ids = bm25_top & vector_top
    bm25_rank = positive_rank_map(bm25_norm, candidate_k)
    vector_rank = positive_rank_map(vector_norm, candidate_k)
    label_rank = positive_rank_map(label_scores, candidate_k, min_score=0.0)

    rows = []
    for idx in candidate_ids:
        doc = docs[idx]
        label = label_scores[idx]
        preferred_hit = bool(preferred_name and doc["display_name"] == preferred_name)
        if score_mode == "vector-only":
            if vector_norm[idx] <= 0:
                continue
        elif bm25_norm[idx] <= 0 and vector_norm[idx] <= 0 and label <= 0:
            continue
        if score_mode == "vector-only":
            branch = "vector_only"
            rank_score = vector_norm[idx]
        elif score_mode in {"rrf-hybrid", "quota-rrf"}:
            signal_count = int(idx in bm25_rank) + int(idx in vector_rank) + int(idx in label_rank)
            rank_score = (
                rrf_component(bm25_rank, idx, RRF_BM25_WEIGHT)
                + rrf_component(vector_rank, idx, RRF_VECTOR_WEIGHT)
                + rrf_component(label_rank, idx, RRF_LABEL_WEIGHT)
                + RRF_MULTI_SIGNAL_BONUS * max(0, signal_count - 1)
            )
            if preferred_hit:
                rank_score += 0.03
                branch = "rrf_preferred_alias"
            elif idx in bm25_rank and idx in vector_rank and idx in label_rank:
                branch = "rrf_bm25_vector_label"
            elif idx in bm25_rank and idx in vector_rank:
                branch = "rrf_bm25_vector"
            elif idx in label_rank:
                branch = "rrf_label"
            elif idx in vector_rank:
                branch = "rrf_vector"
            else:
                branch = "rrf_bm25"
        else:
            branch = "both" if idx in intersection_ids else ("bm25_only" if idx in bm25_top else "vector_only")
            rank_score = HYBRID_BM25_WEIGHT * bm25_norm[idx] + HYBRID_VECTOR_WEIGHT * vector_norm[idx] + 0.25 * label
            if preferred_hit:
                branch = "preferred_alias"
                rank_score += 0.45
            if branch == "both":
                rank_score += 0.08
        rows.append({
            "slot_id": doc["symptom_id"],
            "display_text": doc["display_name"],
            "rank_score": round(float(rank_score), 4),
            "bm25_score": round(float(bm25_norm[idx]), 4),
            "vector_score": round(float(vector_raw[idx]), 4),
            "vector_norm": round(float(vector_norm[idx]), 4),
            "label_score": round(float(label), 4),
            "retrieval_branch": branch,
            "_doc_text": doc.get("retrieval_text", ""),
            "_bm25_text": doc.get("bm25_text", ""),
        })
    if score_mode == "quota-rrf":
        return select_quota_rrf_rows(rows, top_k)

    rows.sort(key=lambda item: item["rank_score"], reverse=True)
    return rows[:top_k]


def apply_deterministic_gate(
    span: dict[str, Any],
    candidates: list[dict[str, Any]],
    query: str,
    top_k: int,
    allow_semantic_review: bool = False,
) -> list[dict[str, Any]]:
    """IR 후보를 최종 채택하기 전 규칙적으로 정리합니다.

    LLM이 이미 "없음/호전/과거력"으로 분류한 span은 검색 전 단계에서 제외되며,
    여기서는 top-k 후보 중 실제 span 문구와 후보 표준명이 맞는지 다시 확인합니다.
    """
    if not candidates:
        return []

    evidence_text = gate_evidence_text(span, query)
    gated: list[dict[str, Any]] = []

    for cand in candidates:
        rank_score = float(cand.get("rank_score") or 0)
        vector_norm = float(cand.get("vector_norm") or 0)
        support_score = candidate_support_score(evidence_text, cand)
        specificity_score = candidate_specificity_score(str(cand.get("display_text") or ""))
        generic_penalty = 0.10 if is_generic_candidate(cand) else 0.0

        direct_supported = support_score >= GATE_MIN_SUPPORT_SCORE
        strong_hybrid = rank_score >= GATE_MIN_RANK_SCORE and vector_norm >= GATE_MIN_VECTOR_NORM

        reasons = []
        if direct_supported:
            reasons.append("label_alias_supported")
        if direct_supported and strong_hybrid:
            reasons.append("hybrid_threshold")
        elif allow_semantic_review and strong_hybrid:
            reasons.append("semantic_review_required")
        if is_generic_candidate(cand) and support_score < 0.55:
            reasons = [reason for reason in reasons if reason != "hybrid_threshold"]
            if "semantic_review_required" not in reasons:
                reasons.append("generic_label_downranked")

        gate_score = rank_score + (0.28 * support_score) + (0.03 * specificity_score) - generic_penalty
        updated = {
            **cand,
            "rank_score": round(gate_score, 4),
            "gate_support_score": round(support_score, 4),
            "gate_specificity_score": round(specificity_score, 4),
            "gate_reason": ",".join(reasons) if reasons else "rejected_by_gate",
        }
        if reasons and "generic_label_downranked" not in reasons:
            decision = "needs_llm" if "semantic_review_required" in reasons and not direct_supported else "accepted"
            gated.append({**updated, "gate_decision": decision})

    if not gated and candidates:
        backup_candidate = best_threshold_backup(candidates, evidence_text, allow_semantic_review)
        if backup_candidate:
            gated.append(backup_candidate)

    gated.sort(
        key=lambda item: (
            -float(item.get("rank_score") or 0),
            -float(item.get("gate_specificity_score") or 0),
            -float(item.get("gate_support_score") or 0),
        )
    )
    return gated[:top_k]


def gate_evidence_text(span: dict[str, Any], query: str) -> str:
    """후보 검증에 사용할 evidence 문자열을 한 곳에서 구성합니다."""
    parts = [
        span.get("normalized_text", ""),
        span.get("name", ""),
        span.get("source_quote", ""),
        query,
    ]
    return normalize_text(" ".join(str(part) for part in parts if part))


def candidate_support_score(evidence_text: str, candidate: dict[str, Any]) -> float:
    """span evidence가 후보 표준명 또는 표준명에서 파생된 표현을 직접 지지하는 정도입니다."""
    display_name = str(candidate.get("display_text") or "")
    support = direct_label_score(evidence_text, display_name)
    for term in candidate_label_terms(display_name):
        support = max(support, direct_label_score(evidence_text, term))
    return float(support)


def candidate_label_terms(display_name: str) -> list[str]:
    """수작업 alias 표가 아니라 후보 표준명 자체에서만 비교 표현을 파생합니다."""
    normalized = normalize_text(display_name)
    compacted = "".join(KOREAN_TOKEN_RE.findall(normalized))
    terms = {normalized, compacted}
    for token in KOREAN_TOKEN_RE.findall(normalized):
        if len(token) >= 2:
            terms.add(token)
    if "의 " in normalized:
        terms.add(normalized.replace("의 ", " "))
    return [term for term in terms if len(term) >= 2]


def candidate_specificity_score(display_name: str) -> float:
    """짧고 포괄적인 후보보다 세부 후보를 우선하기 위한 일반적 길이 기반 점수입니다."""
    compacted = "".join(KOREAN_TOKEN_RE.findall(normalize_text(display_name)))
    if not compacted:
        return 0.0
    return min(1.0, max(0.0, (len(compacted) - 2) / 8))


def is_generic_candidate(candidate: dict[str, Any]) -> bool:
    """너무 넓은 라벨은 직접 근거가 약할 때 뒤로 미룹니다."""
    display_name = str(candidate.get("display_text") or "")
    return display_name in GATE_GENERIC_LABELS or len("".join(KOREAN_TOKEN_RE.findall(display_name))) <= 2


def best_threshold_backup(
    candidates: list[dict[str, Any]],
    evidence_text: str,
    allow_semantic_review: bool,
) -> dict[str, Any] | None:
    """gate가 너무 엄격해 전부 제거되는 경우, 매우 강한 hybrid 후보 하나만 살립니다."""
    best = max(candidates, key=lambda item: float(item.get("rank_score") or 0))
    rank_score = float(best.get("rank_score") or 0)
    vector_norm = float(best.get("vector_norm") or 0)
    support_score = candidate_support_score(evidence_text, best)
    direct_supported = support_score >= GATE_MIN_SUPPORT_SCORE
    if rank_score < (GATE_MIN_RANK_SCORE + 0.16) or vector_norm < (GATE_MIN_VECTOR_NORM + 0.12):
        return None
    if not direct_supported and not allow_semantic_review:
        return None
    specificity_score = candidate_specificity_score(str(best.get("display_text") or ""))
    reason = "backup_direct_supported" if direct_supported else "backup_semantic_review"
    return {
        **best,
        "gate_decision": "accepted" if direct_supported else "needs_llm",
        "gate_reason": reason,
        "gate_support_score": round(support_score, 4),
        "gate_specificity_score": round(specificity_score, 4),
    }


def judge_top_candidates(case: dict[str, Any], span: dict[str, Any], candidates: list[dict[str, Any]], top_k: int) -> list[str]:
    """D안: 검색 top-k 후보 안에서만 LLM이 최종 증상을 고릅니다."""
    if not candidates:
        return []
    allowed = [cand["display_text"] for cand in candidates[:top_k]]
    prompt = build_llm_judge_prompt(case, span, allowed)
    try:
        from llm import call_bedrock_json_with_meta

        obj, _raw, _meta = call_bedrock_json_with_meta(prompt, REVIEWER_MODEL_ID, 500)
    except Exception as exc:
        print(f"[WARN] LLM judge 실패: {case.get('case_id')} {exc.__class__.__name__}", file=sys.stderr)
        return []

    selected = obj.get("selected_symptoms") if isinstance(obj, dict) else []
    if not isinstance(selected, list):
        return []
    allowed_set = set(allowed)
    return [name for name in selected if isinstance(name, str) and name in allowed_set]


def link_top_candidates(case: dict[str, Any], span: dict[str, Any], candidates: list[dict[str, Any]], top_k: int) -> dict[str, Any]:
    """G안: IR 후보의 slot_id 안에서만 LLM final linker가 최종 표준 증상을 선택합니다.

    기존 D/F안은 후보 이름 목록만 LLM에 전달했습니다. G안은 후보의 `slot_id`, 표준명,
    검색 점수 일부를 함께 전달하고, 응답은 반드시 후보 목록에 존재하는 `slot_id`로만 받습니다.
    validator가 후보 밖 ID를 발견하면 선택 전체를 무효 처리해 hallucination을 막습니다.
    """
    if not candidates:
        return {
            "decision": "no_match",
            "selected_slot_ids": [],
            "reason": "IR 후보가 없습니다.",
            "invalid_selection": False,
            "scope": "top_k",
        }

    candidate_pack = build_linker_candidate_pack(candidates[:top_k])
    prompt = build_final_linker_prompt(case, span, candidate_pack)
    try:
        from llm import call_bedrock_json_with_meta

        obj, _raw, _meta = call_bedrock_json_with_meta(prompt, REVIEWER_MODEL_ID, 700)
    except Exception as exc:
        print(f"[WARN] LLM linker 실패: {case.get('case_id')} {exc.__class__.__name__}", file=sys.stderr)
        return {
            "decision": "no_match",
            "selected_slot_ids": [],
            "reason": f"llm_linker_error:{exc.__class__.__name__}",
            "invalid_selection": False,
            "scope": "top_k",
        }

    result = validate_linker_output(obj, candidate_pack)
    result["scope"] = "top_k"
    return result


def build_linker_candidate_pack(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """LLM linker에 전달할 후보 정보를 최소 단위로 정리합니다.

    후보 문서 전문을 그대로 넣으면 prompt가 길어지고 판단이 흐려질 수 있어, 표준 증상 ID/표준명과
    IR 점수 근거만 전달합니다. 후보 밖 선택은 뒤의 validator가 차단합니다.
    """
    pack: list[dict[str, Any]] = []
    for rank, cand in enumerate(candidates, start=1):
        pack.append({
            "rank": rank,
            "slot_id": cand.get("slot_id", ""),
            "name": cand.get("display_text", ""),
            "rank_score": cand.get("rank_score", ""),
            "bm25_score": cand.get("bm25_score", ""),
            "vector_score": cand.get("vector_score", ""),
            "label_score": cand.get("label_score", ""),
            "retrieval_branch": cand.get("retrieval_branch", ""),
        })
    return pack


def trim_long_text(text: str, limit: int) -> str:
    """LLM prompt가 과도하게 길어지지 않도록 근거 문장을 짧게 자릅니다."""
    text = normalize_text(text)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def validate_linker_output(obj: Any, candidate_pack: list[dict[str, Any]]) -> dict[str, Any]:
    """LLM linker 응답이 후보 목록 안에서만 선택했는지 검증합니다."""
    allowed_ids = {str(item["slot_id"]) for item in candidate_pack if item.get("slot_id")}
    if not isinstance(obj, dict):
        return {
            "decision": "no_match",
            "selected_slot_ids": [],
            "reason": "linker_output_not_json_object",
            "invalid_selection": True,
        }

    selected = obj.get("selected_slot_ids")
    if selected is None:
        selected = obj.get("selected_symptom_ids")
    if not isinstance(selected, list):
        selected = []

    normalized_selected: list[str] = []
    invalid_ids: list[str] = []
    for item in selected:
        slot_id = str(item).strip()
        if not slot_id:
            continue
        if slot_id not in allowed_ids:
            invalid_ids.append(slot_id)
            continue
        if slot_id not in normalized_selected:
            normalized_selected.append(slot_id)

    # 평가 정책: 한 semantic span은 최종적으로 표준 증상 0개 또는 1개에만 연결합니다.
    # 여러 후보를 동시에 고르면 recall은 올라가도 실제 서비스의 "무엇으로 매칭했는가"가
    # 흐려지므로, LLM이 복수 선택을 반환해도 첫 번째 유효 후보만 인정합니다.
    if len(normalized_selected) > 1:
        normalized_selected = normalized_selected[:1]

    reason = str(obj.get("reason") or obj.get("rationale") or "").strip()
    decision = str(obj.get("decision") or "").strip().lower()
    if invalid_ids:
        return {
            "decision": "invalid",
            "selected_slot_ids": [],
            "reason": f"candidate_out_of_scope:{','.join(invalid_ids)}",
            "invalid_selection": True,
        }
    if not normalized_selected:
        return {
            "decision": "no_match",
            "selected_slot_ids": [],
            "reason": reason or "후보 안에서 직접 매칭할 증상이 없다고 판단했습니다.",
            "invalid_selection": False,
        }
    if decision not in {"match", "partial_match"}:
        decision = "match"
    return {
        "decision": decision,
        "selected_slot_ids": normalized_selected,
        "reason": reason,
        "invalid_selection": False,
    }


def build_final_linker_prompt(case: dict[str, Any], span: dict[str, Any], candidate_pack: list[dict[str, Any]]) -> str:
    """IR top-k 후보 안에서만 표준 증상을 고르게 하는 final linker prompt입니다."""
    return f"""
You are a strict Korean clinical symptom linker.
Your task is NOT diagnosis. Your task is entity linking: map one extracted symptom span to exactly zero or one standardized symptom candidate.

Critical rules:
1. You MUST choose only slot_id values from candidate_symptoms.
2. You MUST NOT invent a new symptom name, slot_id, disease, or diagnosis.
3. If the patient text is absent, denied, resolved, improved, only historical, medication-only, or too vague, return no_match with an empty selected_slot_ids list.
4. Prefer the most specific candidate that matches the span meaning.
5. If the span uses lay language, link it to the closest standardized symptom candidate only when the meaning is clinically direct.
6. Select at most one slot_id. If several candidates look possible, choose the single best one.
7. Candidate rank and retrieval scores are only weak retrieval hints. Do not choose by rank or score alone.
8. Examine every candidate_symptoms item, including lower-ranked items, and select the candidate whose name best matches the span meaning.
9. Do not choose a broad candidate when a more specific candidate in the list directly preserves the patient's modifier.
10. Return strict JSON only.

Few-shot examples:
Input span_normalized_text: "다리가 부었습니다"
Input symptom_hint: "다리 붓기"
candidate_symptoms: [
  {{"slot_id": "lower_extremity_edema", "name": "하지부종"}},
  {{"slot_id": "pulmonary_edema", "name": "폐부종"}},
  {{"slot_id": "pain", "name": "통증"}}
]
Output: {{"decision": "match", "selected_slot_ids": ["lower_extremity_edema"], "reason": "다리 붓기는 하지부종과 직접 대응합니다."}}

Input span_normalized_text: "열은 다 내렸고 기침만 조금 남았습니다"
Input symptom_hint: "열"
candidate_symptoms: [
  {{"slot_id": "fever", "name": "발열"}},
  {{"slot_id": "cough", "name": "기침"}}
]
Output: {{"decision": "no_match", "selected_slot_ids": [], "reason": "발열은 호전되어 현재 활성 증상으로 보지 않습니다."}}

Input span_normalized_text: "숨이 차지는 않고 코가 막힙니다"
Input symptom_hint: "코막힘"
candidate_symptoms: [
  {{"slot_id": "dyspnea", "name": "호흡곤란"}},
  {{"slot_id": "nasal_obstruction", "name": "코막힘"}}
]
Output: {{"decision": "match", "selected_slot_ids": ["nasal_obstruction"], "reason": "호흡곤란은 부정되었고 코막힘은 현재 증상입니다."}}

Input span_normalized_text: "누런 가래가 나옵니다"
Input symptom_hint: "누런 가래 또는 객담"
candidate_symptoms: [
  {{"slot_id": "sputum", "name": "가래"}},
  {{"slot_id": "purulent_sputum", "name": "화농성 객담"}}
]
Output: {{"decision": "match", "selected_slot_ids": ["purulent_sputum"], "reason": "누런 가래는 일반 가래보다 화농성 객담에 더 구체적으로 대응합니다."}}

Case:
case_id: {case.get("case_id", "")}
raw_text: {case_text(case)}
standard_text: {case_standard_text(case)}
span_source_quote: {span.get("source_quote", "")}
span_normalized_text: {span.get("normalized_text", "")}
symptom_hint: {span.get("name", "")}
span_status: {span.get("status", "")}
span_type: {span.get("type", "")}
candidate_symptoms: {json.dumps(candidate_pack, ensure_ascii=False)}

Return JSON:
{{
  "decision": "match or no_match",
  "selected_slot_ids": ["zero or one slot_id from candidate_symptoms"],
  "reason": "short Korean reason"
}}
""".strip()


def build_llm_judge_prompt(case: dict[str, Any], span: dict[str, Any], allowed_names: list[str]) -> str:
    """후보 밖 증상을 만들지 못하도록 강하게 제한한 rerank prompt입니다."""
    return f"""
You are evaluating Korean clinical symptom retrieval results.
Your task is NOT diagnosis. Select standardized symptom names that are directly supported by the patient's text.

Rules:
1. Choose only from the provided candidate_names. Do not invent new labels.
2. If the text says the symptom is absent, denied, resolved, improved, or only historical, do not select that symptom.
3. Select zero or more names.
4. Return strict JSON only.

Few-shot examples:
Input standard_text: "열은 다 내렸고 기침만 조금 남았습니다."
candidate_names: ["발열", "기침", "두통"]
Output: {{"selected_symptoms": ["기침"], "reason": "발열은 호전된 상태이고 현재 남은 증상은 기침입니다."}}

Input standard_text: "숨이 차지는 않고 코가 막힙니다."
candidate_names: ["호흡곤란", "코막힘"]
Output: {{"selected_symptoms": ["코막힘"], "reason": "호흡곤란은 부정 표현이고 코막힘은 현재 증상입니다."}}

Case:
case_id: {case.get("case_id", "")}
raw_text: {case_text(case)}
standard_text: {case_standard_text(case)}
span_source_quote: {span.get("source_quote", "")}
span_normalized_text: {span.get("normalized_text", "")}
span_name: {span.get("name", "")}
span_status: {span.get("status", "")}
span_type: {span.get("type", "")}
candidate_names: {json.dumps(allowed_names, ensure_ascii=False)}

Return JSON:
{{
  "selected_symptoms": ["one of candidate_names"],
  "reason": "short Korean reason"
}}
""".strip()


def merge_candidate(merged: dict[str, dict[str, Any]], candidate: dict[str, Any], rank: int) -> None:
    """여러 span에서 나온 같은 후보는 가장 높은 rank_score 기준으로 합칩니다."""
    name = candidate.get("display_text")
    if not name:
        return
    current = merged.get(name)
    score = float(candidate.get("rank_score") or 0)
    if current is None or score > float(current.get("rank_score") or 0):
        merged[name] = {**candidate, "best_rank": rank}


def canonical_name_set(names: list[Any], slot_ids: list[Any] | None = None) -> set[str]:
    """정답 이름/slot_id를 현재 IR 인덱스의 display_name 기준으로 정리합니다."""
    docs, _ = get_ir_index()
    id_to_name = {doc["symptom_id"]: doc["display_name"] for doc in docs}
    valid_names = {doc["display_name"] for doc in docs}
    result = {str(name) for name in names if isinstance(name, str) and str(name) in valid_names}
    for slot_id in slot_ids or []:
        mapped = id_to_name.get(str(slot_id))
        if mapped:
            result.add(mapped)
    return result


def hitrate_at_k(predicted: list[str], gold: set[str], k: int) -> float:
    """정답 증상이 top-k 안에 하나라도 들어왔는지 봅니다."""
    if not gold:
        return 0.0
    return 1.0 if set(predicted[:k]) & gold else 0.0


def recall_at_k(predicted: list[str], gold: set[str], k: int) -> float:
    if not gold:
        return 0.0
    return len(set(predicted[:k]) & gold) / len(gold)


def mrr_at_k(predicted: list[str], gold: set[str], k: int) -> float:
    for idx, name in enumerate(predicted[:k], start=1):
        if name in gold:
            return 1.0 / idx
    return 0.0


def ndcg_at_k(predicted: list[str], gold: set[str], k: int) -> float:
    dcg = 0.0
    for idx, name in enumerate(predicted[:k], start=1):
        if name in gold:
            dcg += 1.0 / math.log2(idx + 1)
    ideal_hits = min(len(gold), k)
    if ideal_hits <= 0:
        return 0.0
    ideal_dcg = sum(1.0 / math.log2(idx + 1) for idx in range(1, ideal_hits + 1))
    return dcg / ideal_dcg if ideal_dcg else 0.0


def symptom_set_metrics(predicted: list[str], gold: set[str]) -> dict[str, Any]:
    """최종 선택 증상 집합을 gold 증상 집합과 비교해 linker용 F1 지표를 계산합니다."""
    predicted_set = set(predicted)
    tp = len(predicted_set & gold)
    fp = len(predicted_set - gold)
    fn = len(gold - predicted_set)
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    return {
        "final_tp": tp,
        "final_fp": fp,
        "final_fn": fn,
        "final_precision": round(precision, 4),
        "final_recall": round(recall, 4),
        "final_f1": round(f1_score(precision, recall), 4),
        "final_exact_match": 1.0 if predicted_set == gold else 0.0,
        "final_false_positive_rate": round(safe_div(fp, tp + fp), 4),
        "final_false_negative_rate": round(safe_div(fn, tp + fn), 4),
    }


def empty_symptom_set_metrics() -> dict[str, Any]:
    """linker를 실행하지 않은 variant에서 F1 지표를 비워 두기 위한 기본값입니다."""
    return {
        "final_tp": 0,
        "final_fp": 0,
        "final_fn": 0,
        "final_precision": 0.0,
        "final_recall": 0.0,
        "final_f1": 0.0,
        "final_exact_match": 0.0,
        "final_false_positive_rate": 0.0,
        "final_false_negative_rate": 0.0,
    }


def summarize_variant(variant: str, rows: list[dict[str, Any]], top_k: int) -> dict[str, Any]:
    count = max(1, len(rows))
    summary = {
        "variant": variant,
        "description": VARIANTS[variant],
        "case_count": len(rows),
    }
    for metric_name in candidate_metric_names(top_k):
        summary[metric_name] = round(sum(float(row.get(metric_name) or 0.0) for row in rows) / count, 4)
    for metric_name in ir_metric_names(top_k):
        summary[metric_name] = round(sum(float(row.get(metric_name) or 0.0) for row in rows) / count, 4)
    total_tp = sum(int(row.get("final_tp") or 0) for row in rows)
    total_fp = sum(int(row.get("final_fp") or 0) for row in rows)
    total_fn = sum(int(row.get("final_fn") or 0) for row in rows)
    final_precision = safe_div(total_tp, total_tp + total_fp)
    final_recall = safe_div(total_tp, total_tp + total_fn)
    summary.update({
        "final_micro_precision": round(final_precision, 4),
        "final_micro_recall": round(final_recall, 4),
        "final_micro_f1": round(f1_score(final_precision, final_recall), 4),
        "final_macro_f1": round(sum(float(row.get("final_f1") or 0.0) for row in rows) / count, 4),
        "final_exact_match_rate": round(sum(float(row.get("final_exact_match") or 0.0) for row in rows) / count, 4),
        "final_false_positive_rate": round(safe_div(total_fp, total_tp + total_fp), 4),
        "final_false_negative_rate": round(safe_div(total_fn, total_tp + total_fn), 4),
        "final_total_tp": total_tp,
        "final_total_fp": total_fp,
        "final_total_fn": total_fn,
    })

    linker_rows = [row for row in rows if int(row.get("linker_used_count") or 0) > 0]
    linker_count = max(1, len(linker_rows))
    linker_tp = sum(int(row.get("final_tp") or 0) for row in linker_rows)
    linker_fp = sum(int(row.get("final_fp") or 0) for row in linker_rows)
    linker_fn = sum(int(row.get("final_fn") or 0) for row in linker_rows)
    linker_precision = safe_div(linker_tp, linker_tp + linker_fp)
    linker_recall = safe_div(linker_tp, linker_tp + linker_fn)
    summary.update({
        "linker_model": REVIEWER_MODEL_ID if linker_rows else "",
        "linker_case_count": len(linker_rows),
        "linker_invocation_count": sum(int(row.get("linker_used_count") or 0) for row in rows),
        "linker_no_match_count": sum(int(row.get("linker_no_match_count") or 0) for row in rows),
        "linker_invalid_count": sum(int(row.get("linker_invalid_count") or 0) for row in rows),
        "linker_micro_precision": round(linker_precision, 4),
        "linker_micro_recall": round(linker_recall, 4),
        "linker_micro_f1": round(f1_score(linker_precision, linker_recall), 4),
        "linker_macro_f1": round(
            sum(float(row.get("final_f1") or 0.0) for row in linker_rows) / linker_count,
            4,
        ) if linker_rows else 0.0,
        "linker_exact_match_rate": round(
            sum(float(row.get("final_exact_match") or 0.0) for row in linker_rows) / linker_count,
            4,
        ) if linker_rows else 0.0,
        "linker_false_positive_rate": round(safe_div(linker_fp, linker_tp + linker_fp), 4),
        "linker_false_negative_rate": round(safe_div(linker_fn, linker_tp + linker_fn), 4),
        "linker_total_tp": linker_tp,
        "linker_total_fp": linker_fp,
        "linker_total_fn": linker_fn,
    })
    return summary


def build_failure_rows(rows: list[dict[str, Any]], failure_k: int = IR_SECONDARY_K) -> list[dict[str, Any]]:
    """실행한 top-k 기준으로 정답 누락/negative hit 케이스를 CSV row로 만듭니다."""
    failure_rows: list[dict[str, Any]] = []
    for row in rows:
        gold = set(row.get("gold_symptoms") or [])
        negative = set(row.get("negative_symptoms") or [])
        predicted = list(row.get("predicted_top_k") or [])
        predicted_set = set(predicted[:failure_k])
        missing = sorted(gold - predicted_set)
        negative_hits = sorted(negative & predicted_set)
        if not missing and not negative_hits:
            continue

        failure_types: list[str] = []
        if not predicted:
            failure_types.append("no_prediction")
        elif missing == sorted(gold):
            failure_types.append("miss_all_gold")
        elif missing:
            failure_types.append("partial_miss")
        if negative_hits:
            failure_types.append("negative_hit")
        if int(row.get("active_span_count") or 0) == 0:
            failure_types.append("no_active_span")
        if row.get("variant") != "O" and not set(row.get("span_names") or []) & gold:
            failure_types.append("extraction_gold_mismatch")

        failure_rows.append({
            "variant": row.get("variant", ""),
            "case_id": row.get("case_id", ""),
            "failure_type": "|".join(failure_types),
            "missing_gold": "; ".join(missing),
            "negative_hits": "; ".join(negative_hits),
            "gold_symptoms": "; ".join(sorted(gold)),
            "evaluated_k": failure_k,
            "predicted_top_k": "; ".join(predicted[:failure_k]),
            "queries_used": " || ".join(row.get("queries_used") or []),
            "span_names": "; ".join(row.get("span_names") or []),
            "span_statuses": "; ".join(row.get("span_statuses") or []),
            "span_types": "; ".join(row.get("span_types") or []),
            "active_span_count": row.get("active_span_count", 0),
            "skipped_span_count": row.get("skipped_span_count", 0),
        })
    return failure_rows


def summarize_final_matching(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """최종 화면에 올라간 증상 집합이 있을 때 Micro/Macro F1을 계산합니다.

    IR 후보 랭킹과 달리 최종 증상 매칭 평가는 "최종 채택된 증상 집합"이 필요합니다.
    평가 데이터에 `final_predicted_symptoms` 또는 `predicted_symptoms` 필드가 있을 때만
    이 요약을 생성합니다.
    """
    case_rows = []
    total_tp = total_fp = total_fn = 0
    for case in cases:
        predicted = final_prediction_set(case)
        if predicted is None:
            continue
        gold = canonical_name_set(case.get("gold_symptoms", []), case.get("gold_slot_ids", []))
        tp = len(predicted & gold)
        fp = len(predicted - gold)
        fn = len(gold - predicted)
        total_tp += tp
        total_fp += fp
        total_fn += fn
        precision = safe_div(tp, tp + fp)
        recall = safe_div(tp, tp + fn)
        case_rows.append({
            "case_id": case.get("case_id", ""),
            "gold_symptoms": sorted(gold),
            "final_predicted_symptoms": sorted(predicted),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1_score(precision, recall), 4),
            "exact_match": 1.0 if predicted == gold else 0.0,
        })

    if not case_rows:
        return {"summary": None, "case_rows": []}

    micro_precision = safe_div(total_tp, total_tp + total_fp)
    micro_recall = safe_div(total_tp, total_tp + total_fn)
    summary = {
        "case_count": len(case_rows),
        "micro_f1": round(f1_score(micro_precision, micro_recall), 4),
        "macro_f1": round(sum(row["f1"] for row in case_rows) / len(case_rows), 4),
        "exact_match_rate": round(sum(row["exact_match"] for row in case_rows) / len(case_rows), 4),
        # 서비스 문맥에서는 "예측으로 올린 증상 중 오답 비율"로 정의합니다.
        # 통계학의 전체 label-space FPR과 구분하기 위해 README에 명시합니다.
        "false_positive_rate": round(safe_div(total_fp, total_tp + total_fp), 4),
        "false_negative_rate": round(safe_div(total_fn, total_tp + total_fn), 4),
        "total_tp": total_tp,
        "total_fp": total_fp,
        "total_fn": total_fn,
    }
    return {"summary": summary, "case_rows": case_rows}


def final_prediction_set(case: dict[str, Any]) -> set[str] | None:
    """평가 JSON에 들어 있는 최종 증상 예측 필드를 표준 증상명 집합으로 정리합니다."""
    for key in ("final_predicted_symptoms", "predicted_symptoms", "matched_symptoms"):
        value = case.get(key)
        if isinstance(value, list):
            return canonical_name_set(value, case.get("final_predicted_slot_ids", []))
    return None


def safe_div(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


def f1_score(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_candidates_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "variant",
        "case_id",
        "span_index",
        "query",
        "rank",
        "candidate",
        "slot_id",
        "rank_score",
        "bm25_score",
        "vector_score",
        "label_score",
        "retrieval_branch",
        "embedding_provider",
        "embedding_model",
        "score_mode",
        "gate_decision",
        "gate_reason",
        "gate_support_score",
        "gate_specificity_score",
        "linker_decision",
        "linker_reason",
        "linker_selected",
        "linker_scope",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_failure_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """정답 누락/negative hit 케이스만 CSV로 저장합니다."""
    fieldnames = [
        "variant",
        "case_id",
        "failure_type",
        "missing_gold",
        "negative_hits",
        "gold_symptoms",
        "evaluated_k",
        "predicted_top_k",
        "queries_used",
        "span_names",
        "span_statuses",
        "span_types",
        "active_span_count",
        "skipped_span_count",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, Any]], top_k: int) -> None:
    print(f"\nIR/linker evaluation summary top_k={top_k}")
    cutoffs = metric_cutoffs(top_k)
    terminal_k = cutoffs[-1]
    for row in rows:
        candidate_parts = [
            f"CandidateRecall@{cutoff}={float(row.get(f'candidate_recall@{cutoff}') or 0):.4f}"
            for cutoff in cutoffs
        ]
        final_parts = [
            f"SelectedRecall@{cutoff}={float(row.get(f'recall@{cutoff}') or 0):.4f}"
            for cutoff in cutoffs
        ]
        ranking_parts = [
            f"CandidateMRR@5={float(row.get(f'candidate_mrr@{IR_SECONDARY_K}') or 0):.4f}",
            f"CandidateNDCG@5={float(row.get(f'candidate_ndcg@{IR_SECONDARY_K}') or 0):.4f}",
            f"CandidateNegativeHit@{terminal_k}={float(row.get(f'candidate_negative_hit@{terminal_k}') or 0):.4f}",
        ]
        linker_parts = []
        if int(row.get("linker_case_count") or 0) > 0:
            linker_parts = [
                f"LinkerMicroF1={float(row.get('linker_micro_f1') or 0):.4f}",
                f"LinkerMacroF1={float(row.get('linker_macro_f1') or 0):.4f}",
                f"LinkerExact={float(row.get('linker_exact_match_rate') or 0):.4f}",
                f"LinkerFPR={float(row.get('linker_false_positive_rate') or 0):.4f}",
                f"LinkerFNR={float(row.get('linker_false_negative_rate') or 0):.4f}",
                f"LinkerModel={row.get('linker_model', '')}",
            ]
        else:
            linker_parts = ["Linker=not_run"]
        print(
            f"- {row['variant']} {row['description']}: "
            + ", ".join(candidate_parts + final_parts + ranking_parts + linker_parts)
        )
    return


def print_final_matching_summary(summary: dict[str, Any]) -> None:
    print("\n최종 증상 매칭 평가")
    print(
        f"- Micro F1={summary['micro_f1']:.4f}, "
        f"Macro F1={summary['macro_f1']:.4f}, "
        f"ExactMatch={summary['exact_match_rate']:.4f}, "
        f"FPR={summary['false_positive_rate']:.4f}, "
        f"FNR={summary['false_negative_rate']:.4f}"
    )


if __name__ == "__main__":
    raise SystemExit(main())

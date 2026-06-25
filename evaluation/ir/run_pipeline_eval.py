#!/usr/bin/env python3
"""대사 기반 end-to-end 문진 파이프라인 평가 도구.

이 스크립트는 평가자가 미리 query term이나 span을 작성하지 않아도 되도록 만든
평가 실행기입니다. 입력 데이터에는 환자 발화와 골든 증상명만 넣고, 실제
백엔드의 LangGraph 노드를 저장 직전 단계까지만 실행합니다.

실행되는 단계:
1. 입력 payload 정리
2. 즉시 위험 표현 감지
3. RAG 참고 문맥 검색
4. Bedrock LLM 의미 추출
5. Pydantic/source_quote validator 및 재시도 loop
6. BM25 + Titan Vector Hybrid IR 매칭

실행하지 않는 단계:
- DynamoDB 저장
- S3 artifact 저장
- 원페이퍼 갱신
- 환자 안내문 생성

따라서 실제 서비스 파이프라인 품질을 보면서도 평가 실행으로 운영 저장소가
오염되지 않습니다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = PROJECT_ROOT / "backend" / "serverless" / "src"
sys.path.insert(0, str(BACKEND_SRC))

try:
    from clinical_state import is_active_symptom_state  # noqa: E402
    from pipeline_nodes import (  # noqa: E402
        hybrid_ir_match_node,
        input_transcript_node,
        quick_safety_flag_node,
        rag_context_retrieval_node,
        schema_quote_validation_node,
        semantic_extraction_node,
    )
    from question_sets import get_question_set  # noqa: E402
    from retrieval_documents import get_ir_index  # noqa: E402
    from settings import EXTRACTION_RETRY_ATTEMPTS  # noqa: E402
    from utils import normalize_visit_type  # noqa: E402
except ModuleNotFoundError as exc:
    raise SystemExit(
        "평가 실행에 필요한 Python 패키지가 없습니다.\n"
        "프로젝트 루트에서 다음 명령을 먼저 실행하세요.\n"
        "  pip install -r evaluation\\ir\\requirements.txt\n"
        f"누락 패키지: {exc.name}"
    ) from exc


DEFAULT_QUESTION_SET_ID = "default"


def main() -> int:
    args = parse_args()
    cases = load_cases(args.input)
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit(f"평가 case가 없습니다: {args.input}")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    case_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    ir_eval_rows: list[dict[str, Any]] = []
    ir_eval_backup_rows: list[dict[str, Any]] = []

    for idx, case in enumerate(cases, start=1):
        result = evaluate_case(case, idx)
        case_row = result["case_row"]
        case_rows.append(case_row)
        prediction_rows.extend(result["prediction_rows"])
        candidate_rows.extend(result["candidate_rows"])
        ir_row = build_ir_eval_case(case, case_row)
        ir_eval_rows.append(ir_row)
        if (ir_row.get("pipeline_meta") or {}).get("backup_span_added"):
            ir_eval_backup_rows.append({
                "case_id": case_row.get("case_id"),
                "reason": (ir_row.get("pipeline_meta") or {}).get("backup_reason"),
                "error": case_row.get("error"),
                "validator_passed": case_row.get("validator_passed"),
            })
        print_progress(case_row)

    summary = summarize_cases(case_rows)
    write_json(args.output_dir / "pipeline_summary.json", summary)
    write_jsonl(args.output_dir / "pipeline_case_results.jsonl", case_rows)
    write_predictions_csv(args.output_dir / "pipeline_predictions.csv", prediction_rows)
    write_candidates_csv(args.output_dir / "pipeline_candidates.csv", candidate_rows)
    write_jsonl(args.output_dir / "pipeline_ir_eval_cases.jsonl", ir_eval_rows)

    diagnostic_rows = build_diagnostic_rows(case_rows)
    span_diagnostic_rows = build_span_diagnostic_rows(case_rows)
    failure_rows = [row for row in diagnostic_rows if row["failure_type"] != "ok"]
    stage_summary = summarize_pipeline_stages(case_rows, diagnostic_rows)
    write_json(args.output_dir / "pipeline_stage_summary.json", stage_summary)
    write_diagnostics_csv(args.output_dir / "pipeline_diagnostics.csv", diagnostic_rows)
    write_span_diagnostics_csv(args.output_dir / "pipeline_span_diagnostics.csv", span_diagnostic_rows)
    write_failure_cases_csv(args.output_dir / "pipeline_failure_cases.csv", failure_rows)

    write_json(
        args.output_dir / "pipeline_ir_eval_manifest.json",
        {
            "source_input": str(args.input),
            "total_cases": len(case_rows),
            "exported_cases": len(ir_eval_rows),
            "backup_query_cases": len(ir_eval_backup_rows),
            "backup_query_rows": ir_eval_backup_rows,
            "purpose": (
                "run_ir_eval.py 입력으로 쓰기 위한 파일입니다. "
                "Bedrock extraction이 생성한 active symptom span을 우선 사용하되, "
                "span 추출 실패 case도 제외하지 않도록 표준화 문장 기반 보조 query span을 추가합니다."
            ),
        },
    )

    print("\n실제 파이프라인 평가 요약")
    print(
        f"- cases={summary['case_count']}, "
        f"MicroF1={summary['micro_f1']:.4f}, "
        f"MacroF1={summary['macro_f1']:.4f}, "
        f"ExactMatch={summary['exact_match_rate']:.4f}, "
        f"FPR={summary['false_positive_rate']:.4f}, "
        f"FNR={summary['false_negative_rate']:.4f}, "
        f"ValidatorPass={summary['validator_pass_rate']:.4f}, "
        f"ErrorRate={summary['error_rate']:.4f}"
    )
    print(
        "- IR query 평가 데이터: "
        f"{args.output_dir / 'pipeline_ir_eval_cases.jsonl'} "
        f"(exported={len(ir_eval_rows)}, backup={len(ir_eval_backup_rows)})"
    )
    print(f"결과 저장: {args.output_dir}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="대사 + 골든 정답 기반 실제 문진 파이프라인 평가")
    parser.add_argument("--input", type=Path, required=True, help="평가 JSONL 또는 JSON 배열 파일")
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation/ir/outputs"), help="결과 저장 폴더")
    parser.add_argument("--limit", type=int, default=0, help="앞에서 N개 case만 실행. 0이면 전체 실행")
    return parser.parse_args()


def load_cases(path: Path) -> list[dict[str, Any]]:
    """JSONL, JSON 배열, {"data": [...]} 래퍼 파일을 모두 읽습니다."""
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

    rows: list[dict[str, Any]] = []
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


def evaluate_case(case: dict[str, Any], row_index: int) -> dict[str, Any]:
    """한 줄의 평가 데이터를 실제 저장 전 파이프라인으로 실행합니다."""
    case_id = str(case.get("case_id") or f"case_{row_index:03d}")
    transcript = transcript_text(case)
    visit_type = normalize_visit_type(case.get("visit_type") or case.get("visitType") or "initial")
    question_id = str(case.get("question_id") or case.get("questionId") or default_question_id(visit_type))
    question_set_id = str(case.get("question_set_id") or case.get("questionSetId") or DEFAULT_QUESTION_SET_ID)
    question_type = resolve_question_type(visit_type, question_id, question_set_id)

    body = {
        "session_id": f"eval_{case_id}",
        "question_id": question_id,
        "question_type": question_type,
        "question_set_id": question_set_id,
        "visit_type": visit_type,
        "transcript": transcript,
    }
    state: dict[str, Any] = {"body": body, "trace": [], "active_path": []}

    for node in (input_transcript_node, quick_safety_flag_node, rag_context_retrieval_node):
        state.update(node(state))
        if state.get("error_response"):
            return build_case_result(case, case_id, state)

    max_attempts = max(1, int(EXTRACTION_RETRY_ATTEMPTS or 1))
    for _ in range(max_attempts):
        state.update(semantic_extraction_node(state))
        state.update(schema_quote_validation_node(state))
        if not state.get("retry_extraction"):
            break

    if not state.get("error_response") and not state.get("safety_only"):
        state.update(hybrid_ir_match_node(state))

    return build_case_result(case, case_id, state)


def transcript_text(case: dict[str, Any]) -> str:
    """평가자가 가장 단순하게 `text`만 넣어도 실행되도록 입력 별칭을 허용합니다."""
    return str(
        case.get("text")
        or case.get("transcript")
        or case.get("standard_text")
        or case.get("raw_text")
        or ""
    ).strip()


def pipeline_standard_text(case: dict[str, Any], extracted: dict[str, Any], state: dict[str, Any]) -> str:
    """IR 보조 query에 쓸 표준화 문장을 안전하게 꺼냅니다.

    역할 분리 파이프라인이 정상 통과하면 `structured.standardized_text`에
    방언/구어체가 정리된 문장이 들어옵니다. validator 실패나 LLM 오류로 이 값이
    비어도 평가 case를 버리지 않기 위해 원 입력 문장을 마지막 보조 입력으로 씁니다.
    """
    structured = extracted.get("structured") if isinstance(extracted, dict) else {}
    raw = state.get("extraction_raw") if isinstance(state, dict) else {}
    raw_structured = raw.get("structured") if isinstance(raw, dict) else {}
    return str(
        (structured or {}).get("standardized_text")
        or (raw_structured or {}).get("standardized_text")
        or case.get("standard_text")
        or case.get("standardized_text")
        or transcript_text(case)
    ).strip()


def default_question_id(visit_type: str) -> str:
    """방문 유형만 있을 때 증상 IR이 도는 대표 문항을 선택합니다."""
    return "Q3" if normalize_visit_type(visit_type) == "followup" else "Q1"


def resolve_question_type(visit_type: str, question_id: str, question_set_id: str) -> str:
    """질문 세트에서 question_type을 찾아 실제 백엔드 payload와 같게 만듭니다."""
    question_set = get_question_set(question_set_id)
    questions = ((question_set or {}).get("visits") or {}).get(visit_type) or []
    for question in questions:
        if str(question.get("id") or "") == str(question_id):
            return str(question.get("question_type") or "")
    raise ValueError(f"질문 세트에서 문항을 찾지 못했습니다: visit_type={visit_type}, question_id={question_id}")


def build_case_result(case: dict[str, Any], case_id: str, state: dict[str, Any]) -> dict[str, Any]:
    """파이프라인 상태를 평가용 row와 CSV row로 변환합니다."""
    matched_slots = (state.get("matched") or {}).get("matched_slots") or []
    predicted = canonical_name_set([slot.get("name") for slot in matched_slots])
    gold = canonical_name_set(case.get("gold_symptoms") or [], case.get("gold_slot_ids") or [])
    negative = canonical_name_set(case.get("negative_symptoms") or [], case.get("negative_slot_ids") or [])
    tp = len(predicted & gold)
    fp = len(predicted - gold)
    fn = len(gold - predicted)
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = f1_score(precision, recall)
    trace = state.get("trace") or []
    extracted = state.get("extracted") or {}
    validation_errors = extraction_validation_errors(state, extracted)

    case_row = {
        "case_id": case_id,
        "visit_type": state.get("visit_type"),
        "question_id": state.get("question_id"),
        "question_type": state.get("question_type"),
        "text": transcript_text(case),
        "standard_text": pipeline_standard_text(case, extracted, state),
        "gold_symptoms": sorted(gold),
        "negative_symptoms": sorted(negative),
        "predicted_symptoms": sorted(predicted),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "exact_match": 1.0 if predicted == gold else 0.0,
        "negative_hit": 1.0 if predicted & negative else 0.0,
        "validator_passed": bool(extracted.get("validator_passed")),
        "extraction_attempts": int((extracted.get("llm_meta") or {}).get("attempts") or state.get("extraction_attempt") or 0),
        "validation_errors": validation_errors,
        "validation_error_count": len(validation_errors),
        "error": response_error_code(state),
        "semantic_failed": bool(state.get("semantic_failed")),
        "safety_only": bool(state.get("safety_only")),
        "active_path": [entry.get("node") for entry in trace],
        "trace_statuses": [f"{entry.get('node')}:{entry.get('status')}" for entry in trace if entry.get("node")],
        "spans": extracted.get("spans") or [],
        "matched_slots": matched_slots,
        "unmatched_spans": (state.get("matched") or {}).get("unmatched_spans") or [],
    }

    prediction_rows = [
        {
            "case_id": case_id,
            "slot_id": slot.get("slot_id"),
            "name": slot.get("name"),
            "status": slot.get("status"),
            "source_quote": slot.get("source_quote"),
            "normalized_text": slot.get("normalized_text"),
            "rank_score": (slot.get("ir_trace") or {}).get("rank_score"),
            "bm25_score": (slot.get("ir_trace") or {}).get("bm25_score"),
            "vector_score": (slot.get("ir_trace") or {}).get("vector_score"),
            "label_score": (slot.get("ir_trace") or {}).get("label_score"),
            "accept_reason": (slot.get("ir_trace") or {}).get("accept_reason"),
        }
        for slot in matched_slots
    ]
    candidate_rows = top_candidate_rows(case_id, matched_slots)
    return {
        "case_row": case_row,
        "prediction_rows": prediction_rows,
        "candidate_rows": candidate_rows,
    }


def build_ir_eval_case(source_case: dict[str, Any], case_row: dict[str, Any]) -> dict[str, Any]:
    """pipeline 결과를 run_ir_eval.py가 읽을 수 있는 입력 row로 변환합니다.

    원본 평가셋에는 환자 발화와 골든 정답만 있습니다. A/B/C query 전략을 제대로 비교하려면
    Bedrock extraction이 만든 source_quote, normalized_text, LLM 증상명이 필요하므로,
    pipeline 평가 직후 별도 JSONL로 저장합니다. 이 파일은 IR 평가 입력일 뿐 운영 저장소에는 쓰지 않습니다.
    """
    text = str(case_row.get("text") or transcript_text(source_case)).strip()
    standard_text = str(case_row.get("standard_text") or source_case.get("standard_text") or text).strip()
    spans = compact_spans_for_ir(case_row.get("spans") or [])
    backup_reason = ""
    if not has_active_ir_span(spans):
        backup_reason = "no_active_pipeline_span_standard_text_query"
        spans = [backup_span_for_ir(text, standard_text, backup_reason)]

    return {
        "case_id": case_row.get("case_id") or source_case.get("case_id"),
        "visit_type": case_row.get("visit_type") or source_case.get("visit_type"),
        "dialect_type": source_case.get("dialect_type") or source_case.get("dialectType") or "",
        "question_id": case_row.get("question_id") or source_case.get("question_id"),
        "question_type": case_row.get("question_type"),
        "text": text,
        "standard_text": standard_text,
        "gold_symptoms": case_row.get("gold_symptoms") or [],
        "negative_symptoms": case_row.get("negative_symptoms") or [],
        "spans": spans,
        "pipeline_meta": {
            "validator_passed": bool(case_row.get("validator_passed")),
            "extraction_attempts": int(case_row.get("extraction_attempts") or 0),
            "error": case_row.get("error") or "",
            "predicted_symptoms": case_row.get("predicted_symptoms") or [],
            "backup_span_added": bool(backup_reason),
            "backup_reason": backup_reason,
        },
    }


def compact_spans_for_ir(spans: list[Any]) -> list[dict[str, Any]]:
    """IR query 생성에 필요한 span 필드만 보존합니다."""
    compacted: list[dict[str, Any]] = []
    for span in spans:
        if not isinstance(span, dict):
            continue
        source_quote = str(span.get("source_quote") or "").strip()
        normalized_text = str(span.get("normalized_text") or "").strip()
        name = str(span.get("name") or "").strip()
        if not (source_quote or normalized_text or name):
            continue
        compacted.append({
            "source_quote": source_quote,
            "normalized_text": normalized_text,
            "name": name,
            "status": span.get("status") or "있음",
            "type": span.get("type") or "symptom",
            "slot_ref": span.get("slot_ref") or "",
        })
    return compacted


def has_active_ir_span(spans: list[dict[str, Any]]) -> bool:
    """run_ir_eval.py 기본 설정에서 실제 검색 query로 쓰일 span이 있는지 확인합니다."""
    return any(is_active_symptom_state(span) for span in spans)


def backup_span_for_ir(source_text: str, standard_text: str, reason: str) -> dict[str, Any]:
    """추출 실패 case도 IR/linker 평가에서 제외하지 않기 위한 최소 span입니다.

    `name`을 비워 두면 C/G variant에서 query가 `normalized_text` 중심으로만
    생성됩니다. 즉 LLM이 만든 증상명 힌트가 없어도 표준화 문장만으로 top-k 후보를
    검색하고, 이후 linker가 그 후보 중 하나를 선택할 수 있습니다.
    """
    query_text = standard_text or source_text
    return {
        "source_quote": source_text,
        "normalized_text": query_text,
        "name": "",
        "status": "있음",
        "type": "symptom",
        "slot_ref": "",
        "backup_query": True,
        "backup_reason": reason,
    }


def top_candidate_rows(case_id: str, matched_slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """운영 matched slot에 들어 있는 IR 후보 trace를 CSV용으로 펼칩니다."""
    rows: list[dict[str, Any]] = []
    for slot in matched_slots:
        ir_trace = slot.get("ir_trace") or {}
        for rank, cand in enumerate(ir_trace.get("top_candidates") or [], start=1):
            rows.append(
                {
                    "case_id": case_id,
                    "accepted_name": slot.get("name"),
                    "query": ir_trace.get("query"),
                    "rank": rank,
                    "candidate": cand.get("name"),
                    "slot_id": cand.get("slot_id"),
                    "score": cand.get("score"),
                    "rank_score": cand.get("rank_score"),
                    "bm25_score": cand.get("bm25_score"),
                    "vector_score": cand.get("vector_score"),
                }
            )
    return rows


def response_error_code(state: dict[str, Any]) -> str:
    """HTTP response 객체에서 평가 표시에 필요한 오류 코드만 꺼냅니다."""
    error_response = state.get("error_response")
    if not error_response:
        return ""
    try:
        body = json.loads(error_response.get("body") or "{}")
    except Exception:
        return "unknown_error"
    return str(body.get("error") or "unknown_error")


def extraction_validation_errors(state: dict[str, Any], extracted: dict[str, Any]) -> list[Any]:
    """schema/source_quote 검증 실패 이유를 평가 파일에 남깁니다.

    운영 저장 데이터가 아니라 평가용 진단 정보입니다. 실패 케이스에서
    "LLM이 JSON 자체를 못 맞춘 것인지", "quote grounding이 깨진 것인지"를
    바로 확인하기 위해 별도 컬럼과 JSON에 보존합니다.
    """
    llm_meta = extracted.get("llm_meta") if isinstance(extracted, dict) else {}
    meta_errors = (llm_meta or {}).get("validation_errors") or []
    state_errors = state.get("extraction_validation_errors") or []
    if meta_errors:
        return meta_errors
    return state_errors


def canonical_name_set(names: list[Any], slot_ids: list[Any] | None = None) -> set[str]:
    """평가 정답/예측을 현재 IR 인덱스의 표준 증상명 기준으로 정규화합니다."""
    docs, _ = get_ir_index()
    id_to_name = {doc["symptom_id"]: doc["display_name"] for doc in docs}
    valid_names = {doc["display_name"] for doc in docs}
    result = {str(name) for name in names if isinstance(name, str) and str(name) in valid_names}
    for slot_id in slot_ids or []:
        mapped = id_to_name.get(str(slot_id))
        if mapped:
            result.add(mapped)
    return result


def summarize_cases(case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """최종 채택 증상 기준 Micro/Macro F1과 오류율을 계산합니다."""
    total_tp = sum(int(row["tp"]) for row in case_rows)
    total_fp = sum(int(row["fp"]) for row in case_rows)
    total_fn = sum(int(row["fn"]) for row in case_rows)
    micro_precision = safe_div(total_tp, total_tp + total_fp)
    micro_recall = safe_div(total_tp, total_tp + total_fn)
    count = max(1, len(case_rows))
    return {
        "case_count": len(case_rows),
        "micro_f1": round(f1_score(micro_precision, micro_recall), 4),
        "macro_f1": round(sum(float(row["f1"]) for row in case_rows) / count, 4),
        "exact_match_rate": round(sum(float(row["exact_match"]) for row in case_rows) / count, 4),
        "false_positive_rate": round(safe_div(total_fp, total_tp + total_fp), 4),
        "false_negative_rate": round(safe_div(total_fn, total_tp + total_fn), 4),
        "negative_hit_rate": round(sum(float(row["negative_hit"]) for row in case_rows) / count, 4),
        "validator_pass_rate": round(sum(1 for row in case_rows if row["validator_passed"]) / count, 4),
        "error_rate": round(sum(1 for row in case_rows if row["error"]) / count, 4),
        "avg_extraction_attempts": round(
            sum(int(row["extraction_attempts"]) for row in case_rows) / count,
            3,
        ),
        "total_tp": total_tp,
        "total_fp": total_fp,
        "total_fn": total_fn,
    }


def summarize_pipeline_stages(case_rows: list[dict[str, Any]], diagnostic_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """최종 F1 전에 어느 단계에서 손실이 생겼는지 요약합니다."""
    count = max(1, len(case_rows))
    span_counts = [len(row.get("spans") or []) for row in case_rows]
    active_counts = [len(active_spans(row.get("spans") or [])) for row in case_rows]
    matched_counts = [len(row.get("matched_slots") or []) for row in case_rows]
    failure_counter = Counter(row.get("failure_type") or "unknown" for row in diagnostic_rows)
    error_counter = Counter(row.get("error") or "none" for row in case_rows)
    status_counter: Counter[str] = Counter()
    type_counter: Counter[str] = Counter()
    for row in case_rows:
        for span in row.get("spans") or []:
            status_counter[str((span or {}).get("status") or "empty")] += 1
            type_counter[str((span or {}).get("type") or "empty")] += 1

    return {
        "case_count": len(case_rows),
        "validator_pass_rate": round(sum(1 for row in case_rows if row.get("validator_passed")) / count, 4),
        "pipeline_error_rate": round(sum(1 for row in case_rows if row.get("error")) / count, 4),
        "span_extracted_case_rate": round(sum(1 for n in span_counts if n > 0) / count, 4),
        "active_span_case_rate": round(sum(1 for n in active_counts if n > 0) / count, 4),
        "matched_case_rate": round(sum(1 for n in matched_counts if n > 0) / count, 4),
        "avg_span_count": round(sum(span_counts) / count, 3),
        "avg_active_span_count": round(sum(active_counts) / count, 3),
        "avg_matched_slot_count": round(sum(matched_counts) / count, 3),
        "failure_type_counts": dict(sorted(failure_counter.items())),
        "error_code_counts": dict(sorted(error_counter.items())),
        "span_status_counts": dict(sorted(status_counter.items())),
        "span_type_counts": dict(sorted(type_counter.items())),
    }


def build_diagnostic_rows(case_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """케이스별로 실패 지점을 한 줄로 볼 수 있게 만듭니다."""
    rows: list[dict[str, Any]] = []
    for row in case_rows:
        gold = set(row.get("gold_symptoms") or [])
        predicted = set(row.get("predicted_symptoms") or [])
        negative = set(row.get("negative_symptoms") or [])
        spans = row.get("spans") or []
        active = active_spans(spans)
        matched_slots = row.get("matched_slots") or []
        missing_gold = sorted(gold - predicted)
        extra_predicted = sorted(predicted - gold)
        negative_hits = sorted(predicted & negative)
        failure_type = classify_failure(row, active, missing_gold, extra_predicted, negative_hits)
        rows.append({
            "case_id": row.get("case_id"),
            "visit_type": row.get("visit_type"),
            "question_id": row.get("question_id"),
            "question_type": row.get("question_type"),
            "failure_type": failure_type,
            "error": row.get("error") or "",
            "validator_passed": bool(row.get("validator_passed")),
            "validation_error_count": int(row.get("validation_error_count") or 0),
            "validation_error_summary": summarize_validation_errors(row.get("validation_errors") or []),
            "extraction_attempts": int(row.get("extraction_attempts") or 0),
            "span_count": len(spans),
            "active_span_count": len(active),
            "matched_count": len(matched_slots),
            "unmatched_count": len(row.get("unmatched_spans") or []),
            "precision": row.get("precision"),
            "recall": row.get("recall"),
            "f1": row.get("f1"),
            "exact_match": row.get("exact_match"),
            "negative_hit": row.get("negative_hit"),
            "gold_symptoms": join_list(sorted(gold)),
            "predicted_symptoms": join_list(sorted(predicted)),
            "missing_gold": join_list(missing_gold),
            "extra_predicted": join_list(extra_predicted),
            "negative_hits": join_list(negative_hits),
            "span_names": join_list(span_names(spans)),
            "active_span_names": join_list(span_names(active)),
            "span_statuses": join_list([str(span.get("status") or "") for span in spans if isinstance(span, dict)]),
            "span_types": join_list([str(span.get("type") or "") for span in spans if isinstance(span, dict)]),
            "active_quotes": join_list([str(span.get("source_quote") or "") for span in active if isinstance(span, dict)]),
            "trace_statuses": join_list(row.get("trace_statuses") or []),
            "text": row.get("text") or "",
        })
    return rows


def build_span_diagnostic_rows(case_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """LLM이 만든 span 단위로 status/type/source_quote를 점검하는 표입니다."""
    rows: list[dict[str, Any]] = []
    for row in case_rows:
        matched_quotes = matched_quote_map(row.get("matched_slots") or [])
        gold = set(row.get("gold_symptoms") or [])
        for idx, span in enumerate(row.get("spans") or [], start=1):
            if not isinstance(span, dict):
                continue
            quote = str(span.get("source_quote") or "")
            matched_names = matched_quotes.get(quote, [])
            rows.append({
                "case_id": row.get("case_id"),
                "span_index": idx,
                "is_active_for_ir": bool(is_active_symptom_state(span)),
                "type": span.get("type") or "",
                "status": span.get("status") or "",
                "name": span.get("name") or "",
                "slot_ref": span.get("slot_ref") or "",
                "source_quote": quote,
                "normalized_text": span.get("normalized_text") or "",
                "matched_names_from_same_quote": join_list(matched_names),
                "matched_gold_overlap": join_list(sorted(set(matched_names) & gold)),
                "explain": span.get("explain") or "",
            })
    return rows


def classify_failure(
    row: dict[str, Any],
    active: list[dict[str, Any]],
    missing_gold: list[str],
    extra_predicted: list[str],
    negative_hits: list[str],
) -> str:
    """케이스를 사람이 바로 볼 수 있는 실패 유형으로 분류합니다."""
    if row.get("error"):
        return "pipeline_error"
    if not row.get("validator_passed"):
        return "validator_failed"
    if not row.get("spans"):
        return "no_extracted_spans"
    if row.get("gold_symptoms") and not active:
        return "no_active_symptom_span"
    if active and row.get("gold_symptoms") and not row.get("predicted_symptoms"):
        return "ir_no_match_after_active_span"
    if negative_hits:
        return "negative_hit"
    if missing_gold and extra_predicted:
        return "partial_miss_with_false_positive"
    if missing_gold:
        return "missing_gold"
    if extra_predicted:
        return "false_positive"
    return "ok"


def active_spans(spans: list[Any]) -> list[dict[str, Any]]:
    """IR 매칭 대상이 되는 현재 증상 span만 남깁니다."""
    return [span for span in spans if isinstance(span, dict) and is_active_symptom_state(span)]


def span_names(spans: list[Any]) -> list[str]:
    return [str(span.get("name") or "") for span in spans if isinstance(span, dict) and span.get("name")]


def matched_quote_map(matched_slots: list[dict[str, Any]]) -> dict[str, list[str]]:
    """같은 source_quote에서 어떤 표준 증상이 채택됐는지 묶습니다."""
    result: dict[str, list[str]] = {}
    for slot in matched_slots:
        quote = str(slot.get("source_quote") or "")
        name = str(slot.get("name") or "")
        if quote and name:
            result.setdefault(quote, []).append(name)
    return result


def summarize_validation_errors(errors: list[Any]) -> str:
    """복잡한 validator 오류를 CSV 한 칸에서 볼 수 있게 짧게 줄입니다."""
    parts: list[str] = []
    for error in errors[:3]:
        if isinstance(error, dict):
            loc = ".".join(str(item) for item in error.get("loc") or [])
            msg = str(error.get("msg") or error.get("message") or "")
            parts.append(f"{loc}: {msg}" if loc else msg)
        else:
            parts.append(str(error))
    return " | ".join(part for part in parts if part)


def join_list(values: list[Any]) -> str:
    return " | ".join(str(value) for value in values if value is not None and str(value) != "")


def safe_div(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


def f1_score(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False, default=json_default) + "\n")


def json_default(value: Any) -> Any:
    """운영 IR 결과의 Decimal 값을 평가 파일에 쓸 수 있는 숫자로 바꿉니다."""
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    raise TypeError(f"Not JSON serializable: {type(value)}")


def write_predictions_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case_id",
        "slot_id",
        "name",
        "status",
        "source_quote",
        "normalized_text",
        "rank_score",
        "bm25_score",
        "vector_score",
        "label_score",
        "accept_reason",
    ]
    write_csv(path, rows, fieldnames)


def write_candidates_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case_id",
        "accepted_name",
        "query",
        "rank",
        "candidate",
        "slot_id",
        "score",
        "rank_score",
        "bm25_score",
        "vector_score",
    ]
    write_csv(path, rows, fieldnames)


def write_diagnostics_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case_id",
        "visit_type",
        "question_id",
        "question_type",
        "failure_type",
        "error",
        "validator_passed",
        "validation_error_count",
        "validation_error_summary",
        "extraction_attempts",
        "span_count",
        "active_span_count",
        "matched_count",
        "unmatched_count",
        "precision",
        "recall",
        "f1",
        "exact_match",
        "negative_hit",
        "gold_symptoms",
        "predicted_symptoms",
        "missing_gold",
        "extra_predicted",
        "negative_hits",
        "span_names",
        "active_span_names",
        "span_statuses",
        "span_types",
        "active_quotes",
        "trace_statuses",
        "text",
    ]
    write_csv(path, rows, fieldnames)


def write_span_diagnostics_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case_id",
        "span_index",
        "is_active_for_ir",
        "type",
        "status",
        "name",
        "slot_ref",
        "source_quote",
        "normalized_text",
        "matched_names_from_same_quote",
        "matched_gold_overlap",
        "explain",
    ]
    write_csv(path, rows, fieldnames)


def write_failure_cases_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    write_diagnostics_csv(path, rows)


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_progress(row: dict[str, Any]) -> None:
    status = "ERROR" if row["error"] else "OK"
    print(
        f"[{status}] {row['case_id']} "
        f"gold={row['gold_symptoms']} pred={row['predicted_symptoms']} "
        f"f1={row['f1']:.4f} attempts={row['extraction_attempts']}"
    )


if __name__ == "__main__":
    raise SystemExit(main())

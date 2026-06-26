"""Run separated evaluation tracks for MunjinTalkTalk artifacts.

Track A and B are offline checks. Track C runs the real LangGraph/Bedrock
pipeline but replaces persistence with an in-memory validator so evaluation
does not write S3 or DynamoDB records.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "serverless" / "src"
TRAIN_PATH = ROOT / "evaluation" / "train_100_v2" / "train_100_v2.jsonl"
DEFAULT_OUT_DIR = ROOT / "evaluation" / "train_100_v2" / "evaluation_runs" / "latest"

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))


def load_build_artifacts_module():
    path = ROOT / "evaluation" / "train_100_v2" / "build_artifacts.py"
    spec = importlib.util.spec_from_file_location("train_100_v2_build_artifacts", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = load_build_artifacts_module()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def unique(values: list[str]) -> list[str]:
    out = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def gold_symptoms(row: dict[str, Any]) -> set[str]:
    return {BUILD.to_ontology_name(symptom) for symptom in row.get("gold_symptoms") or []}


def negative_symptoms(row: dict[str, Any]) -> set[str]:
    values = list(row.get("negative_symptoms") or []) + list(row.get("explicitly_negated_symptoms") or [])
    return {BUILD.to_ontology_name(symptom) for symptom in values}


def prf_counts(gold: set[str], pred: set[str]) -> dict[str, int]:
    return {
        "tp": len(gold & pred),
        "fp": len(pred - gold),
        "fn": len(gold - pred),
    }


def prf_from_counts(counts: dict[str, int]) -> dict[str, float]:
    tp = counts.get("tp", 0)
    fp = counts.get("fp", 0)
    fn = counts.get("fn", 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def run_track_a_ir(rows: list[dict[str, Any]]) -> dict[str, Any]:
    from rag_context import retrieve_alias_hints, retrieve_symptom_references

    details = []
    source_names = ["alias", "bm25", "combined"]
    hit_totals = {source: {1: 0, 3: 0, 5: 0, 10: 0} for source in source_names}
    total_gold = 0
    all_gold_hit_at_5 = {source: 0 for source in source_names}
    negative_rows = 0
    negative_in_top5 = {source: 0 for source in source_names}
    strata: dict[str, dict[str, dict[str, Any]]] = defaultdict(lambda: defaultdict(lambda: {"rows": 0, "gold": 0, "hit5": 0, "all5": 0}))

    for row in rows:
        gold = gold_symptoms(row)
        negative = negative_symptoms(row)
        total_gold += len(gold)
        if negative:
            negative_rows += 1

        alias_candidates = unique([item["canonical_hint"] for item in retrieve_alias_hints(row["utterance"])])
        bm25_candidates = unique([
            item["display_name"]
            for item in retrieve_symptom_references(row["utterance"], top_k=10)
            if item.get("display_name")
        ])
        combined_candidates = unique(alias_candidates + bm25_candidates)
        candidates = {
            "alias": alias_candidates,
            "bm25": bm25_candidates,
            "combined": combined_candidates,
        }

        row_result = {
            "case_id": row["case_id"],
            "question_id": row.get("question_id"),
            "language_style": row.get("language_style"),
            "dialect_source_layer": row.get("dialect_source_layer"),
            "expression_policy": row.get("expression_policy"),
            "symptom_group": row.get("symptom_group"),
            "utterance": row.get("utterance"),
            "gold": sorted(gold),
            "negative": sorted(negative),
            "candidates": candidates,
        }
        details.append(row_result)

        for source, items in candidates.items():
            for k in [1, 3, 5, 10]:
                hit_totals[source][k] += len(gold & set(items[:k]))
            if gold and gold <= set(items[:5]):
                all_gold_hit_at_5[source] += 1
            if negative and negative & set(items[:5]):
                negative_in_top5[source] += 1

            for strat_key in ["question_id", "language_style", "dialect_source_layer", "expression_policy", "symptom_group"]:
                label = str(row.get(strat_key) or "unknown")
                bucket = strata[f"{source}:{strat_key}"][label]
                bucket["rows"] += 1
                bucket["gold"] += len(gold)
                bucket["hit5"] += len(gold & set(items[:5]))
                if gold and gold <= set(items[:5]):
                    bucket["all5"] += 1

    metrics = {}
    for source in source_names:
        metrics[source] = {
            f"recall@{k}": round(hit_totals[source][k] / total_gold, 4) if total_gold else 0.0
            for k in [1, 3, 5, 10]
        }
        metrics[source]["all_gold_hit@5"] = round(all_gold_hit_at_5[source] / len(rows), 4) if rows else 0.0
        metrics[source]["negative_in_top5_rows"] = negative_in_top5[source]
        metrics[source]["negative_in_top5_rate_among_negative_rows"] = (
            round(negative_in_top5[source] / negative_rows, 4) if negative_rows else 0.0
        )

    stratified = {}
    for group_name, buckets in strata.items():
        stratified[group_name] = {}
        for label, bucket in sorted(buckets.items()):
            stratified[group_name][label] = {
                "rows": bucket["rows"],
                "gold": bucket["gold"],
                "recall@5": round(bucket["hit5"] / bucket["gold"], 4) if bucket["gold"] else 0.0,
                "all_gold_hit@5": round(bucket["all5"] / bucket["rows"], 4) if bucket["rows"] else 0.0,
            }

    return {
        "track": "A_offline_ir",
        "runs_bedrock": False,
        "dataset_rows": len(rows),
        "total_gold_mentions": total_gold,
        "negative_rows": negative_rows,
        "metrics": metrics,
        "stratified": stratified,
        "details": details,
    }


def run_track_b_dialect(rows: list[dict[str, Any]]) -> dict[str, Any]:
    from dialect_rag import retrieve_dialect_context
    from utils import compact_ir

    details = []
    anchored_total = 0
    anchored_hit = 0
    non_anchor_gangwon_total = 0
    non_anchor_hint_rows = 0

    for row in rows:
        layer = row.get("dialect_source_layer")
        if row.get("language_style") != "gangwon":
            continue
        context = retrieve_dialect_context(row.get("utterance") or "", top_k=8)
        hints = context.get("hints") or []
        anchor = row.get("dialect_anchor") or {}
        expected = str(anchor.get("dialect") or "")
        expected_compact = compact_ir(expected)
        hint_compacts = [compact_ir(item.get("dialect") or "") for item in hints]
        hit = bool(expected_compact and any(expected_compact in hint or hint in expected_compact for hint in hint_compacts))

        if layer == "rag_pack_anchored":
            anchored_total += 1
            if hit:
                anchored_hit += 1
        else:
            non_anchor_gangwon_total += 1
            if hints:
                non_anchor_hint_rows += 1

        details.append(
            {
                "case_id": row["case_id"],
                "dialect_source_layer": layer,
                "utterance": row.get("utterance"),
                "expected_anchor": expected,
                "hit_expected_anchor": hit if layer == "rag_pack_anchored" else None,
                "hints": hints,
            }
        )

    return {
        "track": "B_dialect_rag_sanity",
        "runs_bedrock": False,
        "gangwon_rows": len(details),
        "rag_pack_anchored_rows": anchored_total,
        "rag_pack_anchor_hit_rows": anchored_hit,
        "rag_pack_anchor_recall": round(anchored_hit / anchored_total, 4) if anchored_total else 0.0,
        "non_anchor_gangwon_rows": non_anchor_gangwon_total,
        "non_anchor_hint_rows": non_anchor_hint_rows,
        "non_anchor_hint_rate": round(non_anchor_hint_rows / non_anchor_gangwon_total, 4) if non_anchor_gangwon_total else 0.0,
        "details": details,
    }


def fake_validate_and_save(body: dict[str, Any]):
    return {
        "validator_passed": True,
        "onepager_ready": False,
        "errors": [],
        "safety_flag": body.get("safety_flag"),
        "eval_persistence": "skipped_s3_dynamodb",
    }, None


def run_track_c_pipeline(rows: list[dict[str, Any]], limit: int, offset: int = 0) -> dict[str, Any]:
    if limit <= 0:
        return {
            "track": "C_pipeline_integration",
            "runs_bedrock": True,
            "status": "not_run",
            "reason": "pipeline_limit <= 0",
        }

    import pipeline_nodes
    import pipeline_graph

    pipeline_nodes.validate_and_save = fake_validate_and_save
    selected = rows[offset: offset + limit]
    details = []
    counts = {"tp": 0, "fp": 0, "fn": 0}
    negative_rows = 0
    negative_false_positive_rows = 0
    schema_failures = 0
    source_quote_ok = 0
    rag_context_seen = 0

    for row in selected:
        body = {
            "session_id": f"eval-{row['case_id']}",
            "question_id": row["question_id"],
            "question_type": row["question_type"],
            "question_set_id": "default",
            "visit_type": row["visit_type"],
            "transcript": row["utterance"],
        }
        try:
            final_state = pipeline_graph._compiled_graph().invoke({"body": body, "trace": [], "active_path": []})
        except Exception as exc:
            schema_failures += 1
            details.append(
                {
                    "case_id": row["case_id"],
                    "status": "exception",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc)[:500],
                    "gold": sorted(gold_symptoms(row)),
                }
            )
            continue

        if final_state.get("error_response"):
            schema_failures += 1
            details.append(
                {
                    "case_id": row["case_id"],
                    "status": "error_response",
                    "error_response": final_state.get("error_response"),
                    "gold": sorted(gold_symptoms(row)),
                }
            )
            continue

        payload = final_state.get("result_payload") or {}
        trace = final_state.get("trace") or []
        matched = payload.get("matched_slots") or []
        spans = payload.get("spans") or []
        pred = {str(item.get("name")) for item in matched if item.get("name")}
        gold = gold_symptoms(row)
        negative = negative_symptoms(row)
        row_counts = prf_counts(gold, pred)
        for key in counts:
            counts[key] += row_counts[key]
        if negative:
            negative_rows += 1
            if negative & pred:
                negative_false_positive_rows += 1

        quotes_ok = all(
            not span.get("source_quote") or str(span.get("source_quote")) in row["utterance"]
            for span in spans
            if isinstance(span, dict)
        )
        if quotes_ok:
            source_quote_ok += 1
        if any(entry.get("node") == "rag_context_retrieval" for entry in trace):
            rag_context_seen += 1

        details.append(
            {
                "case_id": row["case_id"],
                "status": "completed",
                "question_id": row.get("question_id"),
                "language_style": row.get("language_style"),
                "dialect_source_layer": row.get("dialect_source_layer"),
                "utterance": row.get("utterance"),
                "gold": sorted(gold),
                "negative": sorted(negative),
                "predicted": sorted(pred),
                "spans": spans,
                "matched_slots": matched,
                "counts": row_counts,
                "source_quote_grounded": quotes_ok,
                "active_path": [entry.get("node") for entry in trace if entry.get("node")],
                "trace_summary": [
                    {
                        "node": entry.get("node"),
                        "status": entry.get("status"),
                        "details": entry.get("details"),
                    }
                    for entry in trace
                ],
            }
        )

    completed = [item for item in details if item.get("status") == "completed"]
    metrics = prf_from_counts(counts)
    metrics.update(
        {
            "evaluated_rows": len(selected),
            "completed_rows": len(completed),
            "schema_or_runtime_failure_rows": schema_failures,
            "source_quote_grounding_rate": round(source_quote_ok / len(completed), 4) if completed else 0.0,
            "rag_context_node_seen_rate": round(rag_context_seen / len(completed), 4) if completed else 0.0,
            "negative_rows": negative_rows,
            "negative_false_positive_rows": negative_false_positive_rows,
            "negative_false_positive_rate": round(negative_false_positive_rows / negative_rows, 4) if negative_rows else 0.0,
        }
    )

    return {
        "track": "C_pipeline_integration",
        "runs_bedrock": True,
        "persistence": "monkeypatched_no_s3_dynamodb",
        "dataset_rows": len(rows),
        "offset": offset,
        "limit": limit,
        "metrics": metrics,
        "details": details,
    }


def render_markdown(report: dict[str, Any]) -> str:
    track_a = report.get("track_a_ir") or {}
    track_b = report.get("track_b_dialect") or {}
    track_c = report.get("track_c_pipeline") or {}
    lines = [
        "# Separated Evaluation Report",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- dataset: `{report.get('dataset')}`",
        f"- dataset_rows: `{report.get('dataset_rows')}`",
        f"- held_out_test: `{report.get('held_out_test')}`",
        "",
        "## Track A - Offline IR",
        "",
        "Runs no Bedrock. Combines alias hints and local BM25 symptom references.",
        "",
    ]
    for source, metrics in (track_a.get("metrics") or {}).items():
        lines.append(
            f"- {source}: recall@1={metrics.get('recall@1')}, "
            f"recall@3={metrics.get('recall@3')}, recall@5={metrics.get('recall@5')}, "
            f"recall@10={metrics.get('recall@10')}, all_gold_hit@5={metrics.get('all_gold_hit@5')}, "
            f"negative_in_top5_rate={metrics.get('negative_in_top5_rate_among_negative_rows')}"
        )
    lines.extend(
        [
            "",
            "## Track B - Dialect RAG",
            "",
            f"- Gangwon rows: `{track_b.get('gangwon_rows')}`",
            f"- rag_pack_anchored recall: `{track_b.get('rag_pack_anchor_recall')}` "
            f"({track_b.get('rag_pack_anchor_hit_rows')}/{track_b.get('rag_pack_anchored_rows')})",
            f"- non-anchor hint rate: `{track_b.get('non_anchor_hint_rate')}` "
            f"({track_b.get('non_anchor_hint_rows')}/{track_b.get('non_anchor_gangwon_rows')})",
            "",
            "## Track C - Pipeline Integration",
            "",
        ]
    )
    if track_c.get("status") == "not_run":
        lines.append(f"- not run: {track_c.get('reason')}")
    else:
        metrics = track_c.get("metrics") or {}
        lines.extend(
            [
                f"- persistence: `{track_c.get('persistence')}`",
                f"- rows: `{metrics.get('completed_rows')}/{metrics.get('evaluated_rows')}` completed",
                f"- precision: `{metrics.get('precision')}`",
                f"- recall: `{metrics.get('recall')}`",
                f"- F1: `{metrics.get('f1')}`",
                f"- schema/runtime failures: `{metrics.get('schema_or_runtime_failure_rows')}`",
                f"- source quote grounding rate: `{metrics.get('source_quote_grounding_rate')}`",
                f"- RAG context node seen rate: `{metrics.get('rag_context_node_seen_rate')}`",
                f"- negative false-positive rate: `{metrics.get('negative_false_positive_rate')}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Track A is candidate-search quality, not final model F1.",
            "- Track C is the first model/pipeline score, but this run is on train_100_v2 unless a locked test dataset is supplied.",
            "- Held-out reporting still requires test_1000_v2 generation and a frozen first-pass report before any test-driven tuning.",
            "",
        ]
    )
    return "\n".join(lines)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=TRAIN_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--pipeline-limit", type=int, default=0)
    parser.add_argument("--pipeline-offset", type=int, default=0)
    args = parser.parse_args()

    rows = read_jsonl(args.dataset)
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    track_a = run_track_a_ir(rows)
    track_b = run_track_b_dialect(rows)
    track_c = run_track_c_pipeline(rows, args.pipeline_limit, args.pipeline_offset)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(args.dataset.relative_to(ROOT)).replace("\\", "/") if args.dataset.is_relative_to(ROOT) else str(args.dataset),
        "dataset_rows": len(rows),
        "held_out_test": False,
        "track_a_ir": track_a,
        "track_b_dialect": track_b,
        "track_c_pipeline": track_c,
    }

    write_json(out_dir / "track_a_ir.json", track_a)
    write_json(out_dir / "track_b_dialect.json", track_b)
    write_json(out_dir / "track_c_pipeline.json", track_c)
    write_json(out_dir / "separated_evaluation_report.json", report)
    (out_dir / "separated_evaluation_report.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({
        "out_dir": str(out_dir.relative_to(ROOT)).replace("\\", "/") if out_dir.is_relative_to(ROOT) else str(out_dir),
        "track_a": track_a.get("metrics"),
        "track_b": {
            "rag_pack_anchor_recall": track_b.get("rag_pack_anchor_recall"),
            "non_anchor_hint_rate": track_b.get("non_anchor_hint_rate"),
        },
        "track_c": track_c.get("metrics") or {"status": track_c.get("status"), "reason": track_c.get("reason")},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

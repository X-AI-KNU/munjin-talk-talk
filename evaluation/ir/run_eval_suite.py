#!/usr/bin/env python3
"""실제 문진 파이프라인 실행과 IR 평가를 한 번에 이어서 수행합니다.

평가자가 직접 `source_quote`, `normalized_text`, `LLM 증상명`을 만들면 실제
서비스에서 일어나는 LLM 추출 오차가 평가에 반영되지 않습니다. 이 실행기는 먼저
원본 발화 데이터로 백엔드 파이프라인을 실행해 span을 생성하고, 그 결과를 IR 평가
입력으로 넘깁니다.

기본 IR 평가는 현재 MVP 채택안인 G안입니다.
- query: 표준화 span + LLM symptom hint
- ranker: BM25 + Titan Vector + label signal을 RRF로 융합
- linker: top-k 후보 안에서 Nova Pro가 최종 표준 증상을 선택
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_SCRIPT = PROJECT_ROOT / "evaluation" / "ir" / "run_pipeline_eval.py"
IR_SCRIPT = PROJECT_ROOT / "evaluation" / "ir" / "run_ir_eval.py"


def main() -> int:
    args = parse_args()
    input_path = resolve_project_path(args.input)
    output_dir = resolve_project_path(args.output_dir)
    pipeline_dir = output_dir / "pipeline"
    ir_dir = output_dir / "ir_from_pipeline"
    generated_ir_input = pipeline_dir / "pipeline_ir_eval_cases.jsonl"

    pipeline_cmd = [
        sys.executable,
        str(PIPELINE_SCRIPT),
        "--input",
        str(input_path),
        "--output-dir",
        str(pipeline_dir),
    ]
    if args.limit:
        pipeline_cmd.extend(["--limit", str(args.limit)])

    print("\n[1/2] 실제 문진 파이프라인 평가를 실행합니다.")
    print(" ".join(pipeline_cmd))
    run_command(pipeline_cmd)

    if not generated_ir_input.exists() or generated_ir_input.stat().st_size == 0:
        raise SystemExit(
            "파이프라인 결과에서 IR 평가 입력을 만들지 못했습니다. "
            f"파일을 확인하세요: {generated_ir_input}"
        )

    ir_cmd = [
        sys.executable,
        str(IR_SCRIPT),
        "--input",
        str(generated_ir_input),
        "--output-dir",
        str(ir_dir),
        "--top-k",
        str(args.top_k),
        "--score-mode",
        args.score_mode,
        "--variants",
        args.variants,
    ]
    if args.skip_llm_judge:
        ir_cmd.append("--skip-llm-judge")
    if args.use_slot_hint:
        ir_cmd.append("--use-slot-hint")
    if args.include_non_active_spans:
        ir_cmd.append("--include-non-active-spans")

    print("\n[2/2] 파이프라인이 생성한 span으로 IR/linker 평가를 실행합니다.")
    print(" ".join(ir_cmd))
    run_command(ir_cmd)

    print("\n평가 실행이 완료되었습니다.")
    print(f"- 파이프라인 결과: {pipeline_dir}")
    print(f"- IR 평가 결과: {ir_dir}")
    print(f"- IR 평가 입력: {generated_ir_input}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "원본 평가 데이터로 실제 파이프라인을 먼저 실행한 뒤, "
            "생성된 span으로 현재 채택안(G안) IR/linker 평가를 수행합니다."
        )
    )
    parser.add_argument("--input", type=Path, required=True, help="text와 gold_symptoms를 담은 평가 JSONL 또는 JSON 배열")
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation/ir/outputs"), help="전체 평가 결과 저장 폴더")
    parser.add_argument("--limit", type=int, default=0, help="앞에서 N개 case만 실행합니다. 0이면 전체 실행입니다.")
    parser.add_argument("--top-k", type=int, default=20, help="IR 후보 수입니다. 현재 MVP 기준은 20입니다.")
    parser.add_argument("--variants", default="G", help="평가 variant입니다. 기본값 G는 현재 MVP 채택안입니다.")
    parser.add_argument("--score-mode", default="rrf-hybrid", help="IR rank fusion 방식입니다. 기본값은 rrf-hybrid입니다.")
    parser.add_argument("--skip-llm-judge", action="store_true", help="LLM linker를 생략하고 IR 후보군만 빠르게 확인합니다.")
    parser.add_argument("--use-slot-hint", action="store_true", help="span의 slot_ref를 IR 우선 힌트로 사용합니다.")
    parser.add_argument(
        "--include-non-active-spans",
        action="store_true",
        help="없음/호전/과거력 span도 IR 평가에 포함해 false positive를 점검합니다.",
    )
    return parser.parse_args()


def run_command(cmd: list[str]) -> None:
    """하위 평가 스크립트 실패를 즉시 상위 실행 실패로 전달합니다."""
    completed = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def resolve_project_path(path: Path) -> Path:
    """상대 경로 입력을 프로젝트 루트 기준 절대 경로로 변환합니다."""
    return path if path.is_absolute() else PROJECT_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())

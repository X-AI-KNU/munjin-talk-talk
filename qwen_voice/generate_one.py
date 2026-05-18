# qwen_voice/generate_one.py
#
# Qwen3-TTS Base Voice Clone CLI - confirmed against official qwen-tts-demo behavior.
#
# Matching local Web UI command:
#   qwen-tts-demo Qwen/Qwen3-TTS-12Hz-1.7B-Base --device cuda:0 --no-flash-attn --ip 127.0.0.1 --port 8000 --concurrency 1
#
# Important:
# - Uses Base model for voice clone.
# - Uses dtype=bfloat16 by default, same as qwen-tts-demo default.
# - Uses attn_implementation=None when flash-attn is disabled.
# - Does NOT force eager.
# - Does NOT force float16.
# - Does NOT normalize/modify generated output wav.
# - Converts reference audio to the same tuple style as the official Web UI.

import argparse
import csv
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf
import torch

from qwen_tts import Qwen3TTSModel


# ---------------------------------------------------------------------
# Fixed/default settings
# ---------------------------------------------------------------------

MODEL_ID = os.environ.get("QWEN_MODEL_ID", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")
DEVICE = os.environ.get("QWEN_DEVICE", "cuda:0")
LANGUAGE = os.environ.get("QWEN_LANGUAGE", "Korean")

# qwen-tts-demo default dtype is bfloat16.
# Do not set float16 unless you intentionally want to test it.
QWEN_DTYPE = os.environ.get("QWEN_DTYPE", "bfloat16").lower()

# This reproduces qwen-tts-demo with --no-flash-attn:
#   attn_implementation = None
# Do not use "eager" here when trying to match Web UI behavior.
USE_FLASH_ATTN = os.environ.get("QWEN_USE_FLASH_ATTN", "0").strip().lower() in ("1", "true", "yes", "y")

DATA_DIR = Path("qwen_voice/data")
OUTPUT_DIR = Path("qwen_voice/outputs")


# ---------------------------------------------------------------------
# CSV utilities
# ---------------------------------------------------------------------

def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    encodings = ("utf-8-sig", "utf-8", "cp949", "euc-kr", "mbcs")
    last_error = None

    for enc in encodings:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f))
            print(f"CSV loaded: {path} ({enc})")
            return rows
        except UnicodeDecodeError as e:
            last_error = e

    raise RuntimeError(f"CSV encoding failed: {path}") from last_error


def find_by_key(rows: List[Dict[str, str]], key: str, value: str) -> Optional[Dict[str, str]]:
    for row in rows:
        if row.get(key, "").strip() == value:
            return row
    return None


def require_columns(rows: List[Dict[str, str]], required: List[str], file_name: str) -> None:
    if not rows:
        raise ValueError(f"{file_name}에 데이터가 없습니다.")

    missing = [col for col in required if col not in rows[0]]
    if missing:
        raise ValueError(f"{file_name}에 필요한 컬럼이 없습니다: {missing}")


# ---------------------------------------------------------------------
# Official Web UI-compatible audio conversion
# Based on qwen_tts.cli.demo behavior:
#   Gradio audio -> _audio_to_tuple -> (wav_float32_mono, sr)
# ---------------------------------------------------------------------

def normalize_audio(wav: Any, eps: float = 1e-12, clip: bool = True) -> np.ndarray:
    x = np.asarray(wav)

    if np.issubdtype(x.dtype, np.integer):
        info = np.iinfo(x.dtype)
        if info.min < 0:
            y = x.astype(np.float32) / max(abs(info.min), info.max)
        else:
            mid = (info.max + 1) / 2.0
            y = (x.astype(np.float32) - mid) / mid

    elif np.issubdtype(x.dtype, np.floating):
        y = x.astype(np.float32)
        m = np.max(np.abs(y)) if y.size else 0.0
        if m <= 1.0 + 1e-6:
            pass
        else:
            y = y / (m + eps)

    else:
        raise TypeError(f"Unsupported audio dtype: {x.dtype}")

    if clip:
        y = np.clip(y, -1.0, 1.0)

    if y.ndim > 1:
        # Official demo averages the last axis.
        y = np.mean(y, axis=-1).astype(np.float32)

    return y


def file_to_ref_audio_tuple(path: Path) -> Tuple[np.ndarray, int]:
    wav, sr = sf.read(path, always_2d=False)
    wav = normalize_audio(wav)
    return wav, int(sr)


# ---------------------------------------------------------------------
# Model utilities
# ---------------------------------------------------------------------

def dtype_from_str(dtype_name: str) -> torch.dtype:
    s = (dtype_name or "").strip().lower()
    if s in ("bf16", "bfloat16"):
        return torch.bfloat16
    if s in ("fp16", "float16", "half"):
        return torch.float16
    if s in ("fp32", "float32"):
        return torch.float32
    raise ValueError("QWEN_DTYPE must be one of: bfloat16, float16, float32")


def build_model_kwargs() -> Dict[str, Any]:
    dtype = dtype_from_str(QWEN_DTYPE)
    attn_impl = "flash_attention_2" if USE_FLASH_ATTN else None

    # Official qwen-tts-demo passes dtype and attn_implementation explicitly.
    return {
        "device_map": DEVICE,
        "dtype": dtype,
        "attn_implementation": attn_impl,
    }


def to_soundfile_audio(wav: Any) -> Any:
    # Do not normalize, round, clip, nan_to_num, or subtype-force generated output.
    # Only move tensor to CPU if the library returns a tensor.
    if isinstance(wav, torch.Tensor):
        return wav.detach().cpu().numpy()
    return wav


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sample-id",
        default=None,
        help="scripts.csv의 sample_id. 생략하면 첫 번째 샘플을 사용함.",
    )
    parser.add_argument(
        "--speakers-file",
        default=None,
        help="화자 CSV 파일명. 기본: speakers.csv가 있으면 사용, 없으면 speakergw1.csv 사용.",
    )
    args = parser.parse_args()

    wav_dir = OUTPUT_DIR / "wav"
    meta_dir = OUTPUT_DIR / "metadata"
    wav_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    scripts_path = DATA_DIR / "scripts.csv"

    if args.speakers_file:
        speakers_path = DATA_DIR / args.speakers_file
    else:
        speakers_path = DATA_DIR / "speakers.csv"
        if not speakers_path.exists():
            speakers_path = DATA_DIR / "speakergw1.csv"

    scripts = read_csv_rows(scripts_path)
    speakers = read_csv_rows(speakers_path)

    require_columns(scripts, ["sample_id", "text", "ref_speaker_id"], "scripts.csv")
    require_columns(speakers, ["ref_speaker_id", "ref_audio", "ref_text"], str(speakers_path))

    if args.sample_id:
        script = find_by_key(scripts, "sample_id", args.sample_id)
        if script is None:
            raise ValueError(f"sample_id를 찾을 수 없습니다: {args.sample_id}")
    else:
        script = scripts[0]

    sample_id = script["sample_id"].strip()
    text = script["text"].strip()
    ref_speaker_id = script["ref_speaker_id"].strip()

    speaker = find_by_key(speakers, "ref_speaker_id", ref_speaker_id)
    if speaker is None:
        raise ValueError(f"{speakers_path}에서 ref_speaker_id를 찾을 수 없습니다: {ref_speaker_id}")

    ref_audio_path = Path(speaker["ref_audio"].strip())
    ref_text = speaker["ref_text"].strip()

    if not ref_audio_path.exists():
        raise FileNotFoundError(
            f"참조 음성 파일이 없습니다: {ref_audio_path}\n"
            "qwen_voice/data/reference_audio/ 아래 파일과 speaker CSV 경로를 확인하세요."
        )

    ref_audio_tuple = file_to_ref_audio_tuple(ref_audio_path)
    ref_wav, ref_sr = ref_audio_tuple

    model_kwargs = build_model_kwargs()

    print("=== Qwen Voice Clone Single Test / official Web UI matched ===")
    print(f"model_id: {MODEL_ID}")
    print(f"device_map: {model_kwargs['device_map']}")
    print(f"dtype: {model_kwargs['dtype']}")
    print(f"attn_implementation: {model_kwargs['attn_implementation']}")
    print(f"language: {LANGUAGE}")
    print(f"x_vector_only_mode: False")
    print(f"sample_id: {sample_id}")
    print(f"ref_speaker_id: {ref_speaker_id}")
    print(f"speaker_csv: {speakers_path}")
    print(f"ref_audio: {ref_audio_path}")
    print(f"ref_audio_tuple: shape={ref_wav.shape}, sr={ref_sr}, dtype={ref_wav.dtype}")
    print(f"text: {text}")
    print("==============================================================")

    started_at = time.time()

    model = Qwen3TTSModel.from_pretrained(
        MODEL_ID,
        **model_kwargs,
    )

    wavs, sr = model.generate_voice_clone(
        text=text,
        language=LANGUAGE,
        ref_audio=ref_audio_tuple,
        ref_text=ref_text,
        x_vector_only_mode=False,
    )

    elapsed = time.time() - started_at

    out_wav = wav_dir / f"{sample_id}.wav"
    out_meta = meta_dir / f"{sample_id}.json"

    sf.write(out_wav, to_soundfile_audio(wavs[0]), sr)

    meta = {
        "sample_id": sample_id,
        "text": text,
        "ref_speaker_id": ref_speaker_id,
        "speaker_csv": str(speakers_path),
        "ref_audio": str(ref_audio_path),
        "ref_text": ref_text,
        "model_id": MODEL_ID,
        "language": LANGUAGE,
        "x_vector_only_mode": False,
        "device_map": model_kwargs["device_map"],
        "dtype": str(model_kwargs["dtype"]),
        "attn_implementation": model_kwargs["attn_implementation"],
        "use_flash_attn": USE_FLASH_ATTN,
        "ref_audio_tuple_shape": list(ref_wav.shape),
        "ref_audio_sample_rate": ref_sr,
        "sample_rate": sr,
        "output_wav": str(out_wav),
        "elapsed_sec": round(elapsed, 2),
        "synthetic": True,
        "note": "Qwen3-TTS Base voice clone. Official qwen-tts-demo matched: dtype bfloat16 + no flash-attn + no eager.",
    }

    out_meta.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("")
    print("생성 완료")
    print(f"wav: {out_wav}")
    print(f"metadata: {out_meta}")
    print(f"elapsed_sec: {elapsed:.2f}")


if __name__ == "__main__":
    main()

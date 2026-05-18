# qwen_voice/verify_output_audio.py
# 생성 wav가 상수/NaN/무음인지 빠르게 확인합니다. 생성 파일 자체는 수정하지 않습니다.

from pathlib import Path
import sys

import numpy as np
import soundfile as sf


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("qwen_voice/outputs/wav/sample_001.wav")
    y, sr = sf.read(path, dtype="float32")

    if y.ndim > 1:
        y_mono = y.mean(axis=1)
    else:
        y_mono = y

    duration = len(y_mono) / sr if sr else 0
    peak = float(np.max(np.abs(y_mono))) if y_mono.size else 0.0
    rms = float(np.sqrt(np.mean(y_mono * y_mono))) if y_mono.size else 0.0
    min_v = float(np.min(y_mono)) if y_mono.size else 0.0
    max_v = float(np.max(y_mono)) if y_mono.size else 0.0
    unique_first_1000 = int(len(np.unique(y_mono[:1000]))) if y_mono.size else 0
    has_nan = bool(np.isnan(y_mono).any())
    has_inf = bool(np.isinf(y_mono).any())

    print(f"path={path}")
    print(f"sr={sr}")
    print(f"shape={y.shape}")
    print(f"duration_sec={duration:.3f}")
    print(f"min={min_v:.8f}")
    print(f"max={max_v:.8f}")
    print(f"peak={peak:.8f}")
    print(f"rms={rms:.8f}")
    print(f"unique_first_1000={unique_first_1000}")
    print(f"has_nan={has_nan}")
    print(f"has_inf={has_inf}")

    if has_nan or has_inf:
        print("판정: 비정상. NaN/Inf가 있습니다.")
    elif unique_first_1000 <= 1:
        print("판정: 비정상 가능성 큼. 파형이 상수에 가깝습니다.")
    elif peak < 1e-4:
        print("판정: 무음에 가깝습니다.")
    else:
        print("판정: 파형은 정상 범위입니다. 실제 청감 품질만 확인하면 됩니다.")


if __name__ == "__main__":
    main()

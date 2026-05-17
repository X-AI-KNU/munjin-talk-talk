# qwen_voice/config.py

MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"

# flash_attention_2에서 eager로 환경 설정(Local Testing 용)
ATTN_IMPLEMENTATION = "eager"
BATCH_SIZE = 1

DATA_DIR = "qwen_voice/data"
REFERENCE_DIR = "qwen_voice/data/reference_audio"
OUTPUT_DIR = "qwen_voice/outputs"

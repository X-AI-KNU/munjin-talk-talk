# qwen_voice/config.py

# Qwen3-TTS Base Voice Clone local test settings.
# 현재 기준은 공식 qwen-tts-demo 로컬 Web UI 실행 조건을 따른다.

MODEL_ID = 'Qwen/Qwen3-TTS-12Hz-1.7B-Base'
DEVICE = 'cuda:0'
LANGUAGE = 'Korean'

# Confirmed stable local Web UI condition:
# qwen-tts-demo Qwen/Qwen3-TTS-12Hz-1.7B-Base --device cuda:0 --no-flash-attn --ip 127.0.0.1 --port 8000 --concurrency 1
#
# Do not force:
# - attn_implementation='eager'
# - dtype=torch.float16
#
# Effective condition:
# - dtype: bfloat16
# - attn_implementation: None
# - flash-attn: disabled
DEFAULT_DTYPE = 'bfloat16'
USE_FLASH_ATTN = False

DATA_DIR = 'qwen_voice/data'
OUTPUT_DIR = 'qwen_voice/outputs'
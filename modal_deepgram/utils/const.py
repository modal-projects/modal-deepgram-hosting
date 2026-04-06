import os

# secrets
DEEPGRAM_SECRET_NAME = os.environ.get("DEEPGRAM_SECRET_NAME", "deepgram")

# volumes
MODELS_VOL_NAME = "deepgram-models"
CACHE_VOL_NAME = "deepgram-cache"       
MODELS_PATH = "/models"
CACHE_PATH = "/cache"

# stt hardware
STT_CPU_COUNT = 4
STT_MEMORY = 32*1024
STT_GPU = "L4"

# stt autoscaling
STT_MIN_CONTAINERS = 1

# tts hardware
TTS_CPU_COUNT = 8
TTS_MEMORY = 64*1024
TTS_GPU = "L4:2"

# tts autoscaling
TTS_MIN_CONTAINERS = 1
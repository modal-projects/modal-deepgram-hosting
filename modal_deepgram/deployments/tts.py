#!/usr/bin/env python3
"""
Usage:
  modal deploy deepgram.py
"""
import modal

from ..utils.deepgram import DeepgramAPIandEngine
from ..utils.modal_resources import engine_base_image
from ..utils.const import *

models_vol = modal.Volume.from_name(MODELS_VOL_NAME, create_if_missing=True)
cache_vol = modal.Volume.from_name(CACHE_VOL_NAME, create_if_missing=True)

app = modal.App("deepgram-tts")

@app.cls(
    image=engine_base_image,
    volumes={
        MODELS_PATH: models_vol, 
        CACHE_PATH: cache_vol
    },
    gpu=TTS_GPU,  # Engine requires GPU for inference
    secrets=[modal.Secret.from_name("deepgram")],
    timeout=10000,
    cpu=TTS_CPU_COUNT,  # 4 CPUs for handling concurrent requests
    memory=TTS_MEMORY,  # 32GB memory for model loading and inference
    min_containers=TTS_MIN_CONTAINERS,  # Keep at least 1 container warm - suggested by Deepgram
)
@modal.concurrent(target_inputs=40, max_inputs=70)  
class DeepgramTTS(DeepgramAPIandEngine):
    """Deepgram STT Service: Engine + API in single container with web_server"""
    label: str = "tts"
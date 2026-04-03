#!/usr/bin/env python3
"""
Usage:
  modal deploy -m modal_deepgram.deployments.stt
"""
import modal

from ..utils.deepgram import DeepgramSingleContainer
from ..utils.modal_resources import engine_base_image
from ..utils.const import *

models_vol = modal.Volume.from_name(MODELS_VOL_NAME, create_if_missing=True)
cache_vol = modal.Volume.from_name(CACHE_VOL_NAME, create_if_missing=True)

app = modal.App("deepgram-stt")

@app.cls(
    image=engine_base_image,
    volumes={
        MODELS_PATH: models_vol, 
        CACHE_PATH: cache_vol
    },
    gpu=STT_GPU,
    secrets=[modal.Secret.from_name("deepgram")],
    timeout=10000,
    cpu=STT_CPU_COUNT,
    memory=STT_MEMORY,
    min_containers=STT_MIN_CONTAINERS,
)
@modal.concurrent(target_inputs=40, max_inputs=70)  
class DeepgramSTT(DeepgramSingleContainer):
    """Deepgram STT Service: Engine + API in single container with web_server"""
    label: str = "stt"

    @modal.web_server(port=8080, startup_timeout=300)
    def web_server(self):
        pass

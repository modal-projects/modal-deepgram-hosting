"""
Flash deployment of Deepgram TTS using Modal's experimental HTTP server
for lower-latency access with regional proxy support.

Same Deepgram services as the standard TTS deployment, different serving layer.

Usage:
  modal deploy -m deployments.tts_flash
"""
import modal
import modal.experimental

from modal_deepgram.deepgram import DeepgramServerBase
from modal_deepgram.modal_resources import engine_base_image
from modal_deepgram.shared import (
    API_PORT,
    CACHE_PATH,
    CACHE_VOL_NAME,
    FLASH_REGION,
    FLASH_TARGET_INPUTS,
    MODELS_PATH,
    MODELS_VOL_NAME,
)

# defaults for this deployment
DEFAULT_TTS_CPU_COUNT = 8
DEFAULT_TTS_MEMORY = 64 * 1024
DEFAULT_TTS_GPU = "L4:2"
DEFAULT_TTS_MIN_CONTAINERS = 1

models_vol = modal.Volume.from_name(MODELS_VOL_NAME, create_if_missing=True)
cache_vol = modal.Volume.from_name(CACHE_VOL_NAME, create_if_missing=True)

app = modal.App("deepgram-flash-tts")


@app.cls(
    image=engine_base_image,
    volumes={
        MODELS_PATH: models_vol,
        CACHE_PATH: cache_vol,
    },
    gpu=DEFAULT_TTS_GPU,
    secrets=[modal.Secret.from_name("deepgram")],
    timeout=10000,
    cpu=DEFAULT_TTS_CPU_COUNT,
    memory=DEFAULT_TTS_MEMORY,
    min_containers=DEFAULT_TTS_MIN_CONTAINERS,
    region=FLASH_REGION,
)
@modal.concurrent(target_inputs=FLASH_TARGET_INPUTS)
@modal.experimental.http_server(port=API_PORT, proxy_regions=[FLASH_REGION])
class DeepgramFlashTTS(DeepgramServerBase):
    """Deepgram TTS via experimental HTTP server with regional proxy."""
    label: str = "tts"

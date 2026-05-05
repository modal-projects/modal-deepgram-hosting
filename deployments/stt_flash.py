"""
Flash deployment of Deepgram STT using Modal's experimental HTTP server
for lower-latency access with regional proxy support.

Same Deepgram services as the standard STT deployment, different serving layer.

Usage:
  modal deploy -m modal_deepgram.deployments.flash_http_server.stt_flash
"""
import modal
import modal.experimental

from ...utils.deepgram import DeepgramServer
from ...utils.modal_resources import engine_base_image
from ...utils.shared import (
    API_PORT,
    CACHE_PATH,
    CACHE_VOL_NAME,
    FLASH_REGION,
    FLASH_TARGET_INPUTS,
    MODELS_PATH,
    MODELS_VOL_NAME,
)

# defaults for this deployment
DEFAULT_STT_CPU_COUNT = 4
DEFAULT_STT_MEMORY = 32 * 1024
DEFAULT_STT_GPU = "L4"
DEFAULT_STT_MIN_CONTAINERS = 1

models_vol = modal.Volume.from_name(MODELS_VOL_NAME, create_if_missing=True)
cache_vol = modal.Volume.from_name(CACHE_VOL_NAME, create_if_missing=True)

app = modal.App("deepgram-flash-stt")


@app.cls(
    image=engine_base_image,
    volumes={
        MODELS_PATH: models_vol,
        CACHE_PATH: cache_vol,
    },
    gpu=DEFAULT_STT_GPU,
    secrets=[modal.Secret.from_name("deepgram")],
    timeout=10000,
    cpu=DEFAULT_STT_CPU_COUNT,
    memory=DEFAULT_STT_MEMORY,
    min_containers=DEFAULT_STT_MIN_CONTAINERS,
    region=FLASH_REGION,
)
@modal.concurrent(target_inputs=FLASH_TARGET_INPUTS)
@modal.experimental.http_server(port=API_PORT, proxy_regions=[FLASH_REGION])
class DeepgramFlashSTT(DeepgramServer):
    """Deepgram STT via experimental HTTP server with regional proxy."""
    label: str = "stt"

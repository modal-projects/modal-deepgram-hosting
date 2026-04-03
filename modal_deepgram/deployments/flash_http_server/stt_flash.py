"""
Flash deployment of Deepgram STT using Modal's experimental HTTP server
for lower-latency access with regional proxy support.

Same Deepgram services as the standard STT deployment, different serving layer.

Usage:
  modal deploy -m modal_deepgram.deployments._flash.deepgram_flash
"""
import modal
import modal.experimental

from ...utils.deepgram import DeepgramSingleContainer
from ...utils.modal_resources import engine_base_image
from ...utils.const import *

models_vol = modal.Volume.from_name(MODELS_VOL_NAME, create_if_missing=True)
cache_vol = modal.Volume.from_name(CACHE_VOL_NAME, create_if_missing=True)

REGION = "us-west"

app = modal.App("deepgram-flash-stt")


@app.cls(
    image=engine_base_image,
    volumes={
        MODELS_PATH: models_vol,
        CACHE_PATH: cache_vol,
    },
    gpu="L4",
    secrets=[modal.Secret.from_name("deepgram")],
    timeout=10000,
    cpu=4,
    memory=32*1024,
    min_containers=1,
    region=REGION,
)
@modal.concurrent(target_inputs=20)
@modal.experimental.http_server(port=8080, proxy_regions=[REGION])
class DeepgramFlashSTT(DeepgramSingleContainer):
    """Deepgram STT via experimental HTTP server with regional proxy."""
    label: str = "stt"

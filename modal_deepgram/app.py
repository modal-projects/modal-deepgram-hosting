"""
Single-file deployment of Deepgram self-hosted services on Modal.

The deployment is parameterized by the `DEPLOY_LABEL` environment variable,
which selects which set of configs (`/cache/configs/{label}/`) and models
(`/models/{label}/`) on the Modal volumes the container loads at startup.
The label also becomes the Modal app suffix (`deepgram-{label}`), so
multiple labels can be deployed side by side without clobbering each other.

Hardware (`GPU`, `CPU_COUNT`, `MEMORY`, `MIN_CONTAINERS`) is set to
STT-sized literals below. For TTS, Flux, or other workloads, edit the
constants per Deepgram's hardware recommendations before deploying — see
docs/3_compute-autoscaling.md.

Usage:
  DEPLOY_LABEL=stt modal deploy -m modal_deepgram.app
  DEPLOY_LABEL=tts modal deploy -m modal_deepgram.app
"""
import os

import modal
import modal.experimental

from .deepgram import DeepgramServerBase, engine_base_image
from .shared import (
    API_PORT,
    CACHE_PATH,
    CACHE_VOL_NAME,
    MODELS_PATH,
    MODELS_VOL_NAME,
)

# compute resources
GPU = "L4"
CPU_COUNT = 4
MEMORY = 32 * 1024  # MB

# autoscaling
MIN_CONTAINERS = 1

# concurrency
TARGET_INPUTS = 64

# region selection
PROXY_REGION = "us-west"
SERVER_REGIONS = ["us-west"]

DEPLOY_LABEL = os.environ.get("DEPLOY_LABEL")
if not DEPLOY_LABEL:
    raise RuntimeError(
        "DEPLOY_LABEL is required. Example: "
        "DEPLOY_LABEL=stt modal deploy -m modal_deepgram.app"
    )

models_vol = modal.Volume.from_name(MODELS_VOL_NAME, create_if_missing=True)
cache_vol = modal.Volume.from_name(CACHE_VOL_NAME, create_if_missing=True)

app = modal.App(f"deepgram-{DEPLOY_LABEL}")

MINUTES = 60

@app.cls(
    image=engine_base_image.env({"DEPLOY_LABEL": DEPLOY_LABEL}),
    volumes={
        MODELS_PATH: models_vol,
        CACHE_PATH: cache_vol,
    },
    gpu=GPU,
    secrets=[modal.Secret.from_name("deepgram")],
    timeout=30 * MINUTES,
    cpu=CPU_COUNT,
    memory=MEMORY,
    min_containers=MIN_CONTAINERS,
    region=SERVER_REGIONS,
)
@modal.concurrent(target_inputs=TARGET_INPUTS)
@modal.experimental.http_server(port=API_PORT, proxy_regions=[PROXY_REGION])
class DeepgramServer(DeepgramServerBase):
    """Deepgram self-hosted service via Modal's experimental HTTP server.

    The Deepgram workload (STT/TTS/Flux/etc.) is determined entirely by the
    configs and models on the Modal volumes under `{label}/`, selected at
    deploy time by the `DEPLOY_LABEL` environment variable.
    """
    label: str = DEPLOY_LABEL

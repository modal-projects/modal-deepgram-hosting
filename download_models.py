import modal

app = modal.App("download-models")
models_vol = modal.Volume.from_name("deepgram-models", create_if_missing=True)

import urllib.error
import urllib.request
from pathlib import Path


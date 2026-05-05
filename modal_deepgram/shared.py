# volumes
MODELS_VOL_NAME = "deepgram-models"
CACHE_VOL_NAME = "deepgram-cache"
MODELS_PATH = "/models"
CACHE_PATH = "/cache"

# in-container service ports (single-container deployment, localhost networking).
# the API is the only service exposed externally; the others are internal.
API_PORT = 8080
ENGINE_PORT = 8081
LICENSE_PROXY_PORT = 8443
# License Proxy's status endpoint is moved off 8080 to avoid colliding with the API.
LICENSE_PROXY_STATUS_PORT = 8089

# flash http_server deployments
FLASH_REGION = "us-west"
FLASH_TARGET_INPUTS = 20

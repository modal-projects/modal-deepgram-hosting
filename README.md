# Deepgram Self-Hosted on Modal

Deploy Deepgram's self-hosted Speech-to-Text (STT) and Text-to-Speech (TTS) services on [Modal](https://modal.com), a serverless GPU platform.

## Overview

This repository provides infrastructure-as-code for deploying Deepgram's self-hosted API and Engine containers on Modal. Modal handles GPU provisioning, autoscaling, and networking, making it straightforward to run production Deepgram services without managing infrastructure directly.

### Architecture

Deepgram's self-hosted architecture consists of three services:

- **Engine (Impeller)**: GPU-powered inference service that performs speech processing
- **API (Stem)**: HTTP API that receives requests and forwards them to the Engine
- **License Proxy (Hermes)**: Caching proxy for license validation that enables high availability (optional but recommended for production)

This deployment runs all services in a single Modal container, communicating over localhost. The API is exposed via Modal's web server infrastructure, while the Engine and License Proxy handle GPU inference and license validation internally.

Two deployment types are supported:

- **Standard**: Engine and API validate licenses directly against `license.deepgram.com`
- **License Proxy**: A local License Proxy handles license validation, allowing the deployment to continue operating even if connectivity to Deepgram's license server is temporarily lost

## Prerequisites

### Modal Account and CLI

1. Create a [Modal account](https://modal.com) if you don't have one
2. Install the Modal CLI and authenticate:

```bash
pip install modal
modal setup
```

### Deepgram Self-Hosted Credentials

You need the following credentials from Deepgram:

- **API Key**: Your self-hosted API key secret (created in the API Key tab of Deepgram Console)
- **Container Registry Credentials**: Username and password for pulling images from `quay.io/deepgram`
- **Model Links**: URLs to download your licensed model files

See [Self Service Licensing & Credentials](https://developers.deepgram.com/docs/self-hosted-self-service-tutorial) for instructions on generating these credentials.

## Setup

### 1. Clone This Repository

```bash
git clone https://github.com/your-org/modal-deepgram-hosting.git
cd modal-deepgram-hosting
```

### 2. Create Modal Secret

Create a Modal secret containing your Deepgram credentials:

```bash
modal secret create deepgram \
  DEEPGRAM_API_KEY=<your-api-key-secret> \
  REGISTRY_USERNAME=<your-quay-username> \
  REGISTRY_PASSWORD=<your-quay-password>
```

> **Note**: The `REGISTRY_USERNAME` and `REGISTRY_PASSWORD` are your container image distribution credentials from Deepgram Console, used to pull images from `quay.io/deepgram`.

By default, the code looks for a Modal secret named `deepgram`. To use a different name, set the `DEEPGRAM_SECRET_NAME` environment variable:

```bash
# Create a secret with a custom name
modal secret create my-deepgram-secret \
  DEEPGRAM_API_KEY=<your-api-key-secret> \
  REGISTRY_USERNAME=<your-quay-username> \
  REGISTRY_PASSWORD=<your-quay-password>

# Use it for resource preparation and deployment
DEEPGRAM_SECRET_NAME=my-deepgram-secret modal run -m modal_deepgram.utils.modal_resources ...
DEEPGRAM_SECRET_NAME=my-deepgram-secret modal deploy -m modal_deepgram.deployments.web_server.stt
```

### 3. Set Container Image Version

The deployment uses Deepgram's self-hosted container images. The image tag defaults to `release-260319` and can be updated via the `DEEPGRAM_IMAGE_TAG` environment variable. Check the [Deepgram Self-Hosted Changelog](https://developers.deepgram.com/changelog) for the latest release.

```bash
# Use a newer release for all commands
DEEPGRAM_IMAGE_TAG=release-260402 modal run -m modal_deepgram.utils.modal_resources ...
DEEPGRAM_IMAGE_TAG=release-260402 modal deploy -m modal_deepgram.deployments.web_server.stt
```

Or export it for your session:

```bash
export DEEPGRAM_IMAGE_TAG=release-260402
```

### 4. Add Model Links

Create a file containing URLs to your Deepgram model files. Deepgram provides these links based on your license. This file can be created anywhere—you'll pass its path to the prepare command.

```text
https://LINK_TO_MODEL_1.dg
https://LINK_TO_MODEL_2.dg
https://LINK_TO_MODEL_3.dg
```

## Prepare Deployment

### Initial Setup

Before deploying for the first time, you must prepare the required resources on Modal volumes. Run `prepare_resources` **once per deployment type** — each `--label` corresponds to a separate deployment (e.g., `stt`, `tts`, `tts-spanish`).

| Option | Description |
|--------|-------------|
| `--label` | Label for organizing configs/models (e.g., `stt`, `tts`) |
| `--model-links-path` | Path to file containing model download URLs |
| `--source-api-config-file` | Name of API config file to download (see below) |
| `--source-engine-config-file` | Name of Engine config file to download (see below) |
| `--deploy-type` | Deployment type: `license-proxy` (default) or `standard` |

The `--source-api-config-file` and `--source-engine-config-file` arguments specify config file names from Deepgram's self-hosted-resources repository:

- **Standard deployment**: [common/standard_deploy](https://github.com/deepgram/self-hosted-resources/tree/main/common/standard_deploy)
- **License proxy deployment**: [common/license_proxy_deploy](https://github.com/deepgram/self-hosted-resources/tree/main/common/license_proxy_deploy)

For TTS deployments (e.g., Aura-2), you may need language-specific config files like `api.aura-2-en.toml` and `engine.aura-2-en.toml`.
 The config file names should correspond to the `.toml` file name from the standard deployment configs on the Deepgram `self-hosted-resources` [repo](https://github.com/deepgram/self-hosted-resources/tree/main/common/standard_deploy).

#### Prepare STT Resources

```bash
modal run -m modal_deepgram.utils.modal_resources \
  --label stt \
  --model-links-path /path/to/stt_model_links.txt \
  --source-api-config-file api.toml \
  --source-engine-config-file engine.toml
```

#### Prepare TTS Resources

```bash
modal run -m modal_deepgram.utils.modal_resources \
  --label tts \
  --model-links-path /path/to/tts_model_links.txt \
  --source-api-config-file api.aura-2-polyglot.toml \
  --source-engine-config-file engine.aura-2-polyglot.toml
```

#### Prepare without License Proxy

To deploy without a local License Proxy (license validation goes directly to `license.deepgram.com`):

```bash
modal run -m modal_deepgram.utils.modal_resources \
  --label stt \
  --model-links-path /path/to/stt_model_links.txt \
  --source-api-config-file api.toml \
  --source-engine-config-file engine.toml \
  --deploy-type standard
```

#### What This Does

The `prepare_resources` command performs these operations:

1. **Downloads Config Files**: Fetches the specified config files from Deepgram's [self-hosted-resources repository](https://github.com/deepgram/self-hosted-resources), patches them for single-container deployment (localhost networking, port assignments), and saves them to a Modal volume at `/cache/configs/{label}/`

2. **Downloads Model Files**: Downloads all model files (`.dg`) from your model links file to a Modal volume at `/models/{label}/`

3. **Extracts Binaries**: Extracts the `stem` (API) binary from the Deepgram API container image and caches it at `/cache/binary/stem`. For `license-proxy` deployments, also extracts the `hermes` (License Proxy) binary to `/cache/binary/hermes`

The config patching automatically handles the following for single-container deployment:
- Rewrites Engine and API driver URLs to use `localhost`
- For `standard` deploys: removes the License Proxy from `server_url`, pointing directly to `license.deepgram.com`
- For `license-proxy` deploys: rewrites `server_url` to use the local License Proxy at `localhost:8443`, and adjusts the License Proxy status port to `8089` to avoid conflicting with the API on port `8080`

### Update Configuration

To update an existing deployment's configuration, edit the config files stored on the Modal volume. This does not require re-running `prepare_resources`.

#### Edit Config Files

Use the Modal CLI to download, edit, and re-upload config files:

```bash
# Download config files locally
modal volume get deepgram-cache configs/stt/api.toml ./api.toml
modal volume get deepgram-cache configs/stt/engine.toml ./engine.toml
# For license-proxy deployments:
# modal volume get deepgram-cache configs/stt/license-proxy.toml ./license-proxy.toml

# Edit the files locally with your preferred editor
vim api.toml
vim engine.toml

# Upload modified files back to the volume
modal volume put deepgram-cache ./api.toml configs/stt/api.toml
modal volume put deepgram-cache ./engine.toml configs/stt/engine.toml
```

After updating config files, redeploy the service to apply changes:

```bash
modal deploy -m modal_deepgram.deployments.stt
```

See the [Deepgram configuration documentation](https://developers.deepgram.com/docs/deploy-stt-services) for complete configuration options.

## Deploy on Modal

### Deploy STT Service

```bash
modal deploy -m modal_deepgram.deployments.web_server.stt
```

### Deploy TTS Service

```bash
modal deploy -m modal_deepgram.deployments.web_server.tts
```

After deployment, Modal will output the service URL, e.g.:

```
https://{workspace}-{env}--deepgram-stt-deepgramstt-web-server.modal.run
```

## Test Your Deployment

### Check Status

```bash
curl https://{your-modal-url}/v1/status
```

### List Available Models

```bash
curl https://{your-modal-url}/v1/models
```
<!-- 
### Transcribe Audio (STT)

```bash
curl \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{"url":"https://dpgr.am/spacewalk.wav"}' \
  --url 'https://{your-modal-url}/v1/listen?model=nova-3'
```

### Synthesize Speech (TTS)

```bash
curl \
  --request POST \
  --header 'Content-Type: application/json' \
  --output speech.wav \
  --data '{"text":"Hello, this is a test of Deepgram text to speech."}' \
  --url 'https://{your-modal-url}/v1/speak?model=aura-2-thalia-en'
```

## Customize Deployment

### Hardware Configuration

Hardware settings are defined in `modal_deepgram/utils/const.py`:

```python
# STT Hardware
STT_CPU_COUNT = 4
STT_MEMORY = 32 * 1024  # 32 GB
STT_GPU = "L4"

# TTS Hardware (requires more resources)
TTS_CPU_COUNT = 8
TTS_MEMORY = 64 * 1024  # 64 GB
TTS_GPU = "L4:2"  # 2x L4 GPUs
```

Available GPU options on Modal include:
- `T4` - Budget option, suitable for light workloads
- `L4` - Recommended for STT (good balance of price/performance)
- `L4:2` - Recommended for TTS (dual GPU requirement)
- `A10G` - Higher performance option
- `A100` - Maximum performance for high-throughput workloads

### Autoscaling

Autoscaling is configured in the deployment files (`stt.py` / `tts.py`):

```python
@app.cls(
    # ...
    min_containers=1,  # Keep at least 1 container warm
)
@modal.concurrent(target_inputs=40, max_inputs=70)
class DeepgramSTT(DeepgramSingleContainer):
    ...
```

| Setting | Description |
|---------|-------------|
| `min_containers` | Minimum warm containers (avoids cold starts) |
| `target_inputs` | Target concurrent requests per container for scaling |
| `max_inputs` | Maximum concurrent requests before queuing |

> **Tip**: Deepgram recommends keeping at least 1 container warm (`min_containers=1`) to avoid cold start latency on the first request.

### Networking & Security

Modal handles TLS termination and provides HTTPS endpoints automatically. The deployment exposes the Deepgram API on port 8080 via Modal's web server infrastructure.

**Authentication**: By default, the Deepgram API accepts any request. To add authentication:

1. Configure `[server.auth]` in `api.toml` 
2. Or implement authentication at the application layer before calling the Deepgram endpoint

**Private Deployments**: For private/internal deployments, consider:
- Using Modal's [custom domains](https://modal.com/docs/guide/webhooks#custom-domains)
- Implementing authentication middleware
- Deploying behind your own proxy/load balancer -->

## Volumes

This deployment uses two Modal volumes:

| Volume | Mount Path | Contents |
|--------|------------|----------|
| `deepgram-models` | `/models` | Model files (`.dg`) organized by label |
| `deepgram-cache` | `/cache` | Config files and extracted binaries (`stem`, `hermes`) |

To inspect volume contents:

```bash
modal volume ls deepgram-models
modal volume ls deepgram-cache
```

<!-- ## Troubleshooting

### Container Startup Issues

Check container logs in the Modal dashboard or via CLI:

```bash
modal app logs deepgram-stt
```

### License Validation Errors

- Verify `DEEPGRAM_API_KEY` is correctly set in your Modal secret
- Ensure your API key has self-hosted permissions
- Check that the container can reach `license.deepgram.com` on port 443

### Model Loading Errors

- Verify models were downloaded correctly: `modal volume ls deepgram-models`
- Check that `search_paths` in `engine.toml` matches your label directory
- Ensure model files are compatible with your license

### GPU Not Detected

- Verify you're using a GPU-enabled Modal function
- Check `gpu_required = true` in `engine.toml` to fail fast if no GPU is available -->

## Additional Resources

- [Deepgram Self-Hosted Documentation](https://developers.deepgram.com/docs/self-hosted-deployment-environments)
- [Deploy STT Services](https://developers.deepgram.com/docs/deploy-stt-services)
- [Deploy TTS Services](https://developers.deepgram.com/docs/deploy-tts-services)
- [License Proxy](https://developers.deepgram.com/docs/license-proxy)
- [Modal Documentation](https://modal.com/docs)

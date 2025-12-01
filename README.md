# Deepgram Self-Hosted Deployment on Modal

This repository contains provides a sketch for deployment of Deepgram's self-hosted API and Engine on [Modal](https://modal.com).

## Overview

Deepgram's self-hosted architecture consists of two main services:
- **Engine (Impeller)**: GPU-powered inference service that performs speech-to-text processing
- **API (Stem)**: Public-facing HTTP API that receives requests and forwards them to the Engine

## Handling mTLS

Deepgram's Engine requires **mutual TLS (mTLS) authentication** for security. This means the Engine serves HTTPS and expects clients to present a valid client certificate. However, trying to implement this with standard Modal web endpoints results in TLS termination before the Engine sees requests from the API container.

### Unencrypted Tunnels

This deployment uses Modal's **unencrypted tunnels** to properly handle this mTLS contraint. Modal's unencrypted tunnels provide raw TCP passthrough without TLS termination, allowing the API to present its client certificate directly to the Engine for mTLS authentication.

## Prerequisites

### 1. Modal Account and CLI
```bash
pip install modal
modal setup
```

### 2. Deepgram Credentials
You need a Deepgram API key. Create a Modal secret:
```bash
modal secret create deepgram DEEPGRAM_API_KEY=<your-key>
modal secret create deepgram REGISTRY_PASSWORD=<your-passowrd>
modal secret create deepgram REGISTRY_USERNAME=<your-username>
```

### 3. Model Files
Download Deepgram model files and upload them to a Modal volume named `deepgram-models`:
```bash
# Use the download_models.py script (if available) or manually download models
# Then upload to Modal volume
modal volume put deepgram-models /path/to/models /models
```

### 4. Configuration Files
Upload the configuration files from the `configs/` directory to a Modal volume named `deepgram-config`:
```bash
modal volume create deepgram-config
modal volume put deepgram-config configs/api.toml /deepgram-config/api.toml
modal volume put deepgram-config configs/engine.toml /deepgram-config/engine.toml
```

## Configuration Files

### `configs/api.toml`
Configures the Deepgram API service:
- **Server settings**: Port 8080, listens on all interfaces
- **License validation**: Points to `https://license.deepgram.com`
- **Driver pool**: Specifies the Engine URL (dynamically updated by deployment script)
- **Features**: Enable/disable topic detection, summarization, entity detection, etc.
- **Concurrency**: Request limits and disk buffering options

**Key configuration** (line 117):
```toml
[[driver_pool.standard]]
url = "https://engine:8080/v2"  # Updated at runtime to tunnel URL
```

### `configs/engine.toml`
Configures the Deepgram Engine service:
- **Server settings**: Port 8080, HTTPS with mTLS
- **Model paths**: Points to `/models` volume
- **License validation**: Points to `https://license.deepgram.com`
- **Features**: Multichannel, language detection, NER, etc.
- **GPU settings**: Half precision mode (auto-detected)
- **Performance**: Chunking, concurrency, and health checks

### `configs/license-proxy.toml`
**Note**: This file is included for reference but is **not used** in the current deployment. License validation is performed directly against `https://license.deepgram.com` without a local proxy.

## Deployment

This repository contains two separate Modal apps that must be deployed independently:

### Step 1: Deploy the Engine
```bash
modal deploy deploy_deepgram.py::engine_app
```

This will:
- Create a GPU-powered container (L4) running the Deepgram Engine
- Start the Engine binary (`impeller`) serving HTTPS on port 8080
- Create an unencrypted tunnel for raw TCP passthrough
- Expose a web endpoint that provides tunnel connection information

### Step 2: Deploy the API
```bash
modal deploy deploy_deepgram.py::api_app
```

This will:
- Create a container running the Deepgram API
- Fetch the Engine's tunnel URL from the deployed Engine app
- Update the API configuration to connect to the Engine via the unencrypted tunnel
- Start the API binary (`stem`) serving HTTP on port 8080
- Expose a public web endpoint for API requests

**API startup delay**: While the Engine is staring up, you will see request errors in the API container. These are normal and will stop once the Engine container is running and the API is able to connect.

## Usage

After deployment, you'll receive a URL for the API endpoint:
```
https://{workspace}-{environment}--deepgram-api-api.modal.run
```

### Test the API

#### Check Status
```bash
curl https://{workspace}-{environment}--deepgram-api-api.modal.run/v1/status
```

#### List Available Models
```bash
curl https://{workspace}-{environment}--deepgram-api-api.modal.run/v1/models
```

#### Transcribe Audio
```bash
curl \                                          
  --request POST \
  --header 'Authorization: Token a' \
  --header 'Content-Type: application/json' \
  --data '{"url":"https://dpgr.am/spacewalk.wav"}' \
  --url 'https://{workspace}-{environment}--deepgram-api-api.modal.run/v1/listen?model=nova-3'
```

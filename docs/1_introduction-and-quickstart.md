# Deepgram on Modal

[Modal](https://modal.com) is an AI infrastructure platform for serving scalable, GPU-powered workloads in the cloud. This guide walks through deploying Deepgram as a Modal app.

With Modal, you get serverless GPUs, global compute access for low-latency deployments, and built-in autoscaling & load balancing. Modal's SDK makes it easy to programmatically define infrastructure for your deployments. For information on Modal's features and SDK, check out their [documentation](https://modal.com/docs).

Once you deploy Deepgram on Modal, clients can use the standard Deepgram REST and WebSocket APIs.

## Prerequisites

In order to deploy Deepgram on Modal, you’ll first need to have a self-hosted contract with Deepgram.

Once you have access to self-hosted in the [Deepgram Console](https://console.deepgram.com/), you’ll be able to generate an API key and Distribution Credentials, used during the deployment. The Distribution Credentials are used to authenticate to the Deepgram container image registry, with the environment variables specified below.

Additionally, Deepgram will need to generate unique model file links for your contracted Deepgram project ID. Please ask your Account Executive for access to the required Deepgram model weights files for the products you need to deploy, such as Nova-3, Aura-2, and Flux. Please be sure to specify which languages you need for each product as well, and if you intend to use the HTTP or WebSocket streaming APIs.

## Deployment Structure

- All Deepgram [components (Engine, API, Licence Proxy)](https://developers.deepgram.com/docs/self-hosted-introduction#components) run in a single Modal container and communicate over `localhost`.
- The API is exposed publicly using Modal's `http_server` decorator and routed to containers via a low-latency, regional proxy.
- Model weights and Deepgram TOML configs live on Modal Volumes: a fast, remote data store.

The reference repository ([modal-deepgram-hosting](https://github.com/modal-projects/modal-deepgram-hosting)) ships a single deployment module that can be configured to serve STT, TTS, or Flux.

## Quickstart: Speech-to-Text

Get an STT deployment up and running:

1. Create a [Modal account](https://modal.com/signup), install the Modal CLI, and authenticate.
  ```bash
   pip install modal
   modal setup
  ```
2. Create the `deepgram` Modal Secret with your `DEEPGRAM_API_KEY`, `REGISTRY_USERNAME`, and `REGISTRY_PASSWORD`. You can use the CLI or the [Secrets tab](https://modal.com/secrets) of your Modal workspace dashboard.
  ```bash
   modal secret create deepgram \
     DEEPGRAM_API_KEY=<your-api-key> \
     REGISTRY_USERNAME=<your-quay-username> \
     REGISTRY_PASSWORD=<your-quay-password>
  ```
3. Clone the reference repository.
  ```bash
   git clone https://github.com/modal-projects/modal-deepgram-hosting.git
   cd modal-deepgram-hosting
  ```
4. Save your Deepgram STT model download links (provided by Deepgram) to a `.txt` file, e.g. `model-links.txt`, and note the path.
  ```text
    https://LINK_TO_MODEL_1.dg
    https://LINK_TO_MODEL_2.dg
    https://LINK_TO_MODEL_3.dg
    ...
    https://LINK_TO_MODEL_N.dg
  ```
5. Set the label for this configuration using the `DEPLOY_LABEL` environment variable.
  ```bash
   export DEPLOY_LABEL=stt
  ```
6. Download Deepgram configs and model weights to Modal Volumes. This command will download the most recent configs from the Deepgram self-hosted-resources repo and patch them to communicate over `localhost` using the correct ports.
  ```bash
   modal run -m modal_deepgram.deepgram_resources \
     --label $DEPLOY_LABEL \
     --model-links-path /path/to/model-links.txt \
     --source-api-config-file api.toml \
     --source-engine-config-file engine.toml
  ```
7. Deploy the Modal app.
  ```bash
   modal deploy -m modal_deepgram.app
  ```

## Testing the deployment

Once your Modal app is deployed and a container is running, run a quick set of checks against the public URL to confirm the API is up, models are loaded, and inference works end to end. The Modal endpoint speaks the standard Deepgram REST and WebSocket APIs, so any Deepgram client or SDK works against it.

### Locate your deployment URL

The base URL for the Deepgram endpoint is:

- printed when you run `modal deploy`.
- visible in the Modal dashboard for the Deepgram Function.

### Health checks

#### `GET /v1/status`

Confirms the API is up and the Engine is reachable.

```bash
curl https://{your-modal-url}/v1/status
```

A successful response returns 200 with a JSON body indicating both the API and Engine are healthy.

#### `GET /v1/models`

Lists the models loaded from `/models/{label}/`. Use this to confirm `prepare_resources` populated the right model files.

```bash
curl https://{your-modal-url}/v1/models
```

The response is a JSON array of model metadata. The set of names should match what you put in your model-links file.

### Inference

Upload a local WAV file:

```bash
curl --request POST \
  --header "Content-Type: audio/wav" \
  --data-binary @audio.wav \
  'https://{your-modal-url}/v1/listen?model=nova-3'
```

Or pass a URL payload — Modal containers have outbound network access, so URL ingestion works without extra configuration:

```bash
curl --request POST \
  --header "Content-Type: application/json" \
  --data '{"url": "https://dpgr.am/spacewalk.wav"}' \
  'https://{your-modal-url}/v1/listen?model=nova-3'
```

To use a Deepgram SDK, point the client at the Modal URL by overriding the base URL. See the SDK quickstarts on [developers.deepgram.com](https://developers.deepgram.com).

#### Streaming Inference

The reference repository ships a working WebSocket client at `test/test_websocket.py`. It streams a WAV file at real-time pace and is the fastest way to validate streaming end to end.

```bash
python test/test_websocket.py \
  --url wss://{your-modal-url}/v1/listen
```


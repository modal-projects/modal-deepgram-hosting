# Configure a Deepgram Modal Deployment

## Configure Deepgram

Modal Deepgram deployments are managed by labels. Each label specifies a set of Deepgram TOML files and models. These resources are stored on Modal Volumes when you run

```bash
modal run -m modal_deepgram.modal_resources \
  --label <config-label> \
  --model-links-path <path-to-models-list-txt-file> \
  --deploy-type license-proxy \
  --source-api-config-file <api-toml-file> \
  --source-engine-config-file <engine-toml-file>
```

This will
- download the model weights to a Modal Volume
- pull the appropriate config files from Deepgram's repo
- patch the config files
  - to use `localhost` with the desired ports 
  - specify the Modal Volume mount point for model weights

When calling `modal run -m modal_deepgram.modal_resources`, note that
- the models `.txt` filepath should be local
- the config file names should match one of those found in the [Deepgram self-hosted resources repo](https://github.com/deepgram/self-hosted-resources/tree/main/common)
- the `--deploy-type` argument takes either `license-proxy` or `standard` and will choose the appropriate directory to pull the configs (default is `license-proxy`)

### Edit a Deepgram TOML config

Update config files for a deployment after the initial `modal_deepgram.modal_resources` run by pulling them from the Volume, editing, and uploading back to the Volume.

1. Pull the file locally:

   ```bash
   modal volume get deepgram-cache configs/{label}/api.toml ./api.toml
   ```

2. Edit `./api.toml` in your editor.

3. Push the change back:

   ```bash
   modal volume put deepgram-cache ./api.toml configs/{label}/api.toml
   ```

4. Redeploy with `DEPLOY_LABEL={label} modal deploy -m modal_deepgram.app` to apply.

### Update models

Passing `--model-links-path` wipes `/models/{label}/` and re-downloads every URL in the file.

```bash
modal run -m modal_deepgram.modal_resources \
  --label stt \
  --model-links-path ./model-links.txt
```

## TTS deployment example

The end-to-end flow for an Aura-2 TTS deployment:

1. Save your Aura-2 model links to `./tts-model-links.txt`.

2. Run `prepare_resources` with the `tts` label and Aura-2 config files. For language-specific deployments, swap the polyglot configs for variants like `api.aura-2-en.toml` / `engine.aura-2-en.toml`.

   ```bash
   modal run -m modal_deepgram.modal_resources \
     --label tts \
     --model-links-path ./tts-model-links.txt \
     --source-api-config-file api.aura-2-polyglot.toml \
     --source-engine-config-file engine.aura-2-polyglot.toml
   ```

3. TTS requires two GPUs (one for the generative model, one for the vocoder). Edit the hardware literals at the top of `modal_deepgram/app.py`:

   ```python
   GPU = "L4:2"
   CPU_COUNT = 8
   MEMORY = 64 * 1024
   ```

4. Deploy:

   ```bash
   DEPLOY_LABEL=tts modal deploy -m modal_deepgram.app
   ```

## Set Deepgram release version

To change the Deepgram release, edit `DEEPGRAM_IMAGE_TAG` in `modal_deepgram/deepgram.py` and redeploy the app. This will rebuild the container image.


import modal

from .deepgram import (
    app,
    cache_vol,
    extract_hermes_binary,
    extract_stem_binary,
)
from .shared import (
    MODELS_VOL_NAME,
    API_PORT,
    ENGINE_PORT,
    LICENSE_PROXY_PORT,
    LICENSE_PROXY_STATUS_PORT,
)

models_vol = modal.Volume.from_name(MODELS_VOL_NAME, create_if_missing=True)

MINUTES = 60

# Env vars Deepgram requires for specific source engine configs (e.g. Aura-2
# TTS variants). Persisted to /cache/configs/{label}/env.json during prep so
# the runtime container can apply them on startup without baking them into
# the image.
#
# CUDA_VISIBLE_DEVICES is "0,1" for every variant because each label gets its
# own container with its own GPUs (devices always start at 0). Deepgram's
# upstream docs show "2,3" for ES/polyglot only because their reference
# compose file colocates multiple variants on a 4-GPU node.
SOURCE_ENGINE_CONFIG_TO_ENV: dict[str, dict[str, str]] = {
    "engine.aura-2-en.toml": {
        "IMPELLER_AURA2_T2C_UUID": "15ef8614-52cb-4cd3-a641-d68249c15d53",
        "IMPELLER_AURA2_C2A_UUID": "2e5096c7-7bf1-435e-bbdd-f673f88d0ebd",
        "IMPELLER_AURA2_MAX_BATCH_SIZE": "8",
        "CUDA_VISIBLE_DEVICES": "0,1",
    },
    "engine.aura-2-es.toml": {
        "IMPELLER_AURA2_T2C_UUID": "5d53d105-c6a4-47f5-b670-61adb6e8a880",
        "IMPELLER_AURA2_C2A_UUID": "4d5c93ad-9e20-4ebf-a1f0-0fb88ac73ef5",
        "IMPELLER_AURA2_MAX_BATCH_SIZE": "8",
        "CUDA_VISIBLE_DEVICES": "0,1",
    },
    "engine.aura-2-polyglot.toml": {
        "IMPELLER_AURA2_T2C_UUID": "04975889-c601-4f80-a02f-0f2f9c22deaf",
        "IMPELLER_AURA2_C2A_UUID": "9e94567e-11e7-4619-adbc-d28212194367",
        "IMPELLER_AURA2_MAX_BATCH_SIZE": "8",
        "CUDA_VISIBLE_DEVICES": "0,1",
    },
}


@app.function(
    volumes={
        "/mnt/models": models_vol,
    },
)
def clear_models(label: str, destination: str = "/mnt/models/") -> bool:
    """Delete every file under `{destination}/{label}/` and commit the volume."""
    import shutil
    from pathlib import Path

    dest_dir = Path(destination) / label
    if dest_dir.exists():
        for child in dest_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        print(f"   ✅ Cleared existing models at {dest_dir}")
    else:
        print(f"   (No existing models for label '{label}')")

    models_vol.commit()
    return True


@app.function(
    volumes={
        "/mnt/models": models_vol,
    },
    timeout = 20 * MINUTES,
)
def download_model(
    url: str,
    label: str,
    destination: str = "/mnt/models/",
    chunk_size: int = 8192,
    show_progress: bool = True,
) -> bool:
    """
    Download a model file from a URL to the models volume, overwriting any
    existing file with the same name.

    Args:
        url: URL to download the model from
        label: Label for the subfolder to save the model in
        destination: Base directory to save the model file
        chunk_size: Size of chunks to read at a time
        show_progress: Whether to print progress updates
    
    Returns:
        True if download succeeded, False otherwise
    """
    import urllib.request
    import urllib.error
    from pathlib import Path
    
    try:
        dest_dir = Path(destination) / label
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / Path(url).name

        filename = dest_path.name

        # Open the URL
        with urllib.request.urlopen(url) as response:
            # Get file size if available
            file_size = response.headers.get("Content-Length")
            if file_size:
                file_size = int(file_size)
                file_size_mb = file_size / (1024 * 1024)
                if show_progress:
                    print(f"Downloading {filename} ({file_size_mb:.2f} MB)...")
            else:
                if show_progress:
                    print(f"Downloading {filename}...")

            # Download the file
            downloaded = 0
            with dest_path.open("wb") as out_file:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break

                    out_file.write(chunk)
                    downloaded += len(chunk)

                    # Show progress
                    if show_progress and file_size:
                        progress = (downloaded / file_size) * 100
                        downloaded_mb = downloaded / (1024 * 1024)
                        print(
                            f"\rProgress: {progress:.1f}% ({downloaded_mb:.2f} MB / {file_size_mb:.2f} MB)",
                            end="",
                            flush=True,
                        )

            if show_progress:
                print()  # New line after progress
                print(f"✓ Successfully downloaded: {filename}")

            # Commit the volume to persist the file
            models_vol.commit()
            return True

    except urllib.error.HTTPError as e:
        print(f"✗ HTTP Error {e.code}: {e.reason}")
        return False
    except urllib.error.URLError as e:
        print(f"✗ URL Error: {e.reason}")
        return False
    except Exception as e:
        print(f"✗ Error downloading file: {e}")
        return False


@app.function(
    volumes={
        "/mnt/cache": cache_vol,
    },
    secrets=[modal.Secret.from_name("deepgram")],
)
def download_configs(
    label: str,
    api_config_file: str | None = None,
    engine_config_file: str | None = None,
    deploy_type: str = "license-proxy",
    destination: str = "/mnt/cache/configs",
) -> dict[str, bool]:
    """
    Download Deepgram config files from the self-hosted-resources repository.

    Each of api_config_file and engine_config_file is optional; pass only the
    ones you want to (re)download. license-proxy.toml is refreshed only when
    both api and engine configs are being downloaded together (i.e. a full
    config refresh) and deploy_type is "license-proxy".

    Args:
        label: Label for the subfolder to save configs in
        api_config_file: Name of the API config file to download (e.g., "api.toml").
            Pass None to skip.
        engine_config_file: Name of the Engine config file to download (e.g., "engine.toml").
            Pass None to skip.
        deploy_type: Either "license-proxy" or "standard"
        destination: Base directory to save config files
    
    Returns:
        Dict mapping filename to success status
    """
    import urllib.request
    import urllib.error
    from pathlib import Path
    
    BASE_URL = "https://raw.githubusercontent.com/deepgram/self-hosted-resources/refs/heads/main"
    
    # Convert deploy_type to directory name (license-proxy -> license_proxy_deploy)
    deploy_dir = f"{deploy_type.replace('-', '_')}_deploy"
    
    # Build config files list: (remote_filename, local_filename).
    # Local filename is always api.toml/engine.toml/license-proxy.toml on the
    # volume, regardless of which upstream variant we fetched.
    config_files = []
    if api_config_file:
        config_files.append((api_config_file, "api.toml"))
    if engine_config_file:
        config_files.append((engine_config_file, "engine.toml"))
    # Only refresh license-proxy.toml on a full config refresh, so partial
    # updates don't clobber edits the user made on the volume.
    if deploy_type == "license-proxy" and api_config_file and engine_config_file:
        config_files.append(("license-proxy.toml", "license-proxy.toml"))

    if not config_files:
        return {}
    
    # Create destination directory with label subfolder
    dest_path = Path(destination) / label
    dest_path.mkdir(parents=True, exist_ok=True)
    
    results = {}
    
    for remote_file, local_file in config_files:
        url = f"{BASE_URL}/common/{deploy_dir}/{remote_file}"
        file_path = dest_path / local_file
        
        try:
            print(f"Downloading {remote_file} -> {local_file} from {url}...")
            
            with urllib.request.urlopen(url) as response:
                content = response.read()
                
                with file_path.open("wb") as f:
                    f.write(content)
                
                print(f"✓ Successfully downloaded: {remote_file} -> {local_file} ({len(content)} bytes)")
                results[local_file] = True
                
        except urllib.error.HTTPError as e:
            print(f"✗ HTTP Error downloading {remote_file}: {e.code} {e.reason}")
            results[local_file] = False
        except urllib.error.URLError as e:
            print(f"✗ URL Error downloading {remote_file}: {e.reason}")
            results[local_file] = False
        except Exception as e:
            print(f"✗ Error downloading {remote_file}: {e}")
            results[local_file] = False
    
    # Post-process configs for single-container deployment where all services
    # run on localhost. The upstream configs assume multi-container Docker networking
    # (e.g. hostname "engine", "license-proxy") which we replace with localhost.
    import re

    # Upstream configs assume Engine listens on the API's port (8080) in its own
    # container. In the single-container deployment we move Engine to ENGINE_PORT.
    UPSTREAM_ENGINE_PORT = API_PORT
    UPSTREAM_LP_HOST = f"https://license-proxy:{LICENSE_PROXY_PORT}"
    LOCAL_LP_URL = f"https://localhost:{LICENSE_PROXY_PORT}"
    UPSTREAM_SERVER_URL = (
        f'server_url = ["{UPSTREAM_LP_HOST}", "https://license.deepgram.com"]'
    )

    # --- api.toml ---
    api_toml_path = dest_path / "api.toml"
    if api_toml_path.exists():
        content = api_toml_path.read_text()
        content = re.sub(
            rf'url = "https://[^:]+:{UPSTREAM_ENGINE_PORT}/v2"',
            f'url = "https://localhost:{ENGINE_PORT}/v2"',
            content,
        )
        if deploy_type == "standard":
            content = content.replace(
                UPSTREAM_SERVER_URL,
                'server_url = ["https://license.deepgram.com"]',
            )
        elif deploy_type == "license-proxy":
            content = content.replace(UPSTREAM_LP_HOST, LOCAL_LP_URL)
        api_toml_path.write_text(content)
        print("✓ Patched api.toml for single-container deployment")

    # --- engine.toml ---
    engine_toml_path = dest_path / "engine.toml"
    if engine_toml_path.exists():
        content = engine_toml_path.read_text()
        content = (
            content
            .replace('host = "0.0.0.0"', 'host = "127.0.0.1"')
            .replace(f"port = {UPSTREAM_ENGINE_PORT}", f"port = {ENGINE_PORT}")
            .replace('search_paths = ["/models"]', f'search_paths = ["/models/{label}"]')
        )
        if deploy_type == "standard":
            content = content.replace(
                UPSTREAM_SERVER_URL,
                'server_url = ["https://license.deepgram.com"]',
            )
        elif deploy_type == "license-proxy":
            content = content.replace(UPSTREAM_LP_HOST, LOCAL_LP_URL)
        engine_toml_path.write_text(content)
        print(f"✓ Patched engine.toml for single-container deployment (search_paths=/models/{label})")

    # --- license-proxy.toml ---
    lp_toml_path = dest_path / "license-proxy.toml"
    if lp_toml_path.exists():
        content = lp_toml_path.read_text()
        # Bind to localhost (same container) and move the status port off API_PORT
        # to avoid colliding with the API.
        content = (
            content
            .replace('host = "0.0.0.0"', 'host = "127.0.0.1"')
            .replace(f"status_port = {API_PORT}", f"status_port = {LICENSE_PROXY_STATUS_PORT}")
        )
        lp_toml_path.write_text(content)
        print(
            f"✓ Patched license-proxy.toml for single-container deployment "
            f"(status_port={LICENSE_PROXY_STATUS_PORT})"
        )

    # Persist any source-engine-specific env vars so the runtime container
    # can apply them on startup. Only (re)written when the engine config is
    # being refreshed in this call, to avoid clobbering an existing env.json
    # during an api-only refresh.
    if engine_config_file:
        import json

        env_for_engine = SOURCE_ENGINE_CONFIG_TO_ENV.get(engine_config_file, {})
        env_path = dest_path / "env.json"
        env_path.write_text(json.dumps(env_for_engine, indent=2))
        print(f"✓ Wrote env.json ({len(env_for_engine)} vars) for {engine_config_file}")

    cache_vol.commit()
    return results

@app.local_entrypoint()
def prepare_resources(
    label: str,
    model_links_path: str | None = None,
    source_api_config_file: str | None = None,
    source_engine_config_file: str | None = None,
    deploy_type: str = "license-proxy",
):
    """
    Download Deepgram config files, models, and binaries.

    Every argument other than `label` is optional, so you can re-run this
    entrypoint to update only a subset of resources (e.g. refresh models
    without overwriting TOML edits made on the volume).

    Args:
        label: Label for the subfolder to organize configs and models (e.g., "stt", "tts").
        model_links_path: Path to file containing model URLs (one per line).
            When provided, the label's model directory is wiped and re-populated
            from the file. Omit to leave existing models untouched.
        source_api_config_file: Name of the API config file to download from Deepgram's
            self-hosted-resources repository (e.g., "api.toml", "api.aura-2-en.toml").
            Omit to leave api.toml on the volume untouched.
        source_engine_config_file: Name of the Engine config file to download from Deepgram's
            self-hosted-resources repository (e.g., "engine.toml", "engine.aura-2-en.toml").
            Omit to leave engine.toml on the volume untouched.
        deploy_type: Either "license-proxy" (default) or "standard". Controls
            whether the License Proxy is included. license-proxy.toml is only
            (re)downloaded when both api and engine configs are being refreshed
            in the same call.
    """
    from pathlib import Path

    print(f"Preparing resources with label: {label}")
    print(f"  API config: {source_api_config_file or '(skip)'}")
    print(f"  Engine config: {source_engine_config_file or '(skip)'}")
    print(f"  Model links: {model_links_path or '(skip)'}")
    print(f"  Deploy type: {deploy_type}")

    if model_links_path:
        models_file = Path(model_links_path)
        if not models_file.exists():
            raise FileNotFoundError(f"Model links file not found: {model_links_path}")

        urls = []
        for line in models_file.read_text().strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)

        print(f"Found {len(urls)} model URLs in {model_links_path}")

        # wipe before downloading.
        print(f"\nClearing existing models for label '{label}'...")
        clear_models.remote(label)

        if urls:
            print(f"\nDownloading {len(urls)} models to '{label}/' subfolder...")
            for result in download_model.starmap([(url, label) for url in urls]):
                pass
            print("Model downloads complete.")
        else:
            print("\nNo model URLs found; label now has no models.")
    else:
        print("\nNo --model-links-path provided, leaving existing models untouched.")

    if source_api_config_file or source_engine_config_file:
        print(f"\nDownloading config files to '{label}/' subfolder...")
        config_results = download_configs.remote(
            label=label,
            api_config_file=source_api_config_file,
            engine_config_file=source_engine_config_file,
            deploy_type=deploy_type,
        )
        print(f"Config download results: {config_results}")
    else:
        print("\nNo source config files provided, skipping config downloads.")

    # Binary extraction is idempotent (skips if already cached on the volume),
    # so run it on every invocation to make sure the volume is fully provisioned.
    print("\nExtracting stem binary...")
    extract_stem_binary.remote()

    if deploy_type == "license-proxy":
        print("Extracting hermes (license proxy) binary...")
        extract_hermes_binary.remote()

    print("\n✅ Resource preparation complete.")
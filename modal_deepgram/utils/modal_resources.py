import os
import modal

from .shared import (
    CACHE_PATH,
    MODELS_VOL_NAME,
    CACHE_VOL_NAME,
    API_PORT,
    ENGINE_PORT,
    LICENSE_PROXY_PORT,
    LICENSE_PROXY_STATUS_PORT,
)

# pinned tag for the Deepgram self-hosted containers
# (quay.io/deepgram/self-hosted-{api,engine,license-proxy}).
DEFAULT_DEEPGRAM_IMAGE_TAG = os.environ.get("DEEPGRAM_IMAGE_TAG", "release-260319")

models_vol = modal.Volume.from_name(MODELS_VOL_NAME, create_if_missing=True)
cache_vol = modal.Volume.from_name(CACHE_VOL_NAME, create_if_missing=True)

# API image for extracting stem binary
api_image = (
    modal.Image.from_registry(
        f"quay.io/deepgram/self-hosted-api:{DEFAULT_DEEPGRAM_IMAGE_TAG}",
        secret=modal.Secret.from_name("deepgram"),
        add_python="3.12",
    )
    .entrypoint([])
)

# License proxy image for extracting hermes binary
license_proxy_image = (
    modal.Image.from_registry(
        f"quay.io/deepgram/self-hosted-license-proxy:{DEFAULT_DEEPGRAM_IMAGE_TAG}",
        secret=modal.Secret.from_name("deepgram"),
        add_python="3.12",
    )
    .entrypoint([])
)

app = modal.App("prep-deepgram-resources")

@app.cls(image=api_image, secrets=[modal.Secret.from_name("deepgram")])
class StemExtractor:
    """Extract stem binary from API image"""
    
    @modal.method()
    def get_stem_binary(self):
        """Read and return the stem binary"""
        with open("/bin/stem", "rb") as f:
            return f.read()


@app.cls(image=license_proxy_image, secrets=[modal.Secret.from_name("deepgram")])
class LicenseProxyExtractor:
    """Extract hermes binary from license proxy image"""
    
    @modal.method()
    def get_hermes_binary(self):
        """Read and return the hermes (license proxy) binary"""
        with open("/bin/hermes", "rb") as f:
            return f.read()

# Use Engine image as base (has GPU/CUDA dependencies)
engine_base_image = (
    modal.Image.from_registry(
        f"quay.io/deepgram/self-hosted-engine:{DEFAULT_DEEPGRAM_IMAGE_TAG}",
        secret=modal.Secret.from_name("deepgram"),
    )
    .uv_pip_install("fastapi[standard]", "httpx")
    .entrypoint([])
)

MINUTES = 60
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
    Download a model file from a URL to the models volume.
    
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
        # Create destination directory with label subfolder
        dest_dir = Path(destination) / label
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / Path(url).name

        # if file already exists, don't recopy
        if os.path.exists(dest_path):
            return

        # Get file name for progress display
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
    api_config_file: str = "api.toml",
    engine_config_file: str = "engine.toml",
    deploy_type: str = "license-proxy",
    destination: str = "/mnt/cache/configs",
) -> dict[str, bool]:
    """
    Download Deepgram config files from the self-hosted-resources repository.
    
    Args:
        label: Label for the subfolder to save configs in
        api_config_file: Name of the API config file to download (e.g., "api.toml")
        engine_config_file: Name of the Engine config file to download (e.g., "engine.toml")
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
    
    # Build config files list: (remote_filename, local_filename)
    # Remote filename is what we fetch, local filename is always api.toml/engine.toml
    config_files = [
        (api_config_file, "api.toml"),
        (engine_config_file, "engine.toml"),
    ]
    if deploy_type == "license-proxy":
        config_files.append(("license-proxy.toml", "license-proxy.toml"))
    
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

    cache_vol.commit()
    return results

@app.function(
    volumes={
        CACHE_PATH: cache_vol
    },
)
def extract_stem_binary():
    """Extract the stem binary from the API image and cache it in the volume."""
    binary_path = "/cache/binary/stem"
    try:
        if not os.path.exists(binary_path):
            os.makedirs("/cache/binary", exist_ok=True)
            extractor = StemExtractor()
            data = extractor.get_stem_binary.remote()
            with open(binary_path, "wb") as f:
                f.write(data)
            print(f"   ✅ stem binary fetched and saved ({len(data) / (1024**2):.2f} MB)")
        else:
            print(f"   ✅ stem binary already cached")
        cache_vol.commit()
        return True
    except Exception as e:
        raise RuntimeError(f"extract stem binary: {e}")


@app.function(
    volumes={
        CACHE_PATH: cache_vol
    },
)
def extract_hermes_binary():
    """Extract the hermes binary from the license proxy image and cache it in the volume."""
    binary_path = "/cache/binary/hermes"
    try:
        if not os.path.exists(binary_path):
            os.makedirs("/cache/binary", exist_ok=True)
            extractor = LicenseProxyExtractor()
            data = extractor.get_hermes_binary.remote()
            with open(binary_path, "wb") as f:
                f.write(data)
            print(f"   ✅ hermes binary fetched and saved ({len(data) / (1024**2):.2f} MB)")
        else:
            print(f"   ✅ hermes binary already cached")
        cache_vol.commit()
        return True
    except Exception as e:
        raise RuntimeError(f"extract hermes binary: {e}")

@app.local_entrypoint()
def prepare_resources(
    label: str,
    model_links_path: str,
    source_api_config_file: str,
    source_engine_config_file: str,
    deploy_type: str = "license-proxy",
):
    """
    Download Deepgram config files, models, and binaries.
    
    Args:
        label: Label for the subfolder to organize configs and models (e.g., "stt", "tts").
        model_links_path: Path to file containing model URLs (one per line).
        source_api_config_file: Name of the API config file to download from Deepgram's
            self-hosted-resources repository (e.g., "api.toml", "api.aura-2-en.toml").
        source_engine_config_file: Name of the Engine config file to download from Deepgram's
            self-hosted-resources repository (e.g., "engine.toml", "engine.aura-2-en.toml").
        deploy_type: Either "license-proxy" (default) or "standard".
    """
    from pathlib import Path
    
    print(f"Preparing resources with label: {label}")
    print(f"  API config: {source_api_config_file}")
    print(f"  Engine config: {source_engine_config_file}")
    print(f"  Deploy type: {deploy_type}")
    
    # Parse model URLs from file
    models_file = Path(model_links_path)
    if not models_file.exists():
        raise FileNotFoundError(f"Model links file not found: {model_links_path}")
    
    urls = []
    for line in models_file.read_text().strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    
    print(f"Found {len(urls)} model URLs in {model_links_path}")
    
    # Download models to label subfolder
    if urls:
        print(f"\nDownloading {len(urls)} models to '{label}/' subfolder...")
        for result in download_model.starmap([(url, label) for url in urls]):
            pass
        print("Model downloads complete.")
    else:
        print("\nNo model URLs found, skipping model downloads.")

    # Download and patch config files
    print(f"\nDownloading config files to '{label}/' subfolder...")
    config_results = download_configs.remote(
        label=label,
        api_config_file=source_api_config_file,
        engine_config_file=source_engine_config_file,
        deploy_type=deploy_type,
    )
    print(f"Config download results: {config_results}")

    # Extract binaries
    print("\nExtracting stem binary...")
    extract_stem_binary.remote()

    if deploy_type == "license-proxy":
        print("Extracting hermes (license proxy) binary...")
        extract_hermes_binary.remote()

    print("\n✅ Resource preparation complete.")
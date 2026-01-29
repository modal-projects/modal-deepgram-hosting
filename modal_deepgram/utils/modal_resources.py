import os
import modal

from .const import (
    CACHE_PATH,
    MODELS_VOL_NAME, 
    CACHE_VOL_NAME, 
)

models_vol = modal.Volume.from_name(MODELS_VOL_NAME, create_if_missing=True)
cache_vol = modal.Volume.from_name(CACHE_VOL_NAME, create_if_missing=True)

# API image for extracting stem binary
api_image = (
    modal.Image.from_registry(
        "quay.io/deepgram/self-hosted-api:release-251118",
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

# Use Engine image as base (has GPU/CUDA dependencies)
engine_base_image = (
    modal.Image.from_registry(
        "quay.io/deepgram/self-hosted-engine:release-251118",
        secret=modal.Secret.from_name("deepgram"),
        add_python="3.12",
    )
    .pip_install("fastapi[standard]", "httpx")  # Required for web endpoints and health checks
    .entrypoint([])  # Clear default entrypoint
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
    deploy_type: str = "standard",
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
    
    # Post-process api.toml to update engine URL for local deployment
    import re
    api_toml_path = dest_path / "api.toml"
    if api_toml_path.exists():
        content = api_toml_path.read_text()
        # Match url = "https://<anything>:8080/v2" and replace with localhost:8081
        updated_content = re.sub(
            r'url = "https://[^:]+:8080/v2"',
            'url = "https://localhost:8081/v2"',
            content
        )
        
        # For standard (standalone) deployment, remove license-proxy from server_url
        if deploy_type == "standard":
            updated_content = updated_content.replace(
                'server_url = ["https://license-proxy:8443", "https://license.deepgram.com"]',
                'server_url = ["https://license.deepgram.com"]'
            )
            print("✓ Updated api.toml: server_url changed to direct license server")
        
        api_toml_path.write_text(updated_content)
        print("✓ Updated api.toml: engine URL changed to localhost:8081")
    
    # Post-process engine.toml to update server host/port for local deployment
    engine_toml_path = dest_path / "engine.toml"
    if engine_toml_path.exists():
        content = engine_toml_path.read_text()
        updated_content = content.replace(
            'host = "0.0.0.0"',
            'host = "127.0.0.1"'
        ).replace(
            'port = 8080',
            'port = 8081'
        ).replace(
            'search_paths = ["/models"]',
            f'search_paths = ["/models/{label}"]'
        )
        print(f"✓ Updated engine.toml: search_paths changed to /models/{label}")
        
        # For standard (standalone) deployment, remove license-proxy from server_url
        if deploy_type == "standard":
            updated_content = updated_content.replace(
                'server_url = ["https://license-proxy:8443", "https://license.deepgram.com"]',
                'server_url = ["https://license.deepgram.com"]'
            )
            print("✓ Updated engine.toml: server_url changed to direct license server")
        
        engine_toml_path.write_text(updated_content)
        print("✓ Updated engine.toml: server host/port changed to 127.0.0.1:8081")
    
    # Commit the volume to persist the files
    cache_vol.commit()
    
    return results

@app.function(
    volumes={
        CACHE_PATH: cache_vol
    },
)
def extract_stem_binary():
    try:
        # Check if binary is already cached in volume
        if not os.path.exists("/cache/binary/stem"):
            
            # make dir
            os.makedirs("/cache/binary", exist_ok=True)

            # Not cached, fetch from API image
            extractor = StemExtractor()
            stem_data = extractor.get_stem_binary.remote()
            
            # Save to volume for future restarts
            with open("/cache/binary/stem", "wb") as f:
                f.write(stem_data)

            print(f"   ✅ stem binary fetched and saved to /cache/binary/stem ({len(stem_data) / (1024**2):.2f} MB)")
        else:
            # Already cached, skip extraction
            print(f"   ✅ stem binary already cached in /cache/binary/stem")
        return True
    except Exception as e:
        raise RuntimeError(f"❌ Failed to fetch stem binary: {e}")
        return False

@app.local_entrypoint()
def prepare_resources(
    label: str,
    model_links_path: str,
    source_api_config_file: str,
    source_engine_config_file: str,
    deploy_type: str = "standard",
):
    """
    Download Deepgram config files and models.
    
    Args:
        label: Label for the subfolder to organize configs and models (e.g., "stt", "tts").
        model_links_path: Path to file containing model URLs (one per line).
        source_api_config_file: Name of the API config file to download from Deepgram's
            self-hosted-resources repository (e.g., "api.toml", "api.aura-2-en.toml").
        source_engine_config_file: Name of the Engine config file to download from Deepgram's
            self-hosted-resources repository (e.g., "engine.toml", "engine.aura-2-en.toml").
        deploy_type: Either "license-proxy" or "standard". Defaults to "standard".
    """
    from pathlib import Path
    
    print(f"Preparing resources with label: {label}")
    print(f"  API config: {source_api_config_file}")
    print(f"  Engine config: {source_engine_config_file}")
    
    # Parse model URLs from file
    models_file = Path(model_links_path)
    if not models_file.exists():
        raise FileNotFoundError(f"Model links file not found: {model_links_path}")
    
    urls = []
    for line in models_file.read_text().strip().split("\n"):
        line = line.strip()
        # Skip empty lines and comments
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

    # Download config files to label subfolder
    print(f"\nDownloading config files to '{label}/' subfolder...")
    config_results = download_configs.remote(
        label=label,
        api_config_file=source_api_config_file,
        engine_config_file=source_engine_config_file,
        deploy_type=deploy_type,
    )
    print(f"Config download results: {config_results}")

    # Get API stem binary
    # Download config files
    print("\nExtracting API stem binary...")
    if extract_stem_binary.remote():
        print(f"Successfully extracted API stem binary.")
    else:
        print(f"Error extractring API stem binary.")
   
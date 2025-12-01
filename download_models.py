import modal

app = modal.App("download-models")
models_vol = modal.Volume.from_name("deepgram-models", create_if_missing=True)

import urllib.error
import urllib.request
from pathlib import Path

# UPDATE THIS LIST WITH THE URIS OF THE MODEL FILES YOU WANT TO DOWNLOAD
URLS = [] # uris to remote .dg model files


@app.function(
    volumes={
        "/mnt/models": modal.Volume.from_name(
            "deepgram-models", create_if_missing=True
        ),
    }
)
def download_file(
    url: str,
    destination: str = "/mnt/models/",
    chunk_size: int = 8192,
    show_progress: bool = True,
) -> bool:
    try:
        # Create destination directory if it doesn't exist
        dest_path = Path(destination) / Path(url).name

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


@app.local_entrypoint()
def main():
    for _ in download_file.map(URLS):
        pass
import modal

app = modal.App("download-models")
models_vol = modal.Volume.from_name("deepgram-models", create_if_missing=True)

import urllib.error
import urllib.request
from pathlib import Path

URLS = [
    "https://deepgram-self-hosted.s3.us-east-2.amazonaws.com/bb84d796-10c1-43b8-92ee-9b1384732608/models/nova-3-general.es.batch.cb233499.dg",
    "https://deepgram-self-hosted.s3.us-east-2.amazonaws.com/bb84d796-10c1-43b8-92ee-9b1384732608/models/entity-detector.en.streaming.90424f3a.dg",
    "https://deepgram-self-hosted.s3.us-east-2.amazonaws.com/bb84d796-10c1-43b8-92ee-9b1384732608/models/nova-3-general.en.batch.2187e11a.dg",
    "https://deepgram-self-hosted.s3.us-east-2.amazonaws.com/bb84d796-10c1-43b8-92ee-9b1384732608/models/nova-3-general.multi.batch.841d2347.dg",
    "https://deepgram-self-hosted.s3.us-east-2.amazonaws.com/bb84d796-10c1-43b8-92ee-9b1384732608/models/entity-detector.batch.06bc8f36.dg",
    "https://deepgram-self-hosted.s3.us-east-2.amazonaws.com/bb84d796-10c1-43b8-92ee-9b1384732608/models/nova-3-general.en.streaming.40bd3654.dg",
    "https://deepgram-self-hosted.s3.us-east-2.amazonaws.com/bb84d796-10c1-43b8-92ee-9b1384732608/models/aura-2.voice-pack.en.15ef8614.dg",
    "https://deepgram-self-hosted.s3.us-east-2.amazonaws.com/bb84d796-10c1-43b8-92ee-9b1384732608/models/aura-2.voice-pack.es.5d53d105.dg",
    "https://deepgram-self-hosted.s3.us-east-2.amazonaws.com/bb84d796-10c1-43b8-92ee-9b1384732608/models/nova-3-general.multi.streaming.05d3e56e.dg",
    "https://deepgram-self-hosted.s3.us-east-2.amazonaws.com/bb84d796-10c1-43b8-92ee-9b1384732608/models/aura-2.generator.es.4d5c93ad.dg",
    "https://deepgram-self-hosted.s3.us-east-2.amazonaws.com/bb84d796-10c1-43b8-92ee-9b1384732608/models/diarizer.streaming.6ff6f59c.dg",
    "https://deepgram-self-hosted.s3.us-east-2.amazonaws.com/bb84d796-10c1-43b8-92ee-9b1384732608/models/aura-2.generator.en.2e5096c7.dg",
    "https://deepgram-self-hosted.s3.us-east-2.amazonaws.com/bb84d796-10c1-43b8-92ee-9b1384732608/models/nova-3-general.es.streaming.509be9b5.dg",
    "https://deepgram-self-hosted.s3.us-east-2.amazonaws.com/bb84d796-10c1-43b8-92ee-9b1384732608/models/diarizer.batch.a9f85c2b.dg",
]


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
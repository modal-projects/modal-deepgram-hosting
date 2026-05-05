#!/usr/bin/env python3
import os
import subprocess
import time

import modal

from .shared import (
    API_PORT,
    CACHE_PATH,
    CACHE_VOL_NAME,
    ENGINE_PORT,
    LICENSE_PROXY_PORT,
    LICENSE_PROXY_STATUS_PORT,
)

# Pinned tag for the Deepgram self-hosted containers
# (quay.io/deepgram/self-hosted-{api,engine,license-proxy}). Bump this in
# one place — both the prep workflow and the deployed app read it from here.
DEEPGRAM_IMAGE_TAG = "release-260319"

# Pulled during prep to extract /bin/stem onto the cache volume.
api_image = (
    modal.Image.from_registry(
        f"quay.io/deepgram/self-hosted-api:{DEEPGRAM_IMAGE_TAG}",
        secret=modal.Secret.from_name("deepgram"),
        add_python="3.12",
    )
    .entrypoint([])
)

# Pulled during prep to extract /bin/hermes onto the cache volume.
license_proxy_image = (
    modal.Image.from_registry(
        f"quay.io/deepgram/self-hosted-license-proxy:{DEEPGRAM_IMAGE_TAG}",
        secret=modal.Secret.from_name("deepgram"),
        add_python="3.12",
    )
    .entrypoint([])
)

# Base image for the deployed runtime container. Has GPU/CUDA deps and the
# impeller engine binary.
engine_base_image = (
    modal.Image.from_registry(
        f"quay.io/deepgram/self-hosted-engine:{DEEPGRAM_IMAGE_TAG}",
        secret=modal.Secret.from_name("deepgram"),
    )
    .uv_pip_install("fastapi[standard]", "httpx")
    .entrypoint([])
)


# Modal app for the prep workflow. The extractor classes and binary-extraction
# functions below register on this app, as do the volume / config / model
# helpers in `modal_resources.py` (which imports `app` from here).
app = modal.App("prep-deepgram-resources")

cache_vol = modal.Volume.from_name(CACHE_VOL_NAME, create_if_missing=True)


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


@app.function(volumes={CACHE_PATH: cache_vol})
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


@app.function(volumes={CACHE_PATH: cache_vol})
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


class DeepgramServerBase:
    """Deepgram All-in-One Service: Engine + API + optional License Proxy in a single container.

    Subclasses must set `label` as a class variable. Override `config_dir` and
    `_setup_binaries` to change where configs and binaries are sourced from.
    """
    label: str

    @property
    def config_dir(self):
        """Directory containing toml config files. Override for different sources."""
        return f"{CACHE_PATH}/configs/{self.label}"

    @property
    def _has_license_proxy(self):
        return os.path.exists(f"{self.config_dir}/license-proxy.toml")

    def _setup_binaries(self):
        """Copy pre-cached binaries from the volume to /bin/. Override for other sources."""
        import shutil
        binaries = [("stem", f"{CACHE_PATH}/binary/stem")]
        if self._has_license_proxy:
            binaries.append(("hermes", f"{CACHE_PATH}/binary/hermes"))
        for name, src in binaries:
            dst = f"/bin/{name}"
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o755)
            print(f"   ✅ {name} binary ready")

    @staticmethod
    def _stream_logs(process, label):
        for line in process.stdout:
            print(f"[{label}] {line.rstrip()}")

    def _start_process(self, binary, config, label):
        import threading
        process = subprocess.Popen(
            [binary, "-vvvv", "serve", config],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(
            target=self._stream_logs, args=(process, label), daemon=True
        ).start()
        return process

    def _wait_for_ready(self, url, timeout, label):
        import httpx
        print(f"   Waiting for {label} to be ready...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = httpx.get(url, timeout=2.0)
                if response.status_code == 200:
                    print(f"   ✅ {label} is ready")
                    return
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError(f"❌ {label} failed to start within {timeout} seconds")

    def _warm_up(self):
        import httpx
        for i in range(2):
            try:
                print(f"   Warm-up request {i+1}/2...")
                response = httpx.post(
                    f"http://localhost:{API_PORT}/v1/listen",
                    json={"url": "https://dpgr.am/spacewalk.wav"},
                    params={"model": "nova-3"},
                    timeout=60.0,
                )
                if response.status_code == 200:
                    print(f"   ✅ Warm-up request {i+1}/2 successful ({response.elapsed.total_seconds():.2f}s)")
                else:
                    print(f"   ⚠️  Warm-up request {i+1}/2 returned status {response.status_code}")
            except Exception as e:
                print(f"   ⚠️  Warm-up request {i+1}/2 failed: {e}")
        print("   ✅ Warm-up complete")

    @modal.enter()
    def start_deepgram(self):
        has_lp = self._has_license_proxy
        total = 5 + (1 if has_lp else 0)
        step = 0

        print("=" * 80)
        print("🚀 Starting Deepgram All-in-One Service")
        print("=" * 80)

        step += 1
        print(f"\n[Step {step}/{total}] Setting up binaries...")
        self._setup_binaries()

        step += 1
        print(f"\n[Step {step}/{total}] Verifying binaries...")
        required = [("Engine", "/bin/impeller"), ("API", "/bin/stem")]
        if has_lp:
            required.append(("License Proxy", "/bin/hermes"))
        for name, path in required:
            if not os.path.exists(path):
                raise RuntimeError(f"❌ {name} binary ({path}) not found")
        print(f"   ✅ All binaries found: {', '.join(p for _, p in required)}")

        if has_lp:
            step += 1
            print(f"\n[Step {step}/{total}] Starting License Proxy on localhost:{LICENSE_PROXY_PORT}...")
            self._license_proxy_process = self._start_process(
                "/bin/hermes", f"{self.config_dir}/license-proxy.toml", "LicenseProxy"
            )
            self._wait_for_ready(
                f"http://localhost:{LICENSE_PROXY_STATUS_PORT}/v1/status", 60, "License Proxy"
            )

        step += 1
        print(f"\n[Step {step}/{total}] Starting Engine on localhost:{ENGINE_PORT} (HTTPS)...")
        self._engine_process = self._start_process(
            "/bin/impeller", f"{self.config_dir}/engine.toml", "Engine"
        )

        step += 1
        print(f"\n[Step {step}/{total}] Starting API on localhost:{API_PORT} (HTTP, public)...")
        self._api_process = self._start_process(
            "/bin/stem", f"{self.config_dir}/api.toml", "API"
        )
        self._wait_for_ready(f"http://localhost:{API_PORT}/v1/status", 300, "API")

        step += 1
        print(f"\n[Step {step}/{total}] Warming up inference pipeline...")
        self._warm_up()

        print("\n" + "=" * 80)
        print("✅ Deepgram All-in-One Service Ready!")
        print("=" * 80)
        if has_lp:
            print(f"License Proxy: localhost:{LICENSE_PROXY_PORT} (HTTPS, internal only)")
        print(f"Engine:        localhost:{ENGINE_PORT} (HTTPS with mTLS, internal only)")
        print(f"API:           localhost:{API_PORT} (HTTP, exposed via Modal HTTP server)")
        print("=" * 80)

    @modal.exit()
    def cleanup(self):
        print("\n🛑 Shutting down Deepgram Combined Service...")
        processes = [("API", "_api_process"), ("Engine", "_engine_process")]
        if self._has_license_proxy:
            processes.append(("License Proxy", "_license_proxy_process"))
        for name, attr in processes:
            proc = getattr(self, attr, None)
            if proc:
                print(f"   Stopping {name}...")
                proc.terminate()
                proc.wait(timeout=10)
        print("   ✅ Cleanup complete")


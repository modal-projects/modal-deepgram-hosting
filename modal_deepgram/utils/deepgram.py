#!/usr/bin/env python3
"""
Usage:
  modal deploy deepgram.py
"""
import os
import subprocess
import time

import modal

from .const import *

class DeepgramAPIandEngine:
    """Deepgram All-in-One Service: Engine + API in single container with web_server"""
    label: str
    
    @modal.enter()
    def start_deepgram(self):
        """
        Start both Engine and API processes in the same container.
        
        This method:
        1. Starts Engine process with log streaming
        2. Fetches stem binary from API image (cached in volume)
        3. Starts API process with log streaming
        4. Waits for API to be ready
        5. Performs warm-up requests to initialize the inference pipeline
        """
        import httpx
        import shutil
        import threading
        
        print("=" * 80)
        print("🚀 Starting Deepgram All-in-One Service")
        print("=" * 80)
        
        # Start Engine on port 8081 (internal HTTPS, configured in engine.toml)
        print("\n[Step 1/5] Starting Engine on localhost:8081 (HTTPS)...")
        
        self._engine_process = subprocess.Popen(
            ["/bin/impeller", "-vvvv", "serve", f"{CACHE_PATH}/configs/{self.label}/engine.toml"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Stream Engine logs to Modal
        def stream_engine_logs():
            for line in self._engine_process.stdout:
                print(f"[Engine] {line.rstrip()}")
        
        self._engine_log_thread = threading.Thread(target=stream_engine_logs, daemon=True)
        self._engine_log_thread.start()
        
        # Get stem binary from API image (cached in /binary volume)
        print("\n[Step 2/5] Fetching stem binary from cache...")
        # Copy from volume to /bin (volumes are read-only at runtime)
        shutil.copyfile("/cache/binary/stem", "/bin/stem")
        # Make executable
        os.chmod("/bin/stem", 0o755)
        
        # Verify both binaries are present and executable
        print("\n[Step 3/5] Verifying binaries...")
        if not os.path.exists("/bin/impeller"):
            raise RuntimeError("❌ Engine binary (/bin/impeller) not found")
        if not os.path.exists("/bin/stem"):
            raise RuntimeError("❌ API binary (/bin/stem) not found")
        print("   ✅ Both /bin/impeller and /bin/stem found")
        
        # Start API on port 8080 (publicly exposed via web_server decorator)
        print("\n[Step 4/5] Starting API on port 8080 (HTTP, public)...")
        self._api_process = subprocess.Popen(
            ["/bin/stem", "-vvvv", "serve", f"{CACHE_PATH}/configs/{self.label}/api.toml"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Stream API logs to Modal
        def stream_api_logs():
            for line in self._api_process.stdout:
                print(f"[API] {line.rstrip()}")
        
        self._api_log_thread = threading.Thread(target=stream_api_logs, daemon=True)
        self._api_log_thread.start()
        
        # Wait for API to respond to health check
        print("   Waiting for API to be ready...")
        start_time = time.time()
        while time.time() - start_time < 300:
            try:
                response = httpx.get("http://localhost:8080/v1/status", timeout=2.0)
                if response.status_code == 200:
                    print("   ✅ API is running on port 8080")
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("❌ API failed to start within 5 minutes")
        
        # Warm up the inference pipeline with test transcriptions
        # This initializes GPU kernels and loads model weights into memory
        print("\n[Step 5/5] Warming up inference pipeline...")
        warm_up_url = "http://localhost:8080/v1/listen"
        warm_up_data = {"url": "https://dpgr.am/spacewalk.wav"}
        warm_up_params = {"model": "nova-3"}
        
        for i in range(2):
            try:
                print(f"   Warm-up request {i+1}/2...")
                response = httpx.post(
                    warm_up_url,
                    json=warm_up_data,
                    params=warm_up_params,
                    timeout=60.0
                )
                if response.status_code == 200:
                    print(f"   ✅ Warm-up request {i+1}/2 successful ({response.elapsed.total_seconds():.2f}s)")
                else:
                    print(f"   ⚠️  Warm-up request {i+1}/2 returned status {response.status_code}")
            except Exception as e:
                print(f"   ⚠️  Warm-up request {i+1}/2 failed: {e}")
        
        print("   ✅ Warm-up complete")
        
        print("\n" + "=" * 80)
        print("✅ Deepgram All-in-One Service Ready!")
        print("=" * 80)
        print(f"Engine: localhost:8081 (HTTPS with mTLS, internal only)")
        print(f"API: localhost:8080 (HTTP, exposed via @modal.web_server)")
        print("=" * 80)
        print("\nService is now accepting requests via web_server.")
        print("=" * 80)
    
    @modal.exit()
    def cleanup(self):
        """
        Clean up resources on container shutdown.
        
        Gracefully terminates both Engine and API subprocesses.
        Log streaming threads will automatically stop when processes exit (daemon=True).
        """
        print("\n🛑 Shutting down Deepgram Combined Service...")
        
        # Terminate API process (SIGTERM allows graceful shutdown)
        if hasattr(self, '_api_process') and self._api_process:
            print("   Stopping API...")
            self._api_process.terminate()
            self._api_process.wait(timeout=10)
        
        # Terminate Engine process (SIGTERM allows graceful shutdown)
        if hasattr(self, '_engine_process') and self._engine_process:
            print("   Stopping Engine...")
            self._engine_process.terminate()
            self._engine_process.wait(timeout=10)
        
        print("   ✅ Cleanup complete")

    @modal.web_server(port=8080, startup_timeout=300)
    def web_server(self):
        """
        Passthrough web server that forwards all traffic to the Deepgram API (stem).
        
        This decorator tells Modal to expose port 8080 from the container to the public internet.
        All HTTP/WebSocket traffic is forwarded directly to the stem process running on localhost:8080.
        """
        pass

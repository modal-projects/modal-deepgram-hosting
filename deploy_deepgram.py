#!/usr/bin/env python3
"""
Deploy Deepgram self-hosted API and Engine on Modal.

This deployment uses Modal's unencrypted tunnels to enable mTLS authentication
between the API and Engine services. The Engine creates an unencrypted tunnel
(raw TCP passthrough) that preserves HTTPS and mTLS, allowing the API to
present its client certificate for authentication.

Architecture:
- Engine: Runs on GPU, serves HTTPS with mTLS on port 8080
- API: Connects to Engine via unencrypted tunnel, serves public HTTP API

Requirements:
- Modal secret named "deepgram" with DEEPGRAM_API_KEY
- Modal volumes: "deepgram-models" (contains model files), "deepgram-config" (contains TOML configs)

Deployment:
This file contains two separate Modal apps that can be deployed independently:
  modal deploy deploy_deepgram.py::engine_app
  modal deploy deploy_deepgram.py::api_app

Deploy the engine_app first, then the api_app. The API will automatically
discover and connect to the Engine via the unencrypted tunnel.
"""
import os
import modal
import subprocess
import threading

os.environ["MODAL_IMAGE_BUILDER_VERSION"] = "2025.06"

models_vol = modal.Volume.from_name("deepgram-models", create_if_missing=True)
config_vol = modal.Volume.from_name("deepgram-config", create_if_missing=True)

engine_app = modal.App("deepgram-engine")
engine_image = (
    modal.Image.from_registry(
        "quay.io/deepgram/self-hosted-engine:release-251118",
        secret=modal.Secret.from_name("deepgram"),
        add_python="3.12",  # Required by Modal
    )
    .pip_install("fastapi[standard]")  # Required for @modal.fastapi_endpoint()
    .entrypoint([])  # Preserve Deepgram's default entrypoint
)


@engine_app.cls(
    image=engine_image,
    volumes={"/models": models_vol, "/deepgram-config": config_vol},
    gpu="L4",  # Deepgram Engine requires GPU for inference
    secrets=[modal.Secret.from_name("deepgram")],
    min_containers=1,
)
@modal.concurrent(max_inputs=50)
class Engine:
    """Deepgram Engine: Serves speech-to-text inference via HTTPS with mTLS on port 8080"""
    
    tunnel: modal.Tunnel
    engine_thread: threading.Thread
    shutdown_event: threading.Event

    @modal.enter()
    def start_engine(self):
        """Start the Deepgram Engine and create an unencrypted tunnel"""
        import socket
        import time
        
        self.shutdown_event = threading.Event()

        def run_engine_with_tunnel():
            # Start the Engine process
            print("Starting Deepgram Engine on 0.0.0.0:8080 (HTTPS)...")
            engine_process = subprocess.Popen(
                ["/usr/bin/impeller", "-vvvv", "serve", "/deepgram-config/engine.toml"]
            )
            
            # Wait for Engine to start listening
            start = time.time()
            while time.time() - start < 300:
                try:
                    with socket.create_connection(("localhost", 8080), timeout=2):
                        print("✅ Engine is listening on port 8080")
                        break
                except Exception:
                    time.sleep(1)
            else:
                raise RuntimeError("Engine failed to start")
            
            # Create unencrypted tunnel for raw TCP passthrough (required for mTLS)
            print("Creating unencrypted tunnel to port 8080...")
            with modal.forward(8080, unencrypted=True) as tunnel:
                self.tunnel = tunnel
                print(f"✅ Tunnel created: {tunnel.url}")
                
                # Wait for shutdown
                self.shutdown_event.wait()
                engine_process.terminate()

        self.engine_thread = threading.Thread(target=run_engine_with_tunnel)
        self.engine_thread.start()

    @modal.exit()
    def shutdown(self):
        """Gracefully shut down the Engine"""
        print("Shutting down Engine...")
        self.shutdown_event.set()
        self.engine_thread.join()

    @modal.fastapi_endpoint(label="get-tunnel")
    def get_tunnel(self):
        """Return tunnel information for the API to connect to"""
        if not hasattr(self, 'tunnel') or not self.tunnel:
            raise RuntimeError("Tunnel not initialized")
        
        return self.tunnel



api_app = modal.App("deepgram-api")

api_image = (
    modal.Image.from_registry(
        "quay.io/deepgram/self-hosted-api:release-251118",
        secret=modal.Secret.from_name("deepgram"),
        add_python="3.12",  # Required by Modal for Python-based management
    )
    .entrypoint([])  # Preserve Deepgram's default entrypoint
)


@api_app.function(
    image=api_image.pip_install("httpx", "certifi"),  # certifi provides CA certificates for HTTPS
    volumes={"/models": models_vol, "/deepgram-config": config_vol},
    secrets=[modal.Secret.from_name("deepgram")],
    timeout=10000,
    min_containers=1,
)
@modal.web_server(port=8080)
def api():
    """Deepgram API: Public HTTP endpoint that connects to Engine for inference"""
    import time
    import subprocess
    import re
    from httpx import Client
    import certifi
    
    # Get Engine tunnel information via HTTP request to the Engine's web endpoint
    # This will automatically start the Engine if it's not already running
    print("Fetching Engine tunnel URL...")
    
    engine = modal.Cls.from_name("deepgram-engine", "Engine")()
    engine_endpoint = engine.get_tunnel.get_web_url()

    print(f"Engine endpoint: {engine_endpoint}")
    
    max_retries = 30
    for i in range(max_retries):
        try:
            with Client(timeout=30.0, verify=certifi.where()) as client:
                response = client.get(engine_endpoint)
                response.raise_for_status()
                tunnel_info = response.json()
                if tunnel_info and tunnel_info.get("unencrypted_host") and tunnel_info.get("unencrypted_port"):
                    break
        except Exception as e:
            print(f"Waiting for Engine tunnel... (attempt {i+1}/{max_retries}): {e}")
            time.sleep(5)
    else:
        raise RuntimeError("Could not get Engine tunnel URL after retries")
    
    # Use the unencrypted endpoint for raw TCP passthrough (required for mTLS)
    unencrypted_host = tunnel_info["unencrypted_host"]
    unencrypted_port = tunnel_info["unencrypted_port"]
    
    print(f"✅ Using unencrypted tunnel: {unencrypted_host}:{unencrypted_port}")
    
    # Update API configuration with Engine URL
    with open("/deepgram-config/api.toml", "r") as f:
        api_config = f.read()
    
    new_url = f"https://{unencrypted_host}:{unencrypted_port}/v2"
    
    # Replace the Engine URL in the driver_pool configuration
    api_config_updated = re.sub(
        r'url = "https://[^"]*"',
        f'url = "{new_url}"',
        api_config
    )
    
    # Write to temp file to avoid modifying the original on the volume
    with open("/tmp/api.toml", "w") as f:
        f.write(api_config_updated)
    
    print(f"✅ Configured API to connect to Engine: {new_url}")
    
    # Start the API process
    subprocess.Popen(["/usr/bin/stem", "-vvvv", "serve", "/tmp/api.toml"])
    print("✅ API started and ready to serve requests!")




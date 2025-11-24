"""
Deploy Deepgram using Docker Compose inside a single Modal container.
This solves the inter-service networking issues by running all services
on the same internal Docker network.
"""
import modal
import os

os.environ["MODAL_IMAGE_BUILDER_VERSION"] = "2025.06"

app = modal.App("deepgram-compose")

# Build an image with Docker and docker-compose
deepgram_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "docker.io",
        "docker-compose",
        "curl",
    )
    # Install NVIDIA container toolkit for GPU passthrough
    .run_commands(
        "curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg",
        'curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed "s#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g" | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list',
        "apt-get update",
        "apt-get install -y nvidia-container-toolkit",
    )
)

models_vol = modal.Volume.from_name("deepgram-models", create_if_missing=True)

@app.function(
    image=deepgram_image,
    gpu="L4",
    cpu=4.0,
    memory=16384,  # 16GB RAM
    timeout=86400,  # 24 hours
    secrets=[modal.Secret.from_name("deepgram")],
    volumes={"/models": models_vol},
)
@modal.web_server(8080, startup_timeout=300)
def deepgram_server():
    """
    Run Deepgram services using docker-compose inside this container.
    All services communicate over Docker's internal network.
    """
    import subprocess
    import tempfile
    import os
    
    # Create docker-compose.yml
    compose_content = """
version: '3.8'

services:
  license-proxy:
    image: quay.io/deepgram/self-hosted-license-proxy:release-251118
    command: ["-vvvv", "serve", "/config/license-proxy.toml"]
    environment:
      - DEEPGRAM_API_KEY=${DEEPGRAM_API_KEY}
      - DEEPGRAM_DEPLOYMENT_ORCHESTRATOR=docker-compose
    volumes:
      - ./configs:/config
    networks:
      - deepgram

  engine:
    image: quay.io/deepgram/self-hosted-engine:release-251118
    command: ["-vvvv", "serve", "/config/engine.toml"]
    environment:
      - DEEPGRAM_API_KEY=${DEEPGRAM_API_KEY}
      - DEEPGRAM_DEPLOYMENT_ORCHESTRATOR=docker-compose
    volumes:
      - /models:/models
      - ./configs:/config
    networks:
      - deepgram
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  api:
    image: quay.io/deepgram/self-hosted-api:release-251118
    command: ["-vvvv", "serve", "/config/api.toml"]
    environment:
      - DEEPGRAM_API_KEY=${DEEPGRAM_API_KEY}
      - DEEPGRAM_DEPLOYMENT_ORCHESTRATOR=docker-compose
    volumes:
      - ./configs:/config
    ports:
      - "8080:8080"
    networks:
      - deepgram
    depends_on:
      - engine
      - license-proxy

networks:
  deepgram:
    driver: bridge
"""
    
    # Create temporary directory for compose files
    with tempfile.TemporaryDirectory() as tmpdir:
        compose_file = os.path.join(tmpdir, "docker-compose.yml")
        with open(compose_file, "w") as f:
            f.write(compose_content)
        
        # Copy config files
        os.makedirs(os.path.join(tmpdir, "configs"), exist_ok=True)
        # TODO: Copy your actual config files here
        
        # Start Docker daemon
        print("Starting Docker daemon...")
        subprocess.Popen(["dockerd"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Wait for Docker to be ready
        import time
        for i in range(30):
            try:
                subprocess.run(["docker", "info"], check=True, capture_output=True)
                print("Docker daemon ready")
                break
            except subprocess.CalledProcessError:
                time.sleep(1)
        else:
            raise RuntimeError("Docker daemon failed to start")
        
        # Start services with docker-compose
        print("Starting Deepgram services...")
        subprocess.run(
            ["docker-compose", "up", "-d"],
            cwd=tmpdir,
            check=True,
        )
        
        # Follow logs
        subprocess.run(
            ["docker-compose", "logs", "-f"],
            cwd=tmpdir,
        )


@app.local_entrypoint()
def main():
    """Deploy the Deepgram compose stack"""
    print("Deploying Deepgram with Docker Compose in Modal...")
    print("This will run all services in a single container on a shared network.")
    print("\nServices will be available at:")
    print("- API: https://<your-modal-url>")
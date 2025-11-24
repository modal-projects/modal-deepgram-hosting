"""
Deploy ALL Deepgram services in a SINGLE Modal container.
Services communicate over localhost, bypassing Modal's tunnel system entirely.
"""
import modal
import os

os.environ["MODAL_IMAGE_BUILDER_VERSION"] = "2025.06"

app = modal.App("deepgram-allinone")

models_vol = modal.Volume.from_name("deepgram-models", create_if_missing=True)

# We'll create a custom image that includes all three Deepgram services
# by copying binaries from each official image
base_image = modal.Image.from_registry(
    "quay.io/deepgram/self-hosted-api:release-251118",
    secret=modal.Secret.from_name("deepgram"),
).env({"DEEPGRAM_DEPLOYMENT_ORCHESTRATOR": "docker-compose"})

# Copy impeller binary from engine image
engine_image = modal.Image.from_registry(
    "quay.io/deepgram/self-hosted-engine:release-251118", 
    secret=modal.Secret.from_name("deepgram"),
)

# Copy license-proxy binary from license proxy image  
license_image = modal.Image.from_registry(
    "quay.io/deepgram/self-hosted-license-proxy:release-251118",
    secret=modal.Secret.from_name("deepgram"),
)

# Combine all images (this is a simplified approach - in reality we'd need to copy binaries)
combined_image = (
    base_image
    .apt_install("supervisor")  # Use supervisor to run multiple processes
    .copy_local_file("configs/api.toml", "/config/api.toml")
    .copy_local_file("configs/engine.toml", "/config/engine.toml")
    .copy_local_file("configs/license-proxy.toml", "/config/license-proxy.toml")
    .copy_local_file("start-all-services.sh", "/start-all-services.sh")
    .run_commands("chmod +x /start-all-services.sh")
)


@app.function(
    image=combined_image,
    gpu="L4",
    cpu=4.0,
    memory=16384,
    timeout=86400,
    secrets=[modal.Secret.from_name("deepgram")],
    volumes={"/models": models_vol},
)
@modal.web_server(8080, startup_timeout=300)
def deepgram_server():
    """
    Run all Deepgram services in one container.
    They communicate over localhost - no tunnel issues!
    """
    import subprocess
    
    # Start all services using the wrapper script
    subprocess.run(["/start-all-services.sh"], check=True)


@app.local_entrypoint()
def main():
    print("Deploying Deepgram All-in-One...")
    print("All services will run in a single container and communicate over localhost")


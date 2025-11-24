import os
import modal
import io

os.environ["MODAL_IMAGE_BUILDER_VERSION"] = "2025.06"

models_vol = modal.Volume.from_name("deepgram-models", create_if_missing=True)
config_vol = modal.Volume.from_name("deepgram-config", create_if_missing=True)

app = modal.App("deepgram-web-server-hosting")

impeller_image = (
    modal.Image.from_registry(
        "quay.io/deepgram/self-hosted-engine:release-251118",
        secret=modal.Secret.from_name("deepgram"),
        add_python="3.12",
    ) 
    # .entrypoint([])
)


# license_proxy_image = (
#     modal.Image.from_registry(
#         "quay.io/deepgram/self-hosted-license-proxy:release-251118",
#         secret=modal.Secret.from_name("deepgram"),
#     )
#     .env({"DEEPGRAM_DEPLOYMENT_ORCHESTRATOR": "docker-compose"}) 
# )


@app.function(
    image = impeller_image,
    volumes={"/models": models_vol, "/deepgram-config": config_vol},
    gpu="L4",
    timeout=10000,
    secrets=[modal.Secret.from_name("deepgram")],
    min_containers=1,
)
@modal.web_server(port = 8080)
def impeller():

    import subprocess

    cmd = [
        "serve",
        "/deepgram-config/engine.toml",
    ]
    subprocess.Popen(cmd)


stem_image = (
    modal.Image.from_registry(
        "quay.io/deepgram/self-hosted-api:release-251118",
        add_python="3.12",
        secret=modal.Secret.from_name("deepgram"),
    )
    # .entrypoint([])
)

@app.function(
    image = stem_image,
    volumes={"/models": models_vol, "/deepgram-config": config_vol},
    timeout=10000,
    secrets=[modal.Secret.from_name("deepgram")],
    min_containers=1,
)
@modal.web_server(port = 8080)
def api():

    import subprocess

    impeller_url = impeller.hydrate().get_web_url()
    print(f"Impeller URL: {impeller_url}")
    api_config = (
        open("/deepgram-config/api.toml", "r")
        .read()
        .replace("https://engine:8080/v2", f"{impeller_url}/v2")
    )
    # write back to same file
    with open("/deepgram-config/api.toml", "w") as f:
        f.write(api_config)

    cmd = [
        "serve",
        "/deepgram-config/api.toml",
    ]
    subprocess.Popen(cmd)


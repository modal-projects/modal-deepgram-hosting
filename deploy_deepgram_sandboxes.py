import os
import modal
import io

os.environ["MODAL_IMAGE_BUILDER_VERSION"] = "2025.06"

app = modal.App.lookup("deepgram", create_if_missing=True)
models_vol = modal.Volume.from_name("deepgram-models", create_if_missing=True)
config_vol = modal.Volume.from_name("deepgram-config", create_if_missing=True)


def configure(image: modal.Image) -> modal.Image:
    return image #.env({"DEEPGRAM_DEPLOYMENT_ORCHESTRATOR": "docker-compose"})

with modal.enable_output():
    # with models_vol.batch_upload(force=True) as batch:
    #     batch.put_directory("models/", "/")

    for sandbox in modal.Sandbox.list(app_id=app.app_id):
        print(f"🏖️  Terminating existing sandbox {sandbox.object_id}")
        sandbox.terminate()

    # license_proxy_image = configure(
    #     modal.Image.from_registry(
    #         "quay.io/deepgram/self-hosted-license-proxy:release-251118",
    #         secret=modal.Secret.from_name("deepgram"),
    #     )
    # )
    # print("🏖️  Creating license proxy sandbox")
    # license_proxy = modal.Sandbox.create(
    #     "-vvvv",
    #     "serve",
    #     "/deepgram-config/license-proxy.toml",
    #     unencrypted_ports=[8443],  # Use unencrypted tunnel - license proxy handles HTTPS internally
    #     secrets=[modal.Secret.from_name("deepgram")],
    #     image=license_proxy_image,
    #     volumes={"/deepgram-config": config_vol},
    #     app=app,
    #     timeout=10000,
    # )

    # license_proxy_tunnel = license_proxy.tunnels()[8443]

    # with config_vol.batch_upload(force=True) as batch:
    #     engine_config = (
    #         open("configs/engine.toml", "r")
    #         .read()
    #         .replace('"https://license-proxy:8443"', f'"{license_proxy_tunnel.url}"')
    #     )
    #     batch.put_file(io.BytesIO(engine_config.encode("utf-8")), "/engine.toml")

    # config_vol.commit()

    impeller = modal.Sandbox.create(
        "-vvvv",
        "serve",
        "/deepgram-config/engine.toml",
        encrypted_ports=[8080, 9991],  # Use unencrypted tunnels - Engine handles HTTPS internally
        secrets=[modal.Secret.from_name("deepgram")],
        image=configure(
            modal.Image.from_registry(
                "quay.io/deepgram/self-hosted-engine:release-251118",
                secret=modal.Secret.from_name("deepgram"),
            )
        ),
        volumes={"/models": models_vol, "/deepgram-config": config_vol},
        app=app,
        gpu="L4",
        timeout=10000,
    )

    print("🏖️  Creating impeller sandbox")
    

    impeller_tunnel = impeller.tunnels()[8080]
    impeller_metrics_tunnel = impeller.tunnels()[9991]
    
    print(f"🔗 Impeller tunnel object: {impeller_tunnel}")
    print(f"🔗 Impeller tunnel URL: {impeller_tunnel.url}")
    print(f"🔗 Full Engine URL for API will be: {impeller_tunnel.url}/v2")

    stem_image = configure(
        (
            modal.Image.from_registry(
                "quay.io/deepgram/self-hosted-api:release-251118",
                secret=modal.Secret.from_name("deepgram"),
            )
        )
    )

    print("🏖️  Creating stem sandbox")
    with config_vol.batch_upload(force=True) as batch:
        api_config = (
            open("configs/api.toml", "r")
            .read()
            .replace("https://engine:8080/v2", f"{impeller_tunnel.url}/v2")
            # .replace('"https://license-proxy:8443"', f'"{license_proxy_tunnel.url}"')
        )
        batch.put_file(io.BytesIO(api_config.encode("utf-8")), "/api.toml")

    # config_vol.commit()

    sandbox = modal.Sandbox.create(
        "-vvvv",
        "serve",
        "/deepgram-config/api.toml",
        encrypted_ports=[8080],
        secrets=[modal.Secret.from_name("deepgram")],
        image=stem_image,
        volumes={"/deepgram-config": config_vol},
        app=app,
        timeout=10000,
    )

    stem_tunnel = sandbox.tunnels()[8080]
    # print(f"License Proxy: {license_proxy_tunnel.url}")
    print(f"Impeller: {impeller_tunnel.url}")
    print(f"Impeller Metrics: {impeller_metrics_tunnel.url}")
    print(f"API: {stem_tunnel.url}")
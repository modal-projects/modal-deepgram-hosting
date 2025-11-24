# Deploying Deepgram on Modal using modal-compose

## What is modal-compose?

`modal-compose` is an official tool from Modal that allows you to run Docker Compose files on Modal Sandboxes. Each service in your compose file runs in its own isolated Modal Sandbox, and they communicate via Modal's tunnel system.

## Why This Solves the Networking Problem

1. **Unencrypted Tunnels**: `modal-compose` uses `unencrypted_ports` which do raw TCP forwarding
2. **HTTPS Passthrough**: This allows HTTPS connections between services (Engine and API both serve/expect HTTPS)
3. **Automatic Service Discovery**: Each service gets environment variables with the URLs of dependent services:
   - `$SERVICE_NAME_HOST_0` - the tunnel host
   - `$SERVICE_NAME_PORT_0` - the tunnel port

## Setup

### 1. Install modal-compose

```bash
cd modal-compose
uv sync
```

### 2. Make sure your Deepgram API key is set up in Modal secrets

```bash
modal secret create deepgram DEEPGRAM_API_KEY=<your-key>
```

### 3. Upload your models (if not already done)

The models should be in the `deepgram-models` Modal Volume.

## Deploy

From the project root directory:

```bash
cd /Users/shababo/dev/modal-deepgram-hosting
./modal-compose/.venv/bin/modal-compose -f compose.yml up
```

This will:
1. Create a Modal Sandbox for the license-proxy service
2. Create a Modal Sandbox for the engine service (with GPU)
3. Create a Modal Sandbox for the api service
4. Connect them using Modal tunnels with proper HTTPS support

## Access the API

After deployment, `modal-compose` will print the URLs for each service. Look for the API service URL:

```
🔌 Encrypted URL: https://your-api-url.modal.run
```

You can now make requests to this URL using the Deepgram API.

## How It Works

### Service Communication

1. **License Proxy** starts first and gets a tunnel URL like `https://abc.modal.run`
2. **Engine** starts next:
   - Gets environment variables: `$LICENSE_PROXY_HOST_0` and `$LICENSE_PROXY_PORT_0`
   - The `start-engine.sh` script updates `engine.toml` with the actual license proxy URL
   - Engine listens on HTTPS port 8080
3. **API** starts last:
   - Gets environment variables for both Engine and License Proxy
   - The `start-api.sh` script updates `api.toml` with the actual Engine URL
   - API can now make HTTPS requests to the Engine via the tunnel

### The Wrapper Scripts

- `start-engine.sh`: Updates `engine.toml` with the license proxy URL before starting
- `start-api.sh`: Updates `api.toml` with the engine and license proxy URLs before starting

These scripts bridge the gap between modal-compose's environment variables and Deepgram's TOML configuration files.

## Stopping Services

```bash
./modal-compose/.venv/bin/modal-compose -f compose.yml down
```

## Troubleshooting

### Check Logs

```bash
# Shell into a specific sandbox
modal shell <sandbox-id>

# Check logs
modal logs <sandbox-id>
```

### Common Issues

1. **HTTP/0.9 errors**: This means the tunnel isn't properly configured. Check that services are using `unencrypted_ports`.
2. **502 Bad Gateway**: Services can't reach each other. Verify the wrapper scripts are correctly updating the TOML files.
3. **GPU not found**: Make sure the engine service has the GPU configuration in compose.yml (it does).

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Modal Infrastructure                  │
│                                                          │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────┐   │
│  │ License      │   │ Engine       │   │ API       │   │
│  │ Proxy        │   │ (GPU)        │   │           │   │
│  │ Sandbox      │   │ Sandbox      │   │ Sandbox   │   │
│  │              │   │              │   │           │   │
│  │ HTTPS:8443   │   │ HTTPS:8080   │   │ HTTP:8080 │   │
│  └──────┬───────┘   └──────┬───────┘   └─────┬─────┘   │
│         │                  │                  │         │
│         │ Tunnel (Raw TCP) │                  │         │
│         └──────────────────┴──────────────────┘         │
│           HTTPS traffic preserved through tunnels       │
└─────────────────────────────────────────────────────────┘
```

## Key Differences from Previous Approach

- **Before**: Used `encrypted_ports` which do TLS termination (HTTPS → HTTP)
- **Now**: Uses `unencrypted_ports` for raw TCP forwarding (HTTPS → HTTPS works!)
- **Before**: Services couldn't find each other (separate sandboxes)
- **Now**: modal-compose provides service discovery via environment variables


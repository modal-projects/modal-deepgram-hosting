#!/usr/bin/env python3
"""
Deploy Deepgram self-hosted API and Engine on Modal with authentication.

This deployment uses Modal's unencrypted tunnels to enable mTLS authentication
between the API and Engine services. The Engine creates an unencrypted tunnel
(raw TCP passthrough) that preserves HTTPS and mTLS, allowing the API to
present its client certificate for authentication.

The API includes an authentication proxy that validates API keys before forwarding
requests to the Deepgram API, providing an additional security layer.

The proxy supports both HTTP and WebSocket connections for real-time streaming.

Architecture:
- Engine: Runs on GPU, serves HTTPS with mTLS on port 8080
- API (internal): Connects to Engine via unencrypted tunnel, serves on port 8080
- Auth Proxy (public): FastAPI proxy on port 8081, validates Bearer tokens (HTTP) and query params (WebSocket)

Requirements:
- Modal secret named "deepgram" with DEEPGRAM_API_KEY
- Modal secret named "deepgram-api-auth" with API_KEY (for authentication)
- Modal volumes: "deepgram-models" (contains model files), "deepgram-config" (contains TOML configs)

Deployment:
This file contains two separate Modal apps that can be deployed independently:
  modal deploy deploy_deepgram.py::engine_app
  modal deploy deploy_deepgram.py::api_app

Deploy the engine_app first, then the api_app. The API will automatically
discover and connect to the Engine via the unencrypted tunnel.

Usage:
- HTTP requests: Include header "Authorization: Bearer <your-api-key>"
- WebSocket: Connect to ws://.../v1/listen?token=<your-api-key>&model=nova-2
"""
import os
import modal
import modal.experimental
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
    .entrypoint([])  # Remove Deepgram's default entrypoint
)

REGION = "ap-south"
@engine_app.cls(
    image=engine_image,
    volumes={"/models": models_vol, "/deepgram-config": config_vol},
    gpu="L4",  # Deepgram Engine requires GPU for inference
    secrets=[modal.Secret.from_name("deepgram")],
    min_containers=1,
    region=REGION,
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
    .entrypoint([])  # Remove Deepgram's default entrypoint
    .uv_pip_install("fastapi[standard]", "uvicorn", "httpx", "websockets")
)


@api_app.cls(
    image=api_image.pip_install("certifi"),  # certifi provides CA certificates for HTTPS
    volumes={"/models": models_vol, "/deepgram-config": config_vol},
    secrets=[modal.Secret.from_name("deepgram"), modal.Secret.from_name("deepgram-api-auth")],
    timeout=10000,
    min_containers=1,
    experimental_options={"flash": REGION},
    region=REGION,
)
class API:
    """Deepgram API with authentication proxy"""

    @modal.enter()
    def start_api_server(self):
        """Start Deepgram API and authentication proxy"""
        import time
        import subprocess
        import re
        import httpx
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
        
        # Start the Deepgram API process on port 8080 (internal only)
        print("Starting Deepgram API on port 8080...")
        self._api_process = subprocess.Popen(["/usr/bin/stem", "-vvvv", "serve", "/tmp/api.toml"])

        # Wait for API to be ready
        print("Waiting for Deepgram API to be ready...")
        start_time = time.time()
        while time.time() - start_time < 300:
            try:
                response = httpx.get("http://localhost:8080/v1/status", timeout=2.0)
                if response.status_code == 200:
                    print("✅ Deepgram API is running on port 8080")
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("Deepgram API failed to start")

        # Start authentication proxy on port 8081
        print("Starting authentication proxy on port 8081...")
        self._proxy_thread = threading.Thread(target=self._run_auth_proxy, daemon=True)
        self._proxy_thread.start()
        
        # Wait for proxy to be ready
        start_time = time.time()
        while time.time() - start_time < 60:
            try:
                response = httpx.get("http://localhost:8081/health", timeout=2.0)
                if response.status_code == 200:
                    print("✅ Auth proxy is running on port 8081")
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("Auth proxy failed to start")

        # Expose the auth proxy (not the Deepgram API directly)
        # Flash will handle HTTP/2 from clients and forward as HTTP/1.1 to our proxy
        self._flash_handle = modal.experimental.flash_forward(8081)
        print(f"✅ Public Flash URL: {self._flash_handle.get_container_url()}")
        print("✅ API started and ready to serve authenticated requests!")

    def _run_auth_proxy(self):
        """Run FastAPI authentication proxy with HTTP and WebSocket support"""
        import uvicorn
        from fastapi import FastAPI, Request, HTTPException, Header, Response, WebSocket, WebSocketDisconnect, Query
        import httpx
        import websockets
        import asyncio
        
        app = FastAPI(title="Deepgram Auth Proxy")
        
        # Get API key from Modal secret
        EXPECTED_API_KEY = os.environ.get("API_KEY", "")
        if not EXPECTED_API_KEY:
            raise RuntimeError("API_KEY not found in Modal secret 'deepgram-api-auth'")
        
        print(f"Auth proxy configured with API key authentication (HTTP + WebSocket)")
        
        @app.get("/health")
        async def health():
            """Health check endpoint"""
            return {"status": "ok"}
        
        @app.websocket("/v1/listen")
        async def websocket_proxy(
            websocket: WebSocket,
            authorization: str = Query(None, alias="token")
        ):
            """
            WebSocket proxy for Deepgram streaming transcription.
            Authentication via query parameter: ws://...?token=<your-api-key>
            """
            # Validate authentication from query parameter
            if not authorization or authorization != EXPECTED_API_KEY:
                await websocket.close(code=1008, reason="Invalid or missing token")
                return
            
            # Accept the client connection
            await websocket.accept()
            
            # Build WebSocket URL to Deepgram API
            query_params = dict(websocket.query_params)
            query_params.pop("token", None)  # Remove our auth token
            query_string = "&".join(f"{k}={v}" for k, v in query_params.items())
            deepgram_ws_url = f"ws://localhost:8080/v1/listen"
            if query_string:
                deepgram_ws_url += f"?{query_string}"
            
            try:
                # Connect to Deepgram API
                async with websockets.connect(deepgram_ws_url) as deepgram_ws:
                    # Create bidirectional proxy
                    async def client_to_deepgram():
                        """Forward messages from client to Deepgram"""
                        try:
                            while True:
                                data = await websocket.receive_bytes()
                                await deepgram_ws.send(data)
                        except WebSocketDisconnect:
                            pass
                        except Exception as e:
                            print(f"WebSocket client->Deepgram error: {e}")
                    
                    async def deepgram_to_client():
                        """Forward messages from Deepgram to client"""
                        try:
                            async for message in deepgram_ws:
                                if isinstance(message, bytes):
                                    await websocket.send_bytes(message)
                                else:
                                    await websocket.send_text(message)
                        except Exception as e:
                            print(f"WebSocket Deepgram->client error: {e}")
                    
                    # Run both directions concurrently
                    await asyncio.gather(
                        client_to_deepgram(),
                        deepgram_to_client(),
                        return_exceptions=True
                    )
            
            except Exception as e:
                print(f"WebSocket proxy error: {e}")
                try:
                    await websocket.close(code=1011, reason="Internal server error")
                except:
                    pass
        
        @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        async def proxy_request(
            request: Request,
            path: str,
            authorization: str = Header(None)
        ):
            """
            Proxy all requests to Deepgram API after authentication.
            
            Expected header: Authorization: Bearer <your-api-key>
            """
            # Validate authorization header
            if not authorization:
                raise HTTPException(
                    status_code=401,
                    detail="Missing Authorization header",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            
            if not authorization.startswith("Bearer "):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid Authorization header format. Use: Bearer <api-key>",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            
            # Extract and validate token
            token = authorization.replace("Bearer ", "").strip()
            if token != EXPECTED_API_KEY:
                raise HTTPException(
                    status_code=403,
                    detail="Invalid API key"
                )
            
            # Build target URL
            target_url = f"http://localhost:8080/{path}"
            
            # Prepare headers - exclude hop-by-hop headers and auth
            # Hop-by-hop headers shouldn't be forwarded through proxies
            excluded_headers = {
                "host", "authorization", "connection", "keep-alive",
                "proxy-authenticate", "proxy-authorization", "te", "trailers",
                "transfer-encoding", "upgrade"
            }
            
            headers = {
                key: value for key, value in request.headers.items()
                if key.lower() not in excluded_headers
            }
            
            try:
                # Forward request to Deepgram API
                # Use HTTP/1.1 for local connection (HTTP/2 handled by Flash on public side)
                async with httpx.AsyncClient(
                    timeout=300.0,
                    follow_redirects=True,
                    http2=False  # Force HTTP/1.1 to avoid protocol issues with Deepgram API
                ) as client:
                    response = await client.request(
                        method=request.method,
                        url=target_url,
                        params=request.query_params,
                        headers=headers,
                        content=await request.body(),
                    )
                    
                    # Read the full response content before the client closes
                    content = await response.aread()
                    
                    # Build clean response headers
                    # Only include safe headers that work with HTTP/2
                    response_headers = {}
                    
                    # Content type is essential
                    if content_type := response.headers.get("content-type"):
                        response_headers["content-type"] = content_type
                    
                    # Set content-length explicitly
                    response_headers["content-length"] = str(len(content))
                    
                    # Copy other safe headers if present
                    safe_headers = ["x-dg-request-id", "x-request-id", "cache-control"]
                    for header in safe_headers:
                        if header in response.headers:
                            response_headers[header] = response.headers[header]
                    
                    # Return the complete response
                    return Response(
                        content=content,
                        status_code=response.status_code,
                        headers=response_headers
                    )
            
            except httpx.HTTPError as e:
                print(f"Proxy HTTP error: {type(e).__name__}: {str(e)}")
                raise HTTPException(
                    status_code=502,
                    detail=f"Error connecting to Deepgram API: {str(e)}"
                )
            except Exception as e:
                print(f"Proxy error: {type(e).__name__}: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Internal proxy error: {str(e)}"
                )
        
        # Run uvicorn server
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8081,
            log_level="warning",  # Only show warnings and errors
            access_log=False  # Disable verbose access logs
        )

    @modal.exit()
    def cleanup(self):
        """Clean up resources"""
        print("Shutting down API...")
        if hasattr(self, '_flash_handle') and self._flash_handle:
            self._flash_handle.close()
        if hasattr(self, '_api_process') and self._api_process:
            self._api_process.terminate()
        # Note: proxy thread is daemon, so it will exit automatically




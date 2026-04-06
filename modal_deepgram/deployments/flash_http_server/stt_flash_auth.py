#!/usr/bin/env python3
"""
Flash deployment of Deepgram STT with an authentication proxy layer.

Extends the standard DeepgramSingleContainer with a FastAPI auth proxy on port 8082
that validates Bearer tokens (HTTP) and query param tokens (WebSocket) before
forwarding requests to the internal Deepgram API on port 8080.

Requirements:
- Modal secret "deepgram-api-auth" with API_KEY for client authentication

Usage:
  modal deploy -m modal_deepgram.deployments.flash_http_server.stt_flash_auth

Authentication:
- HTTP: Authorization: Bearer <your-api-key>
- WebSocket: ws://.../v1/listen?token=<your-api-key>&model=nova-2
"""
import os
import modal
import modal.experimental

from ...utils.deepgram import DeepgramSingleContainer
from ...utils.modal_resources import engine_base_image
from ...utils.const import *

models_vol = modal.Volume.from_name(MODELS_VOL_NAME, create_if_missing=True)
cache_vol = modal.Volume.from_name(CACHE_VOL_NAME, create_if_missing=True)

REGION = "us-west"

app = modal.App("deepgram-flash-stt-auth")

auth_engine_image = engine_base_image.pip_install("websockets")


@app.cls(
    image=auth_engine_image,
    volumes={
        MODELS_PATH: models_vol,
        CACHE_PATH: cache_vol,
    },
    gpu="L4",
    secrets=[modal.Secret.from_name(DEEPGRAM_SECRET_NAME), modal.Secret.from_name("deepgram-api-auth")],
    timeout=10000,
    cpu=4,
    memory=32*1024,
    min_containers=1,
    region=REGION,
)
@modal.concurrent(target_inputs=20)
@modal.experimental.http_server(port=8082, proxy_regions=[REGION])
class DeepgramFlashSTTAuth(DeepgramSingleContainer):
    """Deepgram STT via experimental HTTP server with auth proxy."""
    label: str = "stt"

    @modal.enter()
    def start_deepgram(self):
        import threading
        super().start_deepgram()

        print("\n[Auth] Starting authentication proxy on port 8082...")
        self._proxy_thread = threading.Thread(target=self._run_auth_proxy, daemon=True)
        self._proxy_thread.start()
        self._wait_for_ready("http://localhost:8082/health", 60, "Auth Proxy")

        print("\nAuthentication:")
        print("  HTTP:      Authorization: Bearer <your-api-key>")
        print("  WebSocket: ws://.../v1/listen?token=<your-api-key>&model=nova-2")
        print("=" * 80)

    @modal.exit()
    def cleanup(self):
        if hasattr(self, '_uvicorn_server') and self._uvicorn_server:
            print("   Stopping Auth Proxy...")
            self._uvicorn_server.should_exit = True
        super().cleanup()

    def _run_auth_proxy(self):
        """FastAPI authentication proxy with HTTP and WebSocket support."""
        import uvicorn
        import asyncio
        from fastapi import FastAPI, Request, HTTPException, Header, Response, WebSocket, WebSocketDisconnect, Query
        import httpx
        import websockets

        proxy_app = FastAPI(title="Deepgram Auth Proxy")

        EXPECTED_API_KEY = os.environ.get("API_KEY", "")
        if not EXPECTED_API_KEY:
            raise RuntimeError("API_KEY not found in Modal secret 'deepgram-api-auth'")

        print(f"Auth proxy configured with API key authentication (HTTP + WebSocket)")

        @proxy_app.get("/health")
        async def health():
            return {"status": "ok"}

        @proxy_app.websocket("/v1/listen")
        async def websocket_proxy(
            websocket: WebSocket,
            authorization: str = Query(None, alias="token"),
        ):
            """
            WebSocket proxy for streaming transcription.
            Auth via query parameter: ws://...?token=<your-api-key>
            """
            if not authorization or authorization != EXPECTED_API_KEY:
                await websocket.close(code=1008, reason="Invalid or missing token")
                return

            await websocket.accept()

            query_params = dict(websocket.query_params)
            query_params.pop("token", None)
            query_string = "&".join(f"{k}={v}" for k, v in query_params.items())
            deepgram_ws_url = "ws://localhost:8080/v1/listen"
            if query_string:
                deepgram_ws_url += f"?{query_string}"

            try:
                async with websockets.connect(deepgram_ws_url) as deepgram_ws:
                    async def client_to_deepgram():
                        try:
                            while True:
                                data = await websocket.receive_bytes()
                                await deepgram_ws.send(data)
                        except WebSocketDisconnect:
                            pass
                        except Exception as e:
                            print(f"WebSocket client->Deepgram error: {e}")

                    async def deepgram_to_client():
                        try:
                            async for message in deepgram_ws:
                                if isinstance(message, bytes):
                                    await websocket.send_bytes(message)
                                else:
                                    await websocket.send_text(message)
                        except Exception as e:
                            print(f"WebSocket Deepgram->client error: {e}")

                    await asyncio.gather(
                        client_to_deepgram(),
                        deepgram_to_client(),
                        return_exceptions=True,
                    )
            except Exception as e:
                print(f"WebSocket proxy error: {e}")
                try:
                    await websocket.close(code=1011, reason="Internal server error")
                except Exception:
                    pass

        @proxy_app.api_route(
            "/{path:path}",
            methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
        )
        async def proxy_request(
            request: Request,
            path: str,
            authorization: str = Header(None),
        ):
            """Proxy all HTTP requests to Deepgram API after Bearer token validation."""
            if not authorization:
                raise HTTPException(
                    status_code=401,
                    detail="Missing Authorization header",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if not authorization.startswith("Bearer "):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid Authorization header format. Use: Bearer <api-key>",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            token = authorization.replace("Bearer ", "").strip()
            if token != EXPECTED_API_KEY:
                raise HTTPException(status_code=403, detail="Invalid API key")

            target_url = f"http://localhost:8080/{path}"

            excluded_headers = {
                "host", "authorization", "connection", "keep-alive",
                "proxy-authenticate", "proxy-authorization", "te", "trailers",
                "transfer-encoding", "upgrade",
            }
            headers = {
                k: v for k, v in request.headers.items()
                if k.lower() not in excluded_headers
            }

            try:
                async with httpx.AsyncClient(
                    timeout=300.0, follow_redirects=True, http2=False,
                ) as client:
                    response = await client.request(
                        method=request.method,
                        url=target_url,
                        params=request.query_params,
                        headers=headers,
                        content=await request.body(),
                    )
                    content = await response.aread()

                    response_headers = {}
                    if content_type := response.headers.get("content-type"):
                        response_headers["content-type"] = content_type
                    response_headers["content-length"] = str(len(content))
                    for h in ["x-dg-request-id", "x-request-id", "cache-control"]:
                        if h in response.headers:
                            response_headers[h] = response.headers[h]

                    return Response(
                        content=content,
                        status_code=response.status_code,
                        headers=response_headers,
                    )
            except httpx.HTTPError as e:
                print(f"Proxy HTTP error: {type(e).__name__}: {e}")
                raise HTTPException(status_code=502, detail=f"Error connecting to Deepgram API: {e}")
            except Exception as e:
                print(f"Proxy error: {type(e).__name__}: {e}")
                raise HTTPException(status_code=500, detail=f"Internal proxy error: {e}")

        config = uvicorn.Config(
            proxy_app, host="0.0.0.0", port=8082,
            log_level="warning", access_log=False,
        )
        self._uvicorn_server = uvicorn.Server(config)
        asyncio.run(self._uvicorn_server.serve())

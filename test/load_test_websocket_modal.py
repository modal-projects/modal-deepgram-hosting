#!/usr/bin/env python3
"""
Modal-based WebSocket streaming load test for Deepgram API deployment.

This script runs the load test with each client in a separate Modal container,
streaming audio over WebSocket instead of using HTTP POST requests.

Usage:
    modal run load_test/load_test_websocket_modal.py --url <base-url> --api-key <key> --requests 100 --clients 10
"""
import asyncio
import modal
import statistics
import time
from typing import List, Dict, Any

from utils import (
    aggregate_client_results,
    build_results_dict,
    print_error_summary,
    print_results_summary,
    print_test_config,
    spawn_clients_with_stagger,
    wait_for_clients,
)

app = modal.App("deepgram-websocket-load-test")

# Image with dependencies
image = modal.Image.debian_slim().pip_install("websockets", "httpx")


@app.function(
    image=image,
    timeout=3600,  # 1 hour timeout for long tests
)
async def run_websocket_client(
    client_id: int,
    base_url: str,
    api_key: str,
    requests_per_client: int,
    model: str,
    audio_url: str
):
    """Run a single client that streams audio via WebSocket in its own container"""
    import websockets
    import json
    import urllib.request
    import tempfile
    import os
    from datetime import datetime
    
    # Track results for this client
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    
    print(f"[Client {client_id}] Starting {requests_per_client} WebSocket streams in container...")
    
    # Download audio file once
    print(f"[Client {client_id}] Downloading audio from {audio_url}...")
    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        urllib.request.urlretrieve(audio_url, temp_file.name)
        audio_file = temp_file.name
        print(f"[Client {client_id}] ✅ Audio downloaded")
    except Exception as e:
        print(f"[Client {client_id}] ❌ Failed to download audio: {e}")
        return {
            "client_id": client_id,
            "results": [],
            "errors": [{"error": f"Failed to download audio: {e}"}] * requests_per_client
        }
    
    # Read audio data once
    with open(audio_file, "rb") as f:
        audio_data = f.read()
    
    async def stream_audio_once(request_num: int) -> Dict[str, Any]:
        """Stream audio file once via WebSocket"""
        start_time = time.time()
        
        # Use provided api_key if available, otherwise use 'a'
        token = api_key if api_key else "a"
        
        # Build WebSocket URL with authentication
        ws_url = f"wss://{base_url}/v1/listen?token={token}&model={model}&interim_results=false&punctuate=true"
        
        try:
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as websocket:
                # Task to send audio data
                async def send_audio():
                    try:
                        # Send audio in chunks to simulate streaming
                        chunk_size = 8192
                        
                        for i in range(0, len(audio_data), chunk_size):
                            chunk = audio_data[i:i + chunk_size]
                            await websocket.send(chunk)
                            # Small delay to avoid overwhelming the server
                            await asyncio.sleep(0.01)
                        
                        # Send close message to signal end of audio
                        await websocket.send(json.dumps({"type": "CloseStream"}))
                        
                    except Exception as e:
                        raise Exception(f"Error sending audio: {e}")
                
                # Task to receive transcription results
                async def receive_results():
                    try:
                        final_transcripts = []
                        received_metadata = False
                        
                        async for message in websocket:
                            result = json.loads(message)
                            msg_type = result.get("type")
                            
                            if msg_type == "Results":
                                is_final = result.get("is_final", False)
                                channel = result.get("channel", {})
                                alternatives = channel.get("alternatives", [])
                                
                                if alternatives and is_final:
                                    transcript = alternatives[0].get("transcript", "")
                                    if transcript:
                                        final_transcripts.append(transcript)
                            
                            elif msg_type == "Metadata":
                                received_metadata = True
                                break
                        
                        if received_metadata:
                            await websocket.close()
                        
                        return " ".join(final_transcripts)
                        
                    except Exception as e:
                        raise Exception(f"Error receiving results: {e}")
                
                # Run both tasks concurrently
                send_task = asyncio.create_task(send_audio())
                receive_task = asyncio.create_task(receive_results())
                
                await send_task
                transcript = await receive_task
                
                elapsed = time.time() - start_time
                
                return {
                    "client_id": client_id,
                    "request_num": request_num,
                    "status_code": 200,
                    "elapsed": elapsed,
                    "success": True,
                    "transcript_length": len(transcript),
                    "timestamp": datetime.now().isoformat()
                }
                
        except websockets.exceptions.InvalidStatusCode as e:
            elapsed = time.time() - start_time
            return {
                "client_id": client_id,
                "request_num": request_num,
                "status_code": e.status_code,
                "elapsed": elapsed,
                "success": False,
                "error": f"WebSocket connection failed: {e.status_code}",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            elapsed = time.time() - start_time
            return {
                "client_id": client_id,
                "request_num": request_num,
                "status_code": None,
                "elapsed": elapsed,
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    # Make all requests for this client
    for request_num in range(requests_per_client):
        result = await stream_audio_once(request_num)
        
        if result["success"]:
            results.append(result)
        else:
            errors.append(result)
        
        # Print progress every 5 requests (WebSocket is slower than HTTP)
        if (request_num + 1) % 5 == 0:
            success_count = len(results)
            print(f"[Client {client_id}] Progress: {request_num + 1}/{requests_per_client} "
                  f"(✓ {success_count}, ✗ {len(errors)})")
    
    print(f"[Client {client_id}] ✅ Completed {len(results)}/{requests_per_client} successful streams!")
    
    # Clean up temp file
    try:
        os.unlink(audio_file)
    except:
        pass
    
    # Return results from this client
    return {
        "client_id": client_id,
        "results": results,
        "errors": errors
    }


@app.function(image=image)
async def orchestrate_websocket_load_test(
    base_url: str,
    api_key: str,
    requests_per_client: int,
    num_clients: int,
    stagger_delay: float,
    model: str,
    audio_url: str
):
    """Orchestrate the WebSocket load test by spawning multiple client containers"""
    
    print_test_config(
        test_name="Deepgram WebSocket Load Test",
        url=f"wss://{base_url}",
        model=model,
        audio_url=audio_url,
        num_clients=num_clients,
        requests_per_client=requests_per_client,
        stagger_delay=stagger_delay,
        request_label="streams",
    )
    
    start_time = time.time()
    
    # Spawn clients with staggered delays
    client_calls = await spawn_clients_with_stagger(
        client_fn=run_websocket_client,
        num_clients=num_clients,
        stagger_delay=stagger_delay,
        client_kwargs={
            "base_url": base_url,
            "api_key": api_key,
            "requests_per_client": requests_per_client,
            "model": model,
            "audio_url": audio_url,
        },
    )
    
    # Wait for all clients to complete
    client_results = await wait_for_clients(client_calls)
    total_elapsed = time.time() - start_time
    
    # Aggregate results
    all_results, all_errors = aggregate_client_results(client_results)
    
    # Calculate extra metrics for WebSocket (average transcript length)
    extra_metrics = None
    if all_results:
        avg_transcript_length = statistics.mean([r.get("transcript_length", 0) for r in all_results])
        extra_metrics = {"📝 Average transcript length": f"{avg_transcript_length:.0f} characters"}
    
    print_results_summary(all_results, all_errors, total_elapsed, request_label="streams", extra_metrics=extra_metrics)
    print_error_summary(all_errors)
    print("=" * 80)
    
    return build_results_dict(all_results, all_errors, total_elapsed)


@app.local_entrypoint()
async def main(
    url: str,
    api_key: str = "",
    requests: int = 20,  # Lower default for WebSocket (slower than HTTP)
    clients: int = 5,    # Lower default for WebSocket
    stagger: float = 3.0,  # Longer stagger for WebSocket
    model: str = "nova-3",
    audio_url: str = "https://dpgr.am/spacewalk.wav"
):
    """
    Run WebSocket streaming load test in Modal cloud with each client in a separate container.
    
    Usage:
        # With API key (uses token=YOUR_KEY)
        modal run load_test_websocket_modal.py --url your-api.modal.direct --api-key YOUR_KEY
        
        # Without API key (uses token=a)
        modal run load_test_websocket_modal.py --url your-api.modal.direct
        
        # Custom load
        modal run load_test_websocket_modal.py --url your-api.modal.direct --api-key YOUR_KEY --clients 10 --requests 50
        
        # Fast ramp-up
        modal run load_test_websocket_modal.py --url your-api.modal.direct --api-key YOUR_KEY --stagger 1.0
    
    Note: URL should be just the hostname without wss:// or /v1/listen
    """
    print("🚀 Starting distributed WebSocket load test in Modal cloud...")
    print(f"📦 Each of {clients} clients will stream audio in its own container")
    if api_key:
        print(f"🔐 Using token authentication with provided API key")
    else:
        print(f"🔐 Using token=a authentication (no API key provided)")
    print("You can close this terminal - the test will continue running in Modal.\n")
    
    result = await orchestrate_websocket_load_test.remote.aio(
        base_url=url,
        api_key=api_key,
        requests_per_client=requests,
        num_clients=clients,
        stagger_delay=stagger,
        model=model,
        audio_url=audio_url
    )
    
    print("\n✅ WebSocket load test completed!")
    print(f"Success rate: {result['success_rate']:.1%}")
    print(f"Throughput: {result['throughput']:.2f} streams/s")


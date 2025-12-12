#!/usr/bin/env python3
"""
Test WebSocket streaming for authenticated Deepgram API.

Usage:
    python test_websocket.py <flash-url> <api-key> [audio-file]
    
Examples:
    # Use default audio (https://dpgr.am/spacewalk.wav)
    python test_websocket.py modal-labs-shababo-dev--deepgram-api-api.ap-south.modal.direct your-api-key
    
    # Use custom audio file
    python test_websocket.py modal-labs-shababo-dev--deepgram-api-api.ap-south.modal.direct your-api-key bueller.wav
"""
import asyncio
import websockets
import json
import sys
import urllib.request
import tempfile
import os
import wave


async def stream_audio(base_url: str, api_key: str, audio_source: str):
    """Stream audio file to Deepgram via WebSocket and print transcription results"""
    
    # Download audio if it's a URL
    audio_file = audio_source
    temp_file = None
    
    if audio_source.startswith(('http://', 'https://')):
        print(f"Downloading audio from {audio_source}...")
        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
            urllib.request.urlretrieve(audio_source, temp_file.name)
            audio_file = temp_file.name
            print(f"✅ Audio downloaded to {audio_file}")
        except Exception as e:
            print(f"❌ Failed to download audio: {e}")
            return
    
    # Build WebSocket URL with authentication
    # Enable interim_results for real-time transcription and utterance_end_ms for end detection
    ws_url = f"wss://{base_url}/v1/listen?token={api_key}&model=nova-3&interim_results=true&utterance_end_ms=1000&punctuate=true"
    
    print(f"Connecting to {ws_url.replace(api_key, '***')}...")
    
    try:
        async with websockets.connect(ws_url) as websocket:
            print("✅ WebSocket connected!")
            
            # Task to send audio data
            async def send_audio():
                try:
                    # Read audio file and get properties
                    with wave.open(audio_file, 'rb') as wav_file:
                        sample_rate = wav_file.getframerate()
                        n_channels = wav_file.getnchannels()
                        sample_width = wav_file.getsampwidth()
                        
                        # Calculate bytes per second
                        bytes_per_second = sample_rate * n_channels * sample_width
                        
                        print(f"Audio properties: {sample_rate}Hz, {n_channels} channel(s), {sample_width*8}-bit")
                        
                        # Reopen as binary to read all data
                        wav_file.close()
                    
                    with open(audio_file, "rb") as f:
                        audio_data = f.read()
                    
                    # Send in chunks to simulate real-time streaming
                    chunk_size = 8192
                    chunks_sent = 0
                    
                    print(f"Streaming audio file ({len(audio_data)} bytes) in real-time...")
                    
                    for i in range(0, len(audio_data), chunk_size):
                        chunk = audio_data[i:i + chunk_size]
                        await websocket.send(chunk)
                        chunks_sent += 1
                        
                        # Calculate delay based on actual chunk duration
                        chunk_duration = len(chunk) / bytes_per_second
                        await asyncio.sleep(chunk_duration)
                    
                    print(f"✅ Sent {chunks_sent} audio chunks")
                    
                    # Send close message to signal end of audio
                    await websocket.send(json.dumps({"type": "CloseStream"}))
                    
                except FileNotFoundError:
                    print(f"❌ Audio file not found: {audio_file}")
                except Exception as e:
                    print(f"❌ Error sending audio: {e}")
            
            # Task to receive transcription results
            async def receive_results():
                try:
                    print("\nReceiving transcription results:")
                    print("-" * 60)
                    
                    interim_count = 0
                    final_count = 0
                    received_metadata = False
                    
                    try:
                        # Keep receiving until we get the Metadata message (signals end of stream)
                        async for message in websocket:
                            result = json.loads(message)
                            
                            # Check message type first
                            msg_type = result.get("type")
                            
                            if msg_type == "Results":
                                # This is a transcription result
                                is_final = result.get("is_final", False)
                                speech_final = result.get("speech_final", False)
                                
                                # Safely access channel and alternatives
                                channel = result.get("channel", {})
                                alternatives = channel.get("alternatives", [])
                                
                                if alternatives and len(alternatives) > 0:
                                    transcript = alternatives[0].get("transcript", "")
                                    
                                    if transcript:
                                        if is_final:
                                            final_count += 1
                                            if speech_final:
                                                print(f"[FINAL {final_count}] 🎤: {transcript}")
                                            else:
                                                print(f"[FINAL {final_count}]: {transcript}")
                                        else:
                                            interim_count += 1
                                            print(f"[interim {interim_count}]: {transcript}")
                            
                            elif msg_type == "Metadata":
                                duration = result.get('duration', 'N/A')
                                print(f"[INFO] Metadata received (duration: {duration}s)")
                                received_metadata = True
                                # Metadata is the last message from Deepgram, break after receiving it
                                break
                            
                            elif msg_type == "UtteranceEnd":
                                print(f"[INFO] Utterance ended at {result.get('last_word_end', 0):.2f}s")
                            elif msg_type == "SpeechStarted":
                                print(f"[INFO] Speech started at {result.get('timestamp', 0):.2f}s")
                            elif msg_type:
                                print(f"[INFO] {msg_type}")
                        
                        if received_metadata:
                            print("\n✅ Stream complete, closing connection...")
                            await websocket.close()
                    
                    except websockets.exceptions.ConnectionClosed:
                        print("\n✅ WebSocket connection closed by server")
                    
                    print("-" * 60)
                    print(f"✅ Received {final_count} final results, {interim_count} interim results")
                    
                except Exception as e:
                    print(f"\n❌ Error receiving results: {e}")
            
            # Run both tasks concurrently
            # Wait for send to complete first, then receive will continue until connection closes
            await asyncio.gather(
                send_audio(),
                receive_results()
            )
    
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"❌ WebSocket connection failed with status {e.status_code}")
        if e.status_code == 401:
            print("   Authentication failed - check your API key")
        elif e.status_code == 403:
            print("   Forbidden - invalid API key")
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
    finally:
        # Clean up temporary file if it was created
        if temp_file:
            try:
                os.unlink(temp_file.name)
            except:
                pass


def main():
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        print("Usage: python test_websocket.py <flash-url> <api-key> [audio-file]")
        print("\nExamples:")
        print("  # Use default audio (https://dpgr.am/spacewalk.wav)")
        print("  python test_websocket.py modal-labs-shababo-dev--deepgram-api-api.ap-south.modal.direct your-api-key")
        print("\n  # Use custom audio file")
        print("  python test_websocket.py modal-labs-shababo-dev--deepgram-api-api.ap-south.modal.direct your-api-key bueller.wav")
        sys.exit(1)
    
    base_url = sys.argv[1]
    api_key = sys.argv[2]
    audio_source = sys.argv[3] if len(sys.argv) == 4 else "https://dpgr.am/spacewalk.wav"
    
    print("=" * 60)
    print("🔐 Deepgram WebSocket Streaming Test")
    print("=" * 60)
    print(f"Base URL: {base_url}")
    print(f"Audio source: {audio_source}")
    print("=" * 60)
    print()
    
    asyncio.run(stream_audio(base_url, api_key, audio_source))


if __name__ == "__main__":
    main()


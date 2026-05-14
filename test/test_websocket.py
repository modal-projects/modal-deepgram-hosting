#!/usr/bin/env python3
"""Smoke test for a deployed Deepgram-on-Modal WebSocket endpoint.

Streams a WAV file at real-time pace and prints transcripts as they arrive.

Usage:
    python test/test_websocket.py \
        --url wss://your-api.modal.direct/v1/listen \
        [--audio path/or/url.wav]
"""
import argparse
import asyncio
import io
import json
import sys
import time
import urllib.request
import wave
from pathlib import Path

import websockets

DEFAULT_AUDIO = "https://dpgr.am/spacewalk.wav"
CHUNK_SIZE = 8192


def load_audio(source: str) -> tuple[bytes, int]:
    """Return (wav bytes, bytes-per-second) for a local path or http(s) URL."""
    if source.startswith(("http://", "https://")):
        print(f"Downloading audio from {source}...")
        with urllib.request.urlopen(source) as resp:
            audio = resp.read()
    else:
        audio = Path(source).read_bytes()

    with wave.open(io.BytesIO(audio), "rb") as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()

    bytes_per_second = sample_rate * channels * sample_width
    print(f"Audio: {sample_rate}Hz, {channels} channel(s), {sample_width * 8}-bit")
    return audio, bytes_per_second


async def send_audio(ws, audio: bytes, bytes_per_second: int) -> None:
    """Send audio in chunks paced to real-time, then signal end of stream."""
    print(f"Streaming {len(audio)} bytes...")
    for i in range(0, len(audio), CHUNK_SIZE):
        chunk = audio[i : i + CHUNK_SIZE]
        await ws.send(chunk)
        await asyncio.sleep(len(chunk) / bytes_per_second)
    await ws.send(json.dumps({"type": "CloseStream"}))


async def print_transcripts(ws) -> None:
    """Print transcripts as they arrive; return after the final Metadata message."""
    print("\nTranscripts:")
    print("-" * 60)
    async for message in ws:
        result = json.loads(message)
        msg_type = result.get("type")

        if msg_type == "Results":
            alternatives = result.get("channel", {}).get("alternatives", [])
            transcript = alternatives[0].get("transcript", "") if alternatives else ""
            if transcript:
                tag = "FINAL  " if result.get("is_final") else "interim"
                print(f"[{tag}] {transcript}")

        elif msg_type == "Metadata":
            print("-" * 60)
            print(f"Stream complete (duration: {result.get('duration', 'N/A')}s)")
            return


async def stream(url: str, audio_source: str, model: str) -> None:
    audio, bytes_per_second = load_audio(audio_source)
    ws_url = f"{url}?model={model}&interim_results=true&punctuate=true"

    print(f"Connecting to {url} ...")
    started = time.time()
    try:
        async with websockets.connect(ws_url) as ws:
            await asyncio.gather(
                send_audio(ws, audio, bytes_per_second),
                print_transcripts(ws),
            )
    except websockets.exceptions.InvalidStatusCode as e:
        sys.exit(f"WebSocket connection failed (HTTP {e.status_code}). Check --url.")

    print(f"Done in {time.time() - started:.2f}s")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Full WebSocket URL, e.g. wss://your-api.modal.direct/v1/listen",
    )
    parser.add_argument(
        "--audio",
        default=DEFAULT_AUDIO,
        help=f"Local WAV path or http(s) URL (default: {DEFAULT_AUDIO})",
    )
    parser.add_argument("--model", default="nova-3", help="Deepgram model (default: nova-3)")
    args = parser.parse_args()

    asyncio.run(stream(args.url, args.audio, args.model))


if __name__ == "__main__":
    main()

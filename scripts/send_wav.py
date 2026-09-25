import argparse
import asyncio
import json
from pathlib import Path

import websockets

from genesis.wav import CHUNK_BYTES, iter_chunks, load_pcm_wav


async def send(path: Path, url: str, source_lang: str, target_lang: str) -> None:
    pcm = load_pcm_wav(path)
    hello = {
        "type": "hello",
        "source_lang": source_lang,
        "target_lang": target_lang,
        "sample_rate_hz": 16_000,
        "channels": 1,
        "sample_format": "s16le",
    }
    async with websockets.connect(url) as socket:
        await socket.send(json.dumps(hello))
        for chunk in iter_chunks(pcm):
            await socket.send(chunk)
            await asyncio.sleep(len(chunk) / CHUNK_BYTES * 0.1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manda un WAV al ingest de Genesis")
    parser.add_argument("wav", type=Path)
    parser.add_argument("--session", default="sala-1")
    parser.add_argument("--source", default="es")
    parser.add_argument("--target", default="en")
    parser.add_argument("--url", default="")
    args = parser.parse_args()
    if not args.wav.is_file():
        raise SystemExit(f"No existe el archivo: {args.wav}")
    url = args.url or f"ws://127.0.0.1:8000/v1/sessions/{args.session}/audio"
    asyncio.run(send(args.wav, url, args.source, args.target))


if __name__ == "__main__":
    main()

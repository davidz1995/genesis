import json

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from genesis.bus import SubtitleBus
from genesis.engine import GeminiNotConfigured, SubtitleEngine
from genesis.models import Hello, validate_pcm_chunk, validate_session_id

HELLO_MAX_BYTES = 4_096


async def ingest_audio(
    websocket: WebSocket,
    session_id: str,
    engine: SubtitleEngine,
    bus: SubtitleBus,
) -> None:
    try:
        validate_session_id(session_id)
    except ValueError:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        hello = await _read_hello(websocket)
    except ValueError:
        await websocket.close(code=1008)
        return

    try:
        await engine.start(session_id, hello, bus)
    except GeminiNotConfigured:
        await websocket.close(code=1011)
        return
    except Exception:
        await websocket.close(code=1011)
        return

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            payload = message.get("bytes")
            if payload is None:
                await websocket.close(code=1008)
                return
            validate_pcm_chunk(payload)
            await engine.push_audio(session_id, payload)
    except WebSocketDisconnect:
        return
    except ValueError:
        await websocket.close(code=1008)
    finally:
        await engine.stop(session_id)


async def _read_hello(websocket: WebSocket) -> Hello:
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise ValueError("conexión cerrada antes del hello")
    raw = message.get("text")
    if raw is None or len(raw.encode()) > HELLO_MAX_BYTES:
        raise ValueError("hello inválido")
    try:
        hello = Hello.model_validate(json.loads(raw))
        hello.validate_audio_format()
    except (json.JSONDecodeError, ValidationError, ValueError):
        raise ValueError("hello inválido") from None
    return hello

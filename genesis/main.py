from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import HTMLResponse

from genesis.bus import InProcessBus
from genesis.engine import GeminiEngine
from genesis.models import validate_session_id
from genesis.routes.audio import ingest_audio
from genesis.routes.stream import stream_subtitles
from genesis.settings import load_settings

app = FastAPI(title="Genesis Subtitling")
_settings = load_settings()
app.state.bus = InProcessBus()
app.state.engine = GeminiEngine(_settings.gemini_api_key, _settings.gemini_model)
_OVERLAY = (Path(__file__).parent / "overlay.html").read_text(encoding="utf-8")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/v1/sessions/{session_id}/audio")
async def audio(websocket: WebSocket, session_id: str) -> None:
    await ingest_audio(websocket, session_id, app.state.engine, app.state.bus)


@app.get("/v1/sessions/{session_id}/subtitles")
async def subtitles(session_id: str):
    return await stream_subtitles(session_id, app.state.bus)


@app.get("/overlay", response_class=HTMLResponse)
async def overlay(session_id: str) -> HTMLResponse:
    try:
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return HTMLResponse(_OVERLAY)

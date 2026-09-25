import asyncio
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from genesis.bus import InProcessBus
from genesis.engine import _Clock, event_from_server_content
from genesis.main import app
from genesis.models import Hello, SubtitleEvent, validate_pcm_chunk
from genesis.tracing import SessionTrace, usage_details_from_gemini
from genesis.wav import iter_chunks, load_pcm_wav


def test_wav_pcm_se_parte_en_chunks_de_100ms(tmp_path: Path):
    path = tmp_path / "voz.wav"
    pcm = b"\x00\x01" * 4000
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16_000)
        wav_file.writeframes(pcm)
    loaded = load_pcm_wav(path)
    chunks = list(iter_chunks(loaded))
    assert loaded == pcm
    assert chunks[0] == pcm[:3200]
    assert b"".join(chunks) == pcm


def test_wav_de_44100_se_baja_a_16k(tmp_path: Path):
    path = tmp_path / "voz.wav"
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(44_100)
        wav_file.writeframes(b"\x00\x01" * 441)
    loaded = load_pcm_wav(path)
    assert len(loaded) == 320


def test_langfuse_anota_el_final_y_no_rompe_si_falla():
    class Span:
        def __init__(self):
            self.updates = []
            self.ended = False

        def start_observation(self, **kwargs):
            return self

        def update(self, **kwargs):
            self.updates.append(kwargs)

        def end(self):
            self.ended = True

    span = Span()
    trace = SessionTrace(span)
    trace._model = "gemini-3.5-live-translate-preview"
    trace.note_usage(SimpleNamespace(prompt_token_count=1200, response_token_count=80))
    event = SubtitleEvent(
        session_id="sala-1",
        seq=1,
        start_ms=0,
        end_ms=1000,
        source_lang="en",
        target_lang="es",
        text="hola",
        is_final=True,
    )
    trace.record_final(event, latency_ms=400, audio_seconds=1.5)
    trace.finish()
    assert span.ended
    assert span.updates[0]["output"] == "hola"
    assert span.updates[0]["metadata"]["latency_ms"] == 400
    assert "cost_details" not in span.updates[0]
    usage = next(item for item in span.updates if item.get("usage_details"))
    assert usage["usage_details"] == {"input": 1200, "output": 80}
    assert usage_details_from_gemini(SimpleNamespace(prompt_token_count=0, response_token_count=0)) is None

    class Roto:
        def update(self, **kwargs):
            raise RuntimeError("langfuse caido")

        def end(self):
            raise RuntimeError("langfuse caido")

    SessionTrace(Roto()).fail(RuntimeError("gemini"))


def test_pcm_rechaza_longitud_impar():
    with pytest.raises(ValueError):
        validate_pcm_chunk(b"\x00")


def test_hello_exige_pcm_acordado():
    hello = Hello(source_lang="es", target_lang="en", sample_rate_hz=48_000)
    with pytest.raises(ValueError):
        hello.validate_audio_format()


def test_bus_entrega_solo_a_la_sesion():
    event = SubtitleEvent(
        session_id="sala-1",
        seq=1,
        start_ms=0,
        end_ms=100,
        source_lang="es",
        target_lang="en",
        text="hola",
        is_final=False,
    )
    other = event.model_copy(update={"session_id": "otra", "text": "no"})

    async def scenario() -> str:
        bus = InProcessBus()
        agen = bus.subscribe("sala-1")
        pending = asyncio.create_task(agen.__anext__())
        await asyncio.sleep(0)
        await bus.publish(other)
        await bus.publish(event)
        received = await pending
        await agen.aclose()
        return received.text

    assert asyncio.run(scenario()) == "hola"


def test_el_subtitulo_es_la_traduccion():
    hello = Hello(source_lang="es", target_lang="en")
    clock = _Clock()
    clock.advance(3200)
    ignored = event_from_server_content(
        "sala-1",
        hello,
        clock,
        SimpleNamespace(output_transcription=None, input_transcription=SimpleNamespace(text="hola")),
    )
    partial = event_from_server_content(
        "sala-1",
        hello,
        clock,
        SimpleNamespace(output_transcription=SimpleNamespace(text="hello", finished=False)),
    )
    final = event_from_server_content(
        "sala-1",
        hello,
        clock,
        SimpleNamespace(output_transcription=SimpleNamespace(text="hello world", finished=True)),
    )
    assert ignored is None
    assert partial is not None and partial.is_final is False and partial.text == "hello"
    assert final is not None and final.is_final is True and final.target_lang == "en"


def test_overlay_es_transparente_y_usa_el_sse():
    with TestClient(app) as client:
        response = client.get("/overlay", params={"session_id": "sala-1"})
    assert response.status_code == 200
    assert "background: transparent" in response.text
    assert "/v1/sessions/" in response.text
    assert "is_final" in response.text


def test_ingest_exige_hello_antes_del_audio():
    with TestClient(app) as client:
        with client.websocket_connect("/v1/sessions/sala-1/audio") as ws:
            ws.send_bytes(b"\x00\x00")
            with pytest.raises(Exception):
                ws.receive_text()

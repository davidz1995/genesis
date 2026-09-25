import asyncio
import time
from typing import Protocol

from google import genai
from google.genai import types

from genesis.bus import SubtitleBus
from genesis.models import Hello, SubtitleEvent
from genesis.tracing import SessionTrace, Tracing


class SubtitleEngine(Protocol):
    async def start(self, session_id: str, hello: Hello, bus: SubtitleBus) -> None: ...

    async def push_audio(self, session_id: str, pcm: bytes) -> None: ...

    async def stop(self, session_id: str) -> None: ...


class GeminiNotConfigured(RuntimeError):
    pass


class GeminiEngine:
    """Sesión Live de traducción. El subtítulo es el texto traducido, no el audio."""

    def __init__(self, api_key: str, model: str, tracing: Tracing | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._tracing = tracing or Tracing(None, model)
        self._client = genai.Client(api_key=api_key) if api_key else None
        self._sessions: dict[str, asyncio.Task[None]] = {}
        self._sockets: dict[str, object] = {}
        self._ready: dict[str, asyncio.Event] = {}
        self._clocks: dict[str, _Clock] = {}

    async def start(self, session_id: str, hello: Hello, bus: SubtitleBus) -> None:
        if self._client is None:
            raise GeminiNotConfigured("falta GEMINI_API_KEY")
        if session_id in self._sessions:
            return
        ready = asyncio.Event()
        self._ready[session_id] = ready
        self._clocks[session_id] = _Clock()
        task = asyncio.create_task(self._run(session_id, hello, bus, ready))
        self._sessions[session_id] = task
        await ready.wait()
        if task.done() and task.exception() is not None:
            self._sessions.pop(session_id, None)
            self._ready.pop(session_id, None)
            self._clocks.pop(session_id, None)
            raise task.exception()

    async def push_audio(self, session_id: str, pcm: bytes) -> None:
        ready = self._ready.get(session_id)
        if ready is None:
            raise RuntimeError("la sesión Gemini no está abierta")
        await ready.wait()
        socket = self._sockets.get(session_id)
        if socket is None:
            raise RuntimeError("la sesión Gemini no está abierta")
        clock = self._clocks[session_id]
        clock.advance(len(pcm))
        clock.begin_phrase()
        await socket.send_realtime_input(
            audio=types.Blob(data=pcm, mime_type="audio/pcm;rate=16000")
        )

    async def stop(self, session_id: str) -> None:
        task = self._sessions.pop(session_id, None)
        self._ready.pop(session_id, None)
        self._sockets.pop(session_id, None)
        self._clocks.pop(session_id, None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return

    async def _run(
        self,
        session_id: str,
        hello: Hello,
        bus: SubtitleBus,
        ready: asyncio.Event,
    ) -> None:
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription=types.AudioTranscriptionConfig(),
            translation_config=types.TranslationConfig(
                target_language_code=hello.target_lang,
                echo_target_language=True,
            ),
        )
        assert self._client is not None
        trace = self._tracing.open_session(session_id, hello)
        try:
            async with self._client.aio.live.connect(model=self._model, config=config) as session:
                self._sockets[session_id] = session
                ready.set()
                async for response in session.receive():
                    trace.note_usage(getattr(response, "usage_metadata", None))
                    event = event_from_server_content(
                        session_id,
                        hello,
                        self._clocks.get(session_id),
                        response.server_content,
                    )
                    if event is not None:
                        if event.is_final:
                            _record_final(trace, self._clocks.get(session_id), event)
                        await bus.publish(event)
        except asyncio.CancelledError:
            trace.finish()
            raise
        except Exception as exc:
            trace.fail(exc)
            raise
        else:
            trace.finish()
        finally:
            self._sockets.pop(session_id, None)
            ready.set()


class _Clock:
    def __init__(self) -> None:
        self.elapsed_ms = 0
        self.seq = 0
        self._phrase_wall: float | None = None
        self._phrase_audio_ms = 0

    def advance(self, pcm_bytes: int) -> None:
        self.elapsed_ms += pcm_bytes // 32

    def begin_phrase(self) -> None:
        if self._phrase_wall is None:
            self._phrase_wall = time.monotonic()
            self._phrase_audio_ms = self.elapsed_ms

    def take_phrase(self) -> tuple[int, float]:
        started = self._phrase_wall or time.monotonic()
        latency_ms = int((time.monotonic() - started) * 1000)
        audio_seconds = max(0, self.elapsed_ms - self._phrase_audio_ms) / 1000
        self._phrase_wall = None
        return latency_ms, audio_seconds

    def next_seq(self) -> int:
        current = self.seq
        self.seq += 1
        return current


def _record_final(trace: SessionTrace, clock: _Clock | None, event: SubtitleEvent) -> None:
    if clock is None:
        return
    latency_ms, audio_seconds = clock.take_phrase()
    trace.record_final(event, latency_ms=latency_ms, audio_seconds=audio_seconds)


def event_from_server_content(session_id, hello, clock, server_content) -> SubtitleEvent | None:
    if server_content is None or clock is None:
        return None
    translation = getattr(server_content, "output_transcription", None)
    text = getattr(translation, "text", None) if translation is not None else None
    if not text:
        return None
    return SubtitleEvent(
        session_id=session_id,
        seq=clock.next_seq(),
        start_ms=0,
        end_ms=clock.elapsed_ms,
        source_lang=hello.source_lang,
        target_lang=hello.target_lang,
        text=text,
        is_final=bool(getattr(translation, "finished", False)),
    )

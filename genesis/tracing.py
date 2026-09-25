import os
from typing import Any

from genesis.models import Hello, SubtitleEvent


class SessionTrace:
    """Traza de una sala. Si Langfuse falla, la traducción no se entera."""

    def __init__(self, span: Any) -> None:
        self._span = span
        self._finals = 0
        self._closed = False
        self._usage: dict[str, int] | None = None

    def note_usage(self, usage: Any) -> None:
        details = usage_details_from_gemini(usage)
        if details is not None:
            self._usage = details

    def record_final(self, event: SubtitleEvent, *, latency_ms: int, audio_seconds: float) -> None:
        if self._span is None or self._closed:
            return
        self._finals += 1
        try:
            generation = self._span.start_observation(
                name="subtitulo-final",
                as_type="generation",
                model=getattr(self, "_model", None),
            )
            generation.update(
                input={"source_lang": event.source_lang, "target_lang": event.target_lang},
                output=event.text,
                metadata={
                    "latency_ms": latency_ms,
                    "seq": event.seq,
                    "end_ms": event.end_ms,
                    "audio_seconds": round(audio_seconds, 3),
                },
            )
            generation.end()
        except Exception:
            return

    def fail(self, exc: BaseException) -> None:
        self._emit_usage()
        self._end(level="ERROR", status_message=str(exc), output={"finales": self._finals})

    def finish(self) -> None:
        self._emit_usage()
        self._end(output={"finales": self._finals})

    def _emit_usage(self) -> None:
        if self._span is None or self._closed or not self._usage:
            return
        try:
            generation = self._span.start_observation(
                name="uso-api",
                as_type="generation",
                model=getattr(self, "_model", None),
            )
            generation.update(usage_details=self._usage)
            generation.end()
        except Exception:
            return

    def _end(self, **fields: Any) -> None:
        if self._span is None or self._closed:
            return
        self._closed = True
        try:
            self._span.update(**fields)
            self._span.end()
        except Exception:
            return


class Tracing:
    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_env(cls, model: str) -> "Tracing":
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
        if not public_key or not secret_key:
            return cls(None, model)
        try:
            from langfuse import get_client

            return cls(get_client(), model)
        except Exception:
            return cls(None, model)

    def open_session(self, session_id: str, hello: Hello) -> SessionTrace:
        if self._client is None:
            return SessionTrace(None)
        try:
            from langfuse import propagate_attributes

            with propagate_attributes(session_id=session_id):
                span = self._client.start_observation(
                    name="traduccion",
                    as_type="span",
                    input={
                        "session_id": session_id,
                        "source_lang": hello.source_lang,
                        "target_lang": hello.target_lang,
                        "model": self._model,
                    },
                )
            trace = SessionTrace(span)
            trace._model = self._model
            return trace
        except Exception:
            return SessionTrace(None)

    def shutdown(self) -> None:
        if self._client is None:
            return
        try:
            self._client.shutdown()
        except Exception:
            return


def usage_details_from_gemini(usage: Any) -> dict[str, int] | None:
    prompt = getattr(usage, "prompt_token_count", None)
    response = getattr(usage, "response_token_count", None)
    details: dict[str, int] = {}
    if prompt:
        details["input"] = int(prompt)
    if response:
        details["output"] = int(response)
    return details or None

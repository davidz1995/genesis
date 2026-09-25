import re

from pydantic import BaseModel, Field

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LANG_PATTERN = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")

# ~100 ms de PCM 16 kHz / 16-bit / mono son 3200 bytes. Se acepta hasta 500 ms.
MAX_PCM_BYTES = 16_000


class Hello(BaseModel):
    type: str = "hello"
    source_lang: str = Field(pattern=LANG_PATTERN.pattern)
    target_lang: str = Field(pattern=LANG_PATTERN.pattern)
    sample_rate_hz: int = 16_000
    channels: int = 1
    sample_format: str = "s16le"

    def validate_audio_format(self) -> None:
        if self.type != "hello":
            raise ValueError("el primer mensaje debe ser hello")
        if self.sample_rate_hz != 16_000 or self.channels != 1 or self.sample_format != "s16le":
            raise ValueError("el audio debe ser PCM 16-bit, 16 kHz, mono")


class SubtitleEvent(BaseModel):
    session_id: str
    seq: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    source_lang: str
    target_lang: str
    text: str
    is_final: bool


def validate_session_id(session_id: str) -> str:
    if SESSION_ID_PATTERN.fullmatch(session_id) is None:
        raise ValueError("session_id inválido")
    return session_id


def validate_pcm_chunk(payload: bytes) -> None:
    if not payload:
        raise ValueError("chunk PCM vacío")
    if len(payload) > MAX_PCM_BYTES:
        raise ValueError("chunk PCM demasiado grande")
    if len(payload) % 2 != 0:
        raise ValueError("el PCM 16-bit debe tener longitud par")

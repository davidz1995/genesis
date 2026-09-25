import array
import sys
import wave
from pathlib import Path

CHUNK_BYTES = 3_200
TARGET_RATE = 16_000


def load_pcm_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_rate = wav_file.getframerate()
        pcm = wav_file.readframes(wav_file.getnframes())
    if sample_width != 2 or channels not in (1, 2) or frame_rate <= 0:
        raise ValueError("el WAV debe ser PCM 16-bit, mono o estéreo")
    if not pcm:
        raise ValueError("el WAV no tiene audio")
    mono = _to_mono(pcm, channels)
    return _resample_s16(mono, frame_rate, TARGET_RATE)


def _to_mono(pcm: bytes, channels: int) -> bytes:
    if channels == 1:
        return pcm
    samples = _as_samples(pcm)
    mixed = array.array("h", ((_clip((samples[i] + samples[i + 1]) // 2)) for i in range(0, len(samples), 2)))
    return mixed.tobytes()


def _resample_s16(pcm: bytes, source_rate: int, target_rate: int) -> bytes:
    if source_rate == target_rate:
        return pcm
    samples = _as_samples(pcm)
    out_len = max(1, int(len(samples) * target_rate / source_rate))
    scale = source_rate / target_rate
    last = len(samples) - 1
    out = array.array("h", [0]) * out_len
    for index in range(out_len):
        position = index * scale
        left = int(position)
        if left >= last:
            out[index] = samples[last]
            continue
        fraction = position - left
        mixed = samples[left] * (1 - fraction) + samples[left + 1] * fraction
        out[index] = _clip(int(round(mixed)))
    return out.tobytes()


def _as_samples(pcm: bytes) -> array.array:
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def _clip(value: int) -> int:
    return max(-32768, min(32767, value))


def iter_chunks(pcm: bytes, size: int = CHUNK_BYTES):
    for offset in range(0, len(pcm), size):
        yield pcm[offset : offset + size]

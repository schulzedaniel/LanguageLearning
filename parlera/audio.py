"""Small WAV helpers (no ffmpeg needed)."""
from __future__ import annotations

import io
import wave

import numpy as np


def wav_to_float32(data: bytes, target_rate: int = 16000) -> np.ndarray:
    """Decode a PCM WAV (8/16/32-bit, mono or stereo) into mono float32 at target_rate."""
    with wave.open(io.BytesIO(data), "rb") as wf:
        rate, channels, width = wf.getframerate(), wf.getnchannels(), wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())
    if width == 2:
        audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        audio = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    else:
        raise ValueError(f"Unsupported sample width {width}")
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return resample(audio, rate, target_rate)


def resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or len(audio) == 0:
        return audio.astype(np.float32)
    n = int(round(len(audio) * dst / src))
    x_old = np.linspace(0, 1, len(audio), endpoint=False)
    x_new = np.linspace(0, 1, n, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def _rate(data: bytes) -> int:
    with wave.open(io.BytesIO(data), "rb") as wf:
        return wf.getframerate()


def float32_to_wav(audio: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def concat_wavs(chunks: list[bytes], gap_ms: int = 120) -> bytes:
    """Concatenate WAVs (resampling to the first one's rate) with short pauses."""
    chunks = [c for c in chunks if c]
    if not chunks:
        return b""
    if len(chunks) == 1:
        return chunks[0]
    rate = _rate(chunks[0])
    gap = np.zeros(int(rate * gap_ms / 1000), dtype=np.float32)
    parts: list[np.ndarray] = []
    for i, c in enumerate(chunks):
        if i:
            parts.append(gap)
        parts.append(wav_to_float32(c, target_rate=rate))
    return float32_to_wav(np.concatenate(parts), rate)


def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0

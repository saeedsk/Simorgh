"""Bring synthesised audio to the microphone's rate, for the echo
canceller's reference. Kokoro speaks at 24 kHz, Piper at 22.05 kHz,
the mic listens at 16 kHz; a reference at the wrong rate cancels
nothing (the first version sliced 24 kHz audio into 16 kHz frames and
the canceller learnt noise). Linear interpolation is enough for a
reference; nothing here is played."""

from __future__ import annotations

from .api import SAMPLE_RATE


def to_mic_rate(pcm: bytes, sample_rate: int, *, target: int = SAMPLE_RATE) -> bytes:
    if sample_rate == target or not pcm:
        return pcm
    try:
        import numpy as np
    except ImportError:  # pragma: no cover -- numpy is always beside kokoro-onnx
        return pcm
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n_out = int(len(samples) * target / sample_rate)
    if n_out <= 1:
        return b""
    positions = np.linspace(0, len(samples) - 1, n_out)
    out = np.interp(positions, np.arange(len(samples)), samples)
    return np.clip(out, -32768, 32767).astype(np.int16).tobytes()


__all__ = ["to_mic_rate"]

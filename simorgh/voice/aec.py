"""Acoustic echo cancellation, so a person -- and only a person -- can
interrupt Sim.

The level-and-voice gate in `vad.py` asks "is this louder than Sim's
own voice?". That is a heuristic, and a loud room defeats it. This asks
a sharper question, because Sim knows EXACTLY what it is playing: given
the reference (the PCM going to the speaker) and what the microphone
hears, an adaptive filter learns the room's echo path and subtracts it.
What is left -- the residual -- is everything the reference cannot
explain: the person, and the noise floor. On Sim-only speech the filter
converges and the residual collapses (high ERLE); the moment a person
talks, the residual jumps, because their voice is not in the reference.
That jump is the double-talk signal, and it does not care how loud Sim
is.

NLMS in the time domain, one tap-vector per sample, vectorised with
numpy so a 30 ms frame is well inside a 30 ms budget. The filter length
covers the loudspeaker-to-mic delay plus the room tail; `delay_search`
finds the bulk delay once from the opening of a reply so the taps are
spent on the tail, not on empty air.

numpy only, and optional: `[voice] aec` off falls back to the level
gate. It is off by DEFAULT until it has been tuned against a real
recording of the creator's own room -- a simulated echo is not a
promise about a kitchen.
"""

from __future__ import annotations

from .api import SAMPLE_RATE

try:
    import numpy as np
except ImportError:  # numpy is optional; `available()` gates every use below
    np = None


def _to_float(pcm: bytes):
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def _to_pcm(samples) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()


def erle_db(mic, residual) -> float:
    """Echo Return Loss Enhancement: how much quieter the residual is
    than the mic, in dB. High = the filter explained the mic from the
    reference (Sim alone); low = it could not (silence, or a person)."""

    mic_p = float(np.mean(mic.astype(np.float64) ** 2)) if len(mic) else 0.0
    res_p = float(np.mean(residual.astype(np.float64) ** 2)) if len(residual) else 0.0
    if mic_p <= 1e-9:
        return 0.0
    return 10.0 * np.log10(mic_p / max(res_p, 1e-9))


def delay_search(mic: bytes, ref: bytes, *, max_ms: int = 200) -> int:
    """Samples of bulk delay from reference to microphone, by
    cross-correlation of their envelopes. 0 if nothing correlates."""

    m, r = _to_float(mic), _to_float(ref)
    n = min(len(m), len(r))
    if n < SAMPLE_RATE // 20:  # need ~50 ms to say anything
        return 0
    m, r = np.abs(m[:n]), np.abs(r[:n])
    m -= m.mean()
    r -= r.mean()
    max_lag = min(max_ms * SAMPLE_RATE // 1000, n - 1)
    corr = np.correlate(m, r[: n - max_lag] if max_lag else r, mode="valid")
    if not len(corr):
        return 0
    lag = int(np.argmax(corr))
    return lag if corr[lag] > 0 else 0


class EchoCanceller:
    """One adaptive filter, fed (mic frame, reference frame) in order.

    `process` returns the residual for the frame -- the mic with the
    predictable echo removed. State (the filter weights, the reference
    history) persists across frames, so it converges over a reply.
    """

    def __init__(self, *, taps: int = 1024, mu: float = 0.3, delay: int = 0) -> None:

        self._taps = int(taps)
        self._mu = float(mu)
        self._delay = int(delay)
        self._w = np.zeros(self._taps, dtype=np.float32)
        # Reference history: newest last. Long enough for the delay plus
        # a full tap window.
        self._hist = np.zeros(self._taps + self._delay, dtype=np.float32)
        self.last_erle_db = 0.0

    def process(self, mic: bytes, ref: bytes) -> bytes:
        d = _to_float(mic)
        x_in = _to_float(ref)
        # Pad the reference to the mic length (playback may be a beat
        # behind); missing reference is silence, which teaches nothing.
        if len(x_in) < len(d):
            x_in = np.concatenate([x_in, np.zeros(len(d) - len(x_in), dtype=np.float32)])
        else:
            x_in = x_in[: len(d)]
        out = np.empty(len(d), dtype=np.float32)
        w, hist, taps, mu, delay = self._w, self._hist, self._taps, self._mu, self._delay
        eps = 1e-6
        for n in range(len(d)):
            hist = np.roll(hist, -1)
            hist[-1] = x_in[n]
            # The tap window ends `delay` samples back from now.
            end = len(hist) - delay
            xv = hist[end - taps: end]
            y = float(np.dot(w, xv))
            e = d[n] - y
            w += (mu * e / (float(np.dot(xv, xv)) + eps)) * xv
            out[n] = e
        self._w, self._hist = w, hist
        self.last_erle_db = erle_db(d, out)
        return _to_pcm(out)

    def reset(self) -> None:
        self._w[:] = 0.0
        self._hist[:] = 0.0
        self.last_erle_db = 0.0


class EchoCancellingDetector:
    """A barge-in detector that decides on the AEC RESIDUAL.

    Wraps a voice detector (Silero, say). It is handed each frame's
    reference through `set_reference` before `is_speech`, cancels the
    echo, and calls a frame speech only when a voice survives the
    cancellation with real energy -- i.e. a person the reference cannot
    account for. Sim's own voice, however loud, is in the reference and
    is cancelled away.
    """

    name = "aec"

    def __init__(self, voice, canceller: EchoCanceller, *, residual_threshold: float = 0.02) -> None:
        self._voice = voice
        self._aec = canceller
        self._threshold = residual_threshold
        self._ref = b""

    def set_reference(self, ref: bytes) -> None:
        self._ref = ref

    def is_speech(self, frame: bytes) -> bool:

        residual = self._aec.process(frame, self._ref)
        res = _to_float(residual)
        rms = float(np.sqrt(np.mean(res ** 2))) if len(res) else 0.0
        if rms < self._threshold:
            return False
        return bool(self._voice.is_speech(residual))

    # The barge-in endpointer calls these on its level gate; with AEC
    # the residual already has the echo out, so they are no-ops.
    def raise_floor(self, rms: float) -> None:  # noqa: D401
        return None

    def set_ratio(self, ratio: float) -> None:
        return None

    @staticmethod
    def rms(frame: bytes) -> float:

        s = _to_float(frame)
        return float(np.sqrt(np.mean(s ** 2))) * 32768.0 if len(s) else 0.0


def available() -> tuple[bool, str]:
    import importlib.util

    if importlib.util.find_spec("numpy") is None:
        return False, "numpy is not installed"
    return True, ""


__all__ = ["EchoCanceller", "EchoCancellingDetector", "available", "delay_search", "erle_db"]

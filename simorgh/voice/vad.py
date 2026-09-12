"""Endpointing: deciding that the person has finished speaking.

Section 4.2 of the design: silence for `endpoint_silence_ms` ends the
utterance, a hard cap at `max_utterance_s` bounds it, and (later) a
streaming transcript whose last token is a filler holds the door open.

Two detectors. Silero VAD (ONNX, the standard) when its package is
installed; otherwise an energy detector with an adaptive noise floor --
crude, honest about it in `name`, and enough for push-to-talk on a
laptop. Both are fed 30 ms frames of 16 kHz int16 PCM.
"""

from __future__ import annotations

import array
import math

from .api import SAMPLE_RATE, SAMPLE_WIDTH


class EnergyDetector:
    """Speech = RMS well above a running estimate of the noise floor."""

    name = "energy"

    def __init__(self, threshold: float = 0.5) -> None:
        # `threshold` (0..1) scales how far above the floor speech must
        # sit: 0.5 -> 6 dB, 1.0 -> 12 dB.
        self._ratio = 10 ** (0.6 * max(0.05, min(1.0, threshold)))
        self._floor: float | None = None
        # What the microphone is expected to hear of Sim's own voice
        # RIGHT NOW (`set_echo`); 0 when nothing is playing. It is a bar
        # alongside the room floor, not part of it: the floor learns the
        # room through silence and must not learn Sim.
        self._echo = 0.0

    def raise_floor(self, rms: float) -> None:
        """Treat `rms` as silence from now on. Used while Sim speaks:
        the microphone hears the speakers, and that echo must not count
        as a person talking."""
        self._floor = max(self._floor or 0.0, rms, 1.0)

    def set_echo(self, rms: float) -> None:
        """The level of Sim's own voice expected at the microphone for
        the next frame -- from what is PLAYING, never from what the mic
        hears, so a person talking cannot raise the bar against
        themselves. `inf` while that level is still being learnt: then
        nothing is speech."""
        self._echo = max(0.0, float(rms))

    def clear_echo(self) -> None:
        self._echo = 0.0

    def set_ratio(self, ratio: float) -> None:
        """How many times louder than the floor speech must be."""
        self._ratio = max(1.1, float(ratio))

    @staticmethod
    def rms(frame: bytes) -> float:
        samples = array.array("h", frame)
        return math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0

    def is_speech(self, frame: bytes) -> bool:
        samples = array.array("h", frame)
        if not samples:
            return False
        rms = math.sqrt(sum(s * s for s in samples) / len(samples))
        if self._floor is None:
            self._floor = max(rms, 1.0)
            return False
        bar = max(self._floor, self._echo)
        speech = rms > bar * self._ratio and rms > 200.0
        if not speech and not self._echo:
            # Track the floor only through silence, slowly -- and never
            # while Sim is playing: its echo is not the room.
            self._floor = 0.95 * self._floor + 0.05 * max(rms, 1.0)
        return speech


class SileroDetector:
    name = "silero"

    def __init__(self, threshold: float = 0.5) -> None:
        try:
            from silero_vad import load_silero_vad  # type: ignore
        except ImportError as exc:
            raise ImportError("silero-vad is not installed") from exc
        self._model = load_silero_vad(onnx=True)
        reset = getattr(self._model, "reset_states", None)
        if reset is not None:
            reset()
        self._threshold = threshold
        self._buffer = b""

    def is_speech(self, frame: bytes) -> bool:
        try:
            import torch  # silero's API takes a tensor  # type: ignore
        except ImportError as exc:  # pragma: no cover -- silero-vad depends on torch
            raise RuntimeError("silero-vad needs torch") from exc

        self._buffer += frame
        chunk = SAMPLE_RATE * 32 // 1000 * SAMPLE_WIDTH  # silero wants 512-sample windows at 16 kHz
        if len(self._buffer) < chunk:
            return False
        window, self._buffer = self._buffer[:chunk], self._buffer[chunk:]
        samples = array.array("h", window)
        tensor = torch.tensor([s / 32768.0 for s in samples])
        return float(self._model(tensor, SAMPLE_RATE).item()) >= self._threshold


class CompositeDetector:
    """Speech only if the voice detector says so AND the level gate does.

    For barge-in. Silero knows a voice from a keyboard, a clap, a chair
    -- the creator, 2026-09-11: "if sim is talking and I'm typing or
    clapping, that should not interrupt sim" -- but Sim's own voice
    through the speakers is a voice too, so on its own it would fire on
    every echo. The level gate, calibrated to that echo, is what says
    "louder than Sim". Both, or it is not a person cutting in.
    """

    def __init__(self, voice, level) -> None:
        self._voice = voice
        self._level = level
        self.name = f"{voice.name}+{level.name}"

    def is_speech(self, frame: bytes) -> bool:
        # Evaluate both every frame: the level gate's floor only learns
        # from frames it sees, and Silero's state must follow the audio.
        loud = self._level.is_speech(frame)
        voiced = self._voice.is_speech(frame)
        return loud and voiced

    def raise_floor(self, rms: float) -> None:
        raise_floor = getattr(self._level, "raise_floor", None)
        if raise_floor is not None:
            raise_floor(rms)

    def set_ratio(self, ratio: float) -> None:
        set_ratio = getattr(self._level, "set_ratio", None)
        if set_ratio is not None:
            set_ratio(ratio)

    def set_echo(self, rms: float) -> None:
        set_echo = getattr(self._level, "set_echo", None)
        if set_echo is not None:
            set_echo(rms)

    def clear_echo(self) -> None:
        clear_echo = getattr(self._level, "clear_echo", None)
        if clear_echo is not None:
            clear_echo()

    @staticmethod
    def rms(frame: bytes) -> float:
        return EnergyDetector.rms(frame)


class Endpointer:
    """Feed frames; `True` once the utterance has ended.

    Ends after `silence_ms` of non-speech FOLLOWING some speech, or at
    `max_seconds` regardless. Before any speech it never ends -- a
    person who has not started yet is not finished -- which is why
    `max_seconds` exists.
    """

    def __init__(self, detector, *, silence_ms: int, max_seconds: float, frame_ms: int = 30) -> None:
        self._detector = detector
        self._silence_frames = max(1, silence_ms // frame_ms)
        self._max_frames = max(1, int(max_seconds * 1000 / frame_ms))
        self._frames = 0
        self._quiet = 0
        self.heard_speech = False
        self.ended_by = ""

    @property
    def name(self) -> str:
        return self._detector.name

    def feed(self, frame: bytes) -> bool:
        self._frames += 1
        if self._detector.is_speech(frame):
            self.heard_speech = True
            self._quiet = 0
        elif self.heard_speech:
            self._quiet += 1
            if self._quiet >= self._silence_frames:
                self.ended_by = "silence"
                return True
        if self._frames >= self._max_frames:
            self.ended_by = "max_seconds"
            return True
        return False


class BargeInEndpointer(Endpointer):
    """An endpointer that also notices a person cutting in.

    Runs while Sim is speaking. The first `calibrate_frames` frames are
    taken to be what the microphone hears of Sim's own voice through
    the speakers, and the detector's floor is raised to that level --
    the cheapest echo cancellation there is, and enough for a laptop:
    a person at the keyboard is louder at the mic than the speakers'
    spill. Then `speech_ms` of continuous speech calls `on_barge_in`
    once, and the utterance carries on to its normal end, so the words
    that interrupted Sim are the start of the next turn, not lost.
    """

    def __init__(self, detector, *, silence_ms: int, max_seconds: float, speech_ms: int = 400,
                 on_barge_in=None, calibrate_frames: int = 30, ratio: float | None = None,
                 reference: list | None = None, frame_ms: int = 30) -> None:
        super().__init__(detector, silence_ms=silence_ms, max_seconds=max_seconds, frame_ms=frame_ms)
        self._need = max(1, speech_ms // frame_ms)
        self._run = 0
        self._on_barge_in = on_barge_in
        self._calibrate = calibrate_frames
        self._seen = 0
        self._echo = 0.0
        self.barged = False
        # For an echo-cancelling detector: the reference (what Sim is
        # playing), one frame per mic frame. Consumed in step with feed.
        # The caller's own list, kept by identity: the streaming path
        # (`pipeline._play_stream_interruptibly`) appends to it as pieces
        # are produced, so an empty list at construction is not "no
        # reference", it is "none yet". `reference or []` silently
        # replaced it with a private empty list and cancelled nothing.
        self._reference = reference if reference is not None else []
        self._ref_i = 0
        self._silence_frame = b""
        if ratio is not None and hasattr(detector, "set_ratio"):
            detector.set_ratio(ratio)

    def _offer_reference(self) -> None:
        set_reference = getattr(self._detector, "set_reference", None)
        if set_reference is None:
            return
        ref = self._reference[self._ref_i] if self._ref_i < len(self._reference) else self._silence_frame
        self._ref_i += 1
        set_reference(ref)

    def _track_echo(self, frame: bytes) -> None:
        """Raise the floor to the loudest of Sim's own voice heard so far.

        The first version froze the floor after `calibrate_frames`. But
        Kokoro opens near-silent and swells, so a reply's later, louder
        syllables sat above a floor learnt from its quiet opening --
        Sim's own voice cleared the bar and registered as a person, and
        Sim stopped for no one (the creator, 2026-09-11: "sensitivity to
        detect human voice causes sim to stop frequently, even when the
        human is not talking"). The floor is now the running MAXIMUM of
        every frame that was NOT itself a person cutting in, updated for
        the whole reply, so a person must beat Sim's loudest moment --
        not its quietest."""
        rms = self._detector.rms(frame) if hasattr(self._detector, "rms") else 0.0
        self._echo = max(self._echo, rms)
        raise_floor = getattr(self._detector, "raise_floor", None)
        if raise_floor is not None:
            raise_floor(self._echo)

    def feed(self, frame: bytes) -> bool:
        self._seen += 1
        self._offer_reference()
        if self._seen <= self._calibrate:
            # Warm-up: learn the echo, and nothing may interrupt yet.
            self._track_echo(frame)
            self._frames += 1
            return False
        speech = self._detector.is_speech(frame)
        if speech:
            self._run += 1
            if not self.barged and self._run >= self._need:
                self.barged = True
                self.heard_speech = True
                if self._on_barge_in is not None:
                    self._on_barge_in()
        else:
            # Not a person: it is Sim or the room, so it teaches the
            # floor. A brief loud blip that did not reach `_need` frames
            # thus RAISES the bar for the next one -- a stray clip cannot
            # nag Sim to a stop.
            self._run = 0
            if not self.barged:
                self._track_echo(frame)
        if not self.barged:
            # Nothing decisive yet; keep listening for as long as the
            # playback (the caller's `max_seconds`) allows.
            self._frames += 1
            if self._frames >= self._max_frames:
                self.ended_by = "max_seconds"
                return True
            return False
        # A person is talking over Sim: from here on, an ordinary utterance.
        self._frames += 1
        if speech:
            self._quiet = 0
        else:
            self._quiet += 1
            if self._quiet >= self._silence_frames:
                self.ended_by = "silence"
                return True
        if self._frames >= self._max_frames:
            self.ended_by = "max_seconds"
            return True
        return False



def frame_levels(pcm: bytes, sample_rate: int, *, frame_ms: int = 30) -> list[float]:
    """RMS per `frame_ms` frame of int16 PCM, at any sample rate: the
    loudness envelope of a piece of audio."""
    step = max(1, sample_rate * frame_ms // 1000) * SAMPLE_WIDTH
    try:
        import numpy as np

        samples = np.frombuffer(pcm[: len(pcm) - len(pcm) % SAMPLE_WIDTH], dtype=np.int16).astype(np.float64)
        n = step // SAMPLE_WIDTH
        if n <= 0 or not len(samples):
            return []
        whole = len(samples) // n * n
        out = np.sqrt(np.mean(samples[:whole].reshape(-1, n) ** 2, axis=1)).tolist() if whole else []
        if whole < len(samples):
            out.append(float(np.sqrt(np.mean(samples[whole:] ** 2))))
        return [float(x) for x in out]
    except ImportError:
        return [EnergyDetector.rms(pcm[i:i + step]) for i in range(0, len(pcm), step)]


class EchoTracker:
    """What the microphone should be hearing of Sim's own voice, frame
    by frame, worked out from what is being PLAYED.

    The level gate for barge-in needs a bar: "louder than Sim". The
    first two versions learnt that bar from the microphone -- the
    loudest frame heard while Sim spoke -- and both failed, in opposite
    ways. Frozen after a calibration window, the bar sat below Kokoro's
    later, louder syllables, and Sim interrupted itself. Raised by every
    frame for the whole reply, the bar included the person's own frames
    the moment they spoke, and since a frame is never 2.8 times louder
    than a bar that already contains it, no one could interrupt Sim at
    all (the creator, 2026-09-11: "I tried to cut you off or stop you
    like 10 times but you didn't stop").

    So the bar comes from the reference instead. `play(audio)` is told
    each run of audio as it goes to the speaker, with the time it went;
    `expected(now)` is the loudest reference frame in a window around
    `now` -- wide enough for the speaker's latency and the room's tail
    -- scaled by `gain`, the ratio of what the mic hears to what is
    played. The gain is learnt once per reply from the first
    `calibrate_frames` mic frames, during which nothing may interrupt
    (`calibrating`), and carried to the next reply as its starting
    point. The person cannot raise the bar against themselves: their
    voice is not in the reference. Kokoro's swell cannot beat it either:
    when the reference is loud the bar is loud, and in a pause between
    sentences it drops to the room, so a person can cut in there at once.
    """

    # The reference window, relative to a mic frame's arrival: playback
    # starts a beat late (afplay spawns; PortAudio buffers) and the room
    # rings on after each syllable, so the echo of a reference frame
    # reaches the mic anything up to half a second AFTER it was queued.
    BEFORE_S = 0.5
    AFTER_S = 0.15
    MIN_REFERENCE = 100.0  # below this the reference is silence; it teaches no gain

    def __init__(self, *, calibrate_frames: int = 40, gain: float = 0.0) -> None:
        self._calibrate = max(1, int(calibrate_frames))
        self._runs: list[tuple[float, float, list[float]]] = []  # (started_at, frame_s, levels)
        self._ends_at = 0.0
        self.gain = float(gain)      # mic RMS per reference RMS; 0 = not yet learnt
        self._learnt = 0.0           # this reply's estimate so far
        self._seen = 0               # calibration frames used this reply
        self.replies = 0

    # -- what is playing --------------------------------------------------------------------------
    def start(self) -> None:
        """A new playback: forget the old reference, learn the gain afresh."""
        self._runs.clear()
        self._ends_at = 0.0
        self._learnt = 0.0
        self._seen = 0
        self.replies += 1

    def play(self, audio, *, at: float) -> None:
        """`audio` was handed to the speaker at monotonic time `at`."""
        levels = frame_levels(audio.pcm, audio.sample_rate)
        if not levels:
            return
        frame_s = 0.03
        self._runs.append((at, frame_s, levels))
        self._ends_at = max(self._ends_at, at + frame_s * len(levels))

    @property
    def playing(self) -> bool:
        return bool(self._runs)

    def active(self, now: float) -> bool:
        """Whether the microphone may still be hearing Sim at `now`."""
        return bool(self._runs) and now <= self._ends_at + self.BEFORE_S

    @property
    def calibrating(self) -> bool:
        """Still learning this reply's gain with no earlier one to go
        on: the only time a person cannot interrupt."""
        return bool(self._runs) and self._seen < self._calibrate and self.gain <= 0.0

    def reference(self, now: float) -> float:
        """The loudest reference frame that could be reaching the mic now."""
        lo, hi = now - self.BEFORE_S, now + self.AFTER_S
        peak = 0.0
        for started, frame_s, levels in self._runs:
            first = max(0, int((lo - started) / frame_s))
            last = min(len(levels), int((hi - started) / frame_s) + 1)
            if first < last:
                peak = max(peak, max(levels[first:last]))
        return peak

    # -- what the mic hears ---------------------------------------------------------------------------
    def observe(self, mic_rms: float, now: float) -> None:
        """One mic frame while Sim plays. During calibration it teaches
        the gain; afterwards it teaches nothing -- it may be the person."""
        if self._seen >= self._calibrate:
            return
        ref = self.reference(now)
        if ref < self.MIN_REFERENCE:
            return  # the reference is silent here: the mic hears the room, not Sim
        self._seen += 1
        self._learnt = max(self._learnt, mic_rms / ref)
        if self._seen >= self._calibrate and self._learnt > 0.0:
            # This reply's measurement replaces the last one's: the
            # volume may have changed between them.
            self.gain = self._learnt

    def expected(self, now: float) -> float:
        """Sim's own voice at the mic, expected now. `inf` while the gain
        for this reply is still being learnt and none is known from an
        earlier one -- then nothing may count as a person."""
        if not self.active(now):
            return 0.0
        if self.calibrating:
            return float("inf")
        # Learning still (a later reply): the last reply's gain, or this
        # one's so far if the volume has gone up since.
        gain = max(self.gain, self._learnt) if self._seen < self._calibrate else self.gain
        return gain * self.reference(now)


def open_detector(preferred: str = "auto", *, threshold: float = 0.5) -> tuple[object, str]:
    """`(detector, note)`. Never fails: the energy detector needs nothing."""
    if preferred in ("auto", "silero"):
        try:
            return SileroDetector(threshold), ""
        except ImportError as exc:
            if preferred == "silero":
                return EnergyDetector(threshold), f"silero requested but {exc}; using the energy detector"
    if preferred == "fake":
        from .fakes import FakeDetector

        return FakeDetector(), ""
    return EnergyDetector(threshold), ""


__all__ = ["FrameVad", "SENSITIVITY", "threshold_for", "BargeInEndpointer", "CompositeDetector", "EchoTracker", "EnergyDetector", "Endpointer", "SileroDetector", "frame_levels", "open_detector"]


class FrameVad:
    """`VoiceActivityDetector`: one `VadEvent` per frame, with the running
    lengths of the current speech or silence, over any frame detector
    (Silero, energy, composite, echo-cancelling). `speech_start` fires
    on the first speech frame after silence and `speech_end` on the
    first silence frame after speech; the turn manager decides what a
    run of silence means."""

    def __init__(self, detector, *, frame_ms: int = 30, hangover_frames: int = 2) -> None:
        self._detector = detector
        self._frame_ms = frame_ms
        self._hangover = max(0, hangover_frames)
        self._speech_ms = 0
        self._silence_ms = 0
        self._in_speech = False
        self._quiet_run = 0

    @property
    def name(self) -> str:
        return getattr(self._detector, "name", "vad")

    def process(self, frame: bytes):
        from .api import VadEvent

        speech = self._detector.is_speech(frame)
        level = self._detector.rms(frame) if hasattr(self._detector, "rms") else 0.0
        if speech:
            self._quiet_run = 0
            self._silence_ms = 0
            self._speech_ms += self._frame_ms
            if not self._in_speech:
                self._in_speech = True
                return VadEvent("speech_start", speech_ms=self._speech_ms, level=level)
            return VadEvent("speech", speech_ms=self._speech_ms, level=level)
        # A frame or two of quiet inside a word is not the end of speech.
        if self._in_speech and self._quiet_run < self._hangover:
            self._quiet_run += 1
            self._speech_ms += self._frame_ms
            return VadEvent("speech", speech_ms=self._speech_ms, level=level)
        self._silence_ms += self._frame_ms
        if self._in_speech:
            self._in_speech = False
            ended = self._speech_ms
            self._speech_ms = 0
            return VadEvent("speech_end", speech_ms=ended, silence_ms=self._silence_ms, level=level)
        return VadEvent("silence", silence_ms=self._silence_ms, level=level)

    def reset(self) -> None:
        self._speech_ms = self._silence_ms = self._quiet_run = 0
        self._in_speech = False


SENSITIVITY = {"low": 0.7, "balanced": 0.5, "high": 0.35}


def threshold_for(sensitivity: str, fallback: float = 0.5) -> float:
    """`vad_sensitivity` low | balanced | high as a detector threshold;
    a higher threshold needs a surer voice, so `low` is the strict one."""
    return SENSITIVITY.get(str(sensitivity).lower(), fallback)

"""Acoustic echo cancellation: Sim's own voice subtracted, the person kept.

The level-and-voice gate asks "louder than Sim?"; a loud room beats it.
AEC asks "is this in what we are playing?" -- Sim knows exactly, so an
adaptive filter learns the room's echo and subtracts it. On Sim-only
speech the residual collapses (high ERLE); a person, absent from the
reference, survives. Validated here on a SYNTHETIC echo path -- a real
room needs a recording to tune -- which is why `[voice] aec` is off by
default.
"""

from __future__ import annotations

import unittest

try:
    import numpy as np
    _HAVE_NUMPY = True
except ImportError:
    _HAVE_NUMPY = False

from simorgh.voice.api import SAMPLE_RATE


def _i16(x) -> bytes:
    return (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()


def _rms(pcm: bytes) -> float:
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(a ** 2))) if len(a) else 0.0


_PATH = None
def _echo_path():
    global _PATH
    if _PATH is None:
        p = np.zeros(200, dtype=np.float32)
        p[40], p[70], p[110] = 0.8, 0.4, 0.2  # 40-sample delay + a short tail
        _PATH = p
    return _PATH


@unittest.skipUnless(_HAVE_NUMPY, "numpy is required for AEC")
class EchoCancellerTestCase(unittest.TestCase):
    def _play_echo(self, aec, rng, frames, near_end=None):
        """Feed `frames` of Sim-only echo; return the last residual and ERLE."""
        from simorgh.voice.aec import EchoCanceller  # noqa: F401 -- ensure importable
        path = _echo_path()
        frame = SAMPLE_RATE * 30 // 1000
        tail = np.zeros(0, dtype=np.float32)
        last_res, last_erle = b"", 0.0
        for k in range(frames):
            ref = rng.standard_normal(frame).astype(np.float32) * 0.3
            full = np.convolve(np.concatenate([tail, ref]), path)
            mic = full[len(tail):len(tail) + frame]
            tail = ref[-len(path):]
            if near_end is not None and k == frames - 1:
                mic = mic + near_end
            last_res = aec.process(_i16(mic), _i16(ref))
            last_erle = aec.last_erle_db
        return last_res, last_erle

    def test_echo_only_converges_to_high_erle(self):
        from simorgh.voice.aec import EchoCanceller
        aec = EchoCanceller(taps=512, mu=0.5)
        _res, erle = self._play_echo(aec, np.random.default_rng(1), 100)
        self.assertGreater(erle, 20.0, "the filter should remove most of a static echo")

    def test_a_person_survives_the_cancellation(self):
        from simorgh.voice.aec import EchoCanceller
        aec = EchoCanceller(taps=512, mu=0.5)
        rng = np.random.default_rng(2)
        # converge on echo, then one frame of echo + a near-end voice
        person = rng.standard_normal(SAMPLE_RATE * 30 // 1000).astype(np.float32) * 0.3
        res, _ = self._play_echo(aec, rng, 100, near_end=person)
        self.assertGreater(_rms(res), 0.1, "the person is not in the reference and must remain")

    def test_delay_search_finds_a_known_delay(self):
        from simorgh.voice.aec import delay_search
        rng = np.random.default_rng(3)
        ref = rng.standard_normal(SAMPLE_RATE).astype(np.float32) * 0.3
        delayed = np.concatenate([np.zeros(320, dtype=np.float32), ref])[: len(ref)]  # 20 ms
        found = delay_search(_i16(delayed), _i16(ref))
        self.assertTrue(300 <= found <= 340, f"expected ~320, got {found}")

    def test_erle_is_zero_on_silence_not_a_divide_by_zero(self):
        from simorgh.voice.aec import erle_db
        z = np.zeros(480, dtype=np.float32)
        self.assertEqual(erle_db(z, z), 0.0)


@unittest.skipUnless(_HAVE_NUMPY, "numpy is required for AEC")
class EchoCancellingDetectorTestCase(unittest.TestCase):
    def _detector(self, voice_says):
        from simorgh.voice.aec import EchoCanceller, EchoCancellingDetector

        class _V:
            name = "v"
            def is_speech(self, frame):
                return voice_says
        return EchoCancellingDetector(_V(), EchoCanceller(taps=512, mu=0.5), residual_threshold=0.05)

    def test_sim_only_is_never_a_person_even_when_voiced(self):
        det = self._detector(voice_says=True)  # the voice detector would say yes
        rng = np.random.default_rng(4)
        path = _echo_path()
        frame = SAMPLE_RATE * 30 // 1000
        tail = np.zeros(0, dtype=np.float32)
        fired = []
        for _ in range(100):
            ref = rng.standard_normal(frame).astype(np.float32) * 0.3
            full = np.convolve(np.concatenate([tail, ref]), path)
            mic = full[len(tail):len(tail) + frame]
            tail = ref[-len(path):]
            det.set_reference(_i16(ref))
            fired.append(det.is_speech(_i16(mic)))
        self.assertEqual(sum(fired[20:]), 0, "after convergence, Sim's own echo is not speech")

    def test_a_person_over_the_echo_is_speech(self):
        det = self._detector(voice_says=True)
        rng = np.random.default_rng(5)
        path = _echo_path()
        frame = SAMPLE_RATE * 30 // 1000
        tail = np.zeros(0, dtype=np.float32)
        for _ in range(60):  # converge
            ref = rng.standard_normal(frame).astype(np.float32) * 0.3
            mic = np.convolve(np.concatenate([tail, ref]), path)[len(tail):len(tail) + frame]
            tail = ref[-len(path):]
            det.set_reference(_i16(ref)); det.is_speech(_i16(mic))
        ref = rng.standard_normal(frame).astype(np.float32) * 0.3
        mic = np.convolve(np.concatenate([tail, ref]), path)[len(tail):len(tail) + frame]
        person = rng.standard_normal(frame).astype(np.float32) * 0.3
        det.set_reference(_i16(ref))
        self.assertTrue(det.is_speech(_i16(mic + person)))


class AvailabilityTestCase(unittest.TestCase):
    def test_available_reflects_numpy(self):
        from simorgh.voice.aec import available
        ok, why = available()
        self.assertEqual(ok, _HAVE_NUMPY)
        if not ok:
            self.assertIn("numpy", why)


if __name__ == "__main__":
    unittest.main()


class DefaultsTestCase(unittest.TestCase):
    def test_aec_is_on_by_default(self):
        from simorgh.voice.config import Config
        self.assertTrue(Config().aec, "AEC is the default barge-in path when numpy is present")


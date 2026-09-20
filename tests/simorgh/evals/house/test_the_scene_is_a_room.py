"""Stage 11 item 3: the room between a person and the microphone.

The arithmetic is tested here without any model, because a room that
is wrong quietly makes every later scenario lie. The measurements that
need Kokoro, whisper and the embedder are in
`docs/findings/2026-09-20-house-simulator.md`; what this pins is that
distance attenuates, noise is seeded, a bed is fitted to the speech it
sits under, and two people can talk over each other.
"""

import unittest

from simorgh.evals.house.scene import (
    DISTANCES, ROOMS, Scene, attenuate, distance_gain, mix, noise, noise_for, overlap,
    reverb, rms_of, silence,
)


def _tone(seconds: float = 0.5, amplitude: int = 8000):
    """A steady tone, so loudness changes are readable."""
    import array
    import math

    n = int(seconds * 16000)
    samples = array.array("h", (int(amplitude * math.sin(2 * math.pi * 220 * i / 16000)) for i in range(n)))
    from simorgh.voice.audio import Audio

    return Audio(samples.tobytes(), 16000)


class Distance(unittest.TestCase):
    def test_further_is_quieter(self):
        near, far = rms_of(attenuate(_tone(), distance_gain(1.0))), rms_of(attenuate(_tone(), distance_gain(6.0)))
        self.assertLess(far, near / 3)

    def test_leaning_over_the_microphone_is_louder_than_a_metre(self):
        self.assertGreater(distance_gain(0.3), distance_gain(1.0))

    def test_it_does_not_divide_by_zero_at_the_microphone(self):
        self.assertLess(distance_gain(0.0), 10.0)

    def test_a_distant_voice_is_not_merely_a_quiet_one(self):
        """Reverb is what stops the distance table lying: without it,
        six metres is one metre times a number."""
        self.assertNotEqual(reverb(_tone(), 6.0).pcm, attenuate(_tone(), 1.0).pcm)
        self.assertEqual(reverb(_tone(), 0.5).pcm, _tone().pcm, "no reflection up close")


class TheRoomBed(unittest.TestCase):
    def test_the_same_seed_is_the_same_room(self):
        """A scenario that failed has to be able to fail again."""
        self.assertEqual(noise(0.2, rms=500, seed=7).pcm, noise(0.2, rms=500, seed=7).pcm)
        self.assertNotEqual(noise(0.2, rms=500, seed=7).pcm, noise(0.2, rms=500, seed=8).pcm)

    def test_a_worse_room_is_a_louder_bed(self):
        speech = _tone()
        quiet = rms_of(noise_for(speech, ROOMS["quiet"]))
        party = rms_of(noise_for(speech, ROOMS["party"]))
        self.assertGreater(party, quiet)

    def test_every_named_room_has_a_ratio_and_every_distance_a_metre(self):
        self.assertTrue(all(isinstance(v, float) for v in ROOMS.values()))
        self.assertTrue(all(v > 0 for v in DISTANCES.values()))


class Mixing(unittest.TestCase):
    def test_a_mix_is_as_long_as_its_longest_layer(self):
        self.assertEqual(len(mix(_tone(0.2), _tone(0.5)).pcm), len(_tone(0.5).pcm))

    def test_mixing_nothing_is_silence_rather_than_a_crash(self):
        self.assertEqual(rms_of(mix()), 0.0)

    def test_two_people_can_talk_over_each_other(self):
        together = overlap(_tone(0.5), _tone(0.5), after=0.2)
        self.assertGreater(rms_of(together), rms_of(_tone(0.5)))

    def test_a_bed_is_fitted_to_what_it_sits_under(self):
        scene = Scene(room="quiet", playing=_tone(0.1))
        heard = scene.hear(_tone(1.0))
        self.assertEqual(len(heard.pcm), len(_tone(1.0).pcm),
                         "a short bed is looped, a long one trimmed")


class WhatTheMicrophoneGets(unittest.TestCase):
    def test_the_room_is_kept_between_beats(self):
        scene = Scene(room="kitchen", distance=3.0)
        self.assertEqual(scene.snr_db(), ROOMS["kitchen"])
        quiet_beat = rms_of(scene.hear(_tone()))
        self.assertGreater(quiet_beat, 0.0)

    def test_sims_own_voice_comes_back_into_its_microphone(self):
        """The echo path. On 2026-09-20 Sim's own "Still checking."
        arrived as a user turn, so the simulator has to be able to
        produce that."""
        without = Scene(room="clean").hear(_tone())
        with_echo = Scene(room="clean", last_said=_tone()).hear(_tone())
        self.assertGreater(rms_of(with_echo), rms_of(without))

    def test_a_beat_is_a_new_draw_of_the_room(self):
        scene = Scene(room="party")
        first, second = scene.hear(_tone()), scene.hear(_tone())
        self.assertNotEqual(first.pcm, second.pcm, "the same noise twice is not a room")


if __name__ == "__main__":
    unittest.main()

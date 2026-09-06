import collections
import random
import unittest

from simorgh.curiosity.api import Area, DriveContext
from simorgh.curiosity.config import Config
from simorgh.curiosity.drives import DriveEngine
from simorgh.curiosity.sampler import DriveWeightedSampler, softmax_sample


class SoftmaxSampleTest(unittest.TestCase):
    def test_high_temperature_approaches_uniform(self):
        rng = random.Random(1)
        scores = {"a": 10.0, "b": 0.0}
        counts = collections.Counter(softmax_sample(scores, rng=rng, temperature=1000.0) for _ in range(2000))
        ratio = counts["a"] / counts["b"]
        self.assertLess(ratio, 1.3)

    def test_low_temperature_approaches_greedy(self):
        rng = random.Random(1)
        scores = {"a": 10.0, "b": 0.0}
        counts = collections.Counter(softmax_sample(scores, rng=rng, temperature=1e-6) for _ in range(200))
        self.assertEqual(counts["a"], 200)

    def test_zero_temperature_does_not_raise(self):
        rng = random.Random(1)
        softmax_sample({"a": 1.0, "b": 2.0}, rng=rng, temperature=0.0)

    def test_all_names_reachable_over_many_draws(self):
        rng = random.Random(2)
        scores = {"a": 1.0, "b": 1.0, "c": 1.0}
        seen = {softmax_sample(scores, rng=rng, temperature=1.0) for _ in range(200)}
        self.assertEqual(seen, {"a", "b", "c"})


class DriveWeightedSamplerTest(unittest.TestCase):
    def setUp(self):
        self.sampler = DriveWeightedSampler(DriveEngine(Config()))

    def _ctx(self, areas):
        return DriveContext(areas=areas, gaps=(), interests=(), boredom=0.0, staleness_by_area={}, staleness_horizon=604800.0)

    def test_returns_none_with_no_areas(self):
        self.assertIsNone(self.sampler.pick(self._ctx(()), [], rng=random.Random(1), temperature=1.0))

    def test_area_with_no_modules_returns_none(self):
        ctx = self._ctx((Area(name="empty", modules=()),))
        self.assertIsNone(self.sampler.pick(ctx, [], rng=random.Random(1), temperature=1.0))

    def test_avoids_recent_subjects_when_alternative_exists(self):
        ctx = self._ctx((Area(name="a", modules=("m1.py", "m2.py")),))
        rng = random.Random(3)
        for _ in range(20):
            target = self.sampler.pick(ctx, ["m1.py"], rng=rng, temperature=1.0)
            self.assertEqual(target.subject, "m2.py")

    def test_falls_back_to_all_modules_when_all_recent(self):
        ctx = self._ctx((Area(name="a", modules=("m1.py", "m2.py")),))
        rng = random.Random(4)
        picks = {self.sampler.pick(ctx, ["m1.py", "m2.py"], rng=rng, temperature=1.0).subject for _ in range(20)}
        self.assertEqual(picks, {"m1.py", "m2.py"})

    def test_never_repeats_a_module_across_areas_before_every_module_is_tried_once(self):
        modules = {"a1.py", "a2.py", "b1.py"}
        ctx = self._ctx((Area(name="a", modules=("a1.py", "a2.py")), Area(name="b", modules=("b1.py",))))
        rng = random.Random(9)
        recent: list[str] = []
        seen: set[str] = set()
        for i in range(15):
            target = self.sampler.pick(ctx, recent[-30:], rng=rng, temperature=1.0)
            if target.subject in seen:
                self.assertEqual(seen, modules, f"{target.subject!r} repeated at pick {i} before every module was tried once")
            seen.add(target.subject)
            recent.append(target.subject)
        self.assertEqual(seen, modules)

    def test_score_table_covers_every_area(self):
        ctx = self._ctx((Area(name="a", modules=("m1.py",)), Area(name="b", modules=("m2.py",))))
        table = self.sampler.score_table(ctx)
        self.assertEqual(set(table), {"a", "b"})
        self.assertIn("total", table["a"])


if __name__ == "__main__":
    unittest.main()

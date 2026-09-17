"""Seven cameras tripping together is a queue, not a stampede.

2026-09-16, 23:46: seven Reolink cameras fired motion within the same
second. Each passed the per-camera guard (`camera in self._busy`, and a
90 s cooldown *per camera*), each spawned its own `asyncio.create_task`,
and seven seventeen-second vision questions went at one 3B model on one
machine at once. Nothing capped them, and there was no setting that
could.

Seventeen seconds is the measured cost of one frame through
`qwen2.5vl:3b` on this laptop. Seven at once do not take seventeen
seconds; they take longer than seven times that, because they fight for
the same GPU and the same memory. One at a time answers each in the time
one takes.

What must NOT change: a camera waiting its turn stays in `_busy`, so its
own repeats are still suppressed while it queues, and `_busy` is
released exactly once when it is done.
"""

from __future__ import annotations

import asyncio
import unittest


class _Vision:
    """The gate and the bookkeeping, without the cameras."""

    def __init__(self, width: int = 1):
        from simorgh.execution.vision import CameraVision

        self._config = type("C", (), {"camera_vision_concurrency": width})()
        self._busy: set[str] = set()
        self._looking = None
        self._live = 0
        self.most = 0
        self.order: list[str] = []
        self._gate = CameraVision._gate.__get__(self)          # noqa: SLF001
        self._look = CameraVision._look.__get__(self)          # noqa: SLF001

    async def _look_now(self, payload, camera):
        self._live += 1
        self.most = max(self.most, self._live)
        await asyncio.sleep(0.02)
        self.order.append(camera)
        self._live -= 1


class OneAtATimeTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_seven_cameras_are_looked_at_one_at_a_time(self):
        vision = _Vision(width=1)
        names = [f"cam{i}" for i in range(7)]
        for name in names:
            vision._busy.add(name)  # noqa: SLF001 -- as the caller does
        await asyncio.gather(*(vision._look({}, n) for n in names))  # noqa: SLF001
        self.assertEqual(vision.most, 1, "cameras were looked at concurrently")
        self.assertEqual(len(vision.order), 7, "a camera was dropped")

    async def test_a_wider_setting_really_widens(self):
        vision = _Vision(width=3)
        names = [f"cam{i}" for i in range(7)]
        for name in names:
            vision._busy.add(name)  # noqa: SLF001
        await asyncio.gather(*(vision._look({}, n) for n in names))  # noqa: SLF001
        self.assertEqual(vision.most, 3)

    async def test_a_queued_camera_stays_busy_until_it_has_been_looked_at(self):
        """Its own repeats must stay suppressed while it waits."""
        vision = _Vision(width=1)
        vision._busy.update({"a", "b"})  # noqa: SLF001
        first = asyncio.create_task(vision._look({}, "a"))  # noqa: SLF001
        second = asyncio.create_task(vision._look({}, "b"))  # noqa: SLF001
        await asyncio.sleep(0.005)
        self.assertIn("b", vision._busy, "a queued camera was released early")  # noqa: SLF001
        await asyncio.gather(first, second)
        self.assertEqual(vision._busy, set(), "a camera stayed busy for ever")  # noqa: SLF001

    async def test_a_failure_still_releases_the_camera(self):
        vision = _Vision(width=1)
        vision._busy.add("a")  # noqa: SLF001

        async def _boom(payload, camera):
            raise RuntimeError("the camera went away")

        vision._look_now = _boom  # noqa: SLF001
        with self.assertRaises(RuntimeError):
            await vision._look({}, "a")  # noqa: SLF001
        self.assertEqual(vision._busy, set(), "a failed look left the camera busy for ever")  # noqa: SLF001

    async def test_zero_or_nonsense_still_means_one(self):
        for width in (0, -4, None):
            with self.subTest(width=width):
                vision = _Vision(width=width)
                self.assertEqual(vision._gate()._value, 1)  # noqa: SLF001


class TheSettingTestCase(unittest.TestCase):
    def test_it_defaults_to_one(self):
        from simorgh.execution.config import Config

        self.assertEqual(Config().camera_vision_concurrency, 1)

    def test_it_can_be_set(self):
        from simorgh.execution.config import Config

        self.assertEqual(Config.from_mapping({"camera_vision_concurrency": 4}).camera_vision_concurrency, 4)

    def test_the_per_camera_cooldown_is_a_different_thing(self):
        """Widening concurrency must not quietly disable the cooldown."""
        from simorgh.execution.config import Config

        self.assertEqual(Config().camera_vision_cooldown_s, 90.0)


if __name__ == "__main__":
    unittest.main()

"""An ONVIF push must actually reach the bus (execution/home/cameras.py).

`ReolinkNvr.events` called `self._host.ONVIF_event_callback(body)` without
awaiting it. That method is a coroutine function -- the only one on
`reolink_aio`'s `Host` this module ever called unawaited, confirmed by
scanning all 105 of them. So its body never ran, `list()` raised
TypeError on the coroutine object, and `_watch`'s bare `except
Exception: return` swallowed it.

The effect was total and silent: **no `world.camera.event` was ever
published for a Reolink camera.** Every camera event the household saw
came from Ring. Motion on seven NVR cameras reached nothing -- no
description, no notice, and nothing for camera vision to answer about.
The only trace was a RuntimeWarning on the creator's console,
2026-09-16: "coroutine 'Host.ONVIF_event_callback' was never awaited".

It survived the test suite because the suite's fake host declared

    def events(self, body):        # sync

-- the opposite shape to the real library. The double could not exhibit
the bug, so the tests proved the caller worked against something that
was never going to fail. Same lesson as the overheard clock the same
day: a test that supplies both sides of a boundary proves the
arithmetic and nothing about the system.

So these tests assert the SHAPE against the real library's contract,
not against a convenient stand-in.
"""

from __future__ import annotations

import inspect
import unittest


class TheCallbackIsAwaitedTestCase(unittest.IsolatedAsyncioTestCase):
    def test_events_is_a_coroutine_function(self):
        """A sync `events` cannot await a coroutine callback, which is
        exactly how this broke."""
        from simorgh.domains.home.cameras import ReolinkNvr

        self.assertTrue(inspect.iscoroutinefunction(ReolinkNvr.events))

    def test_the_library_method_it_calls_really_is_a_coroutine(self):
        """If `reolink_aio` ever makes this synchronous, the `await`
        above becomes wrong and this test says so rather than the
        cameras going quiet again."""
        try:
            from reolink_aio.api import Host
        except ImportError:  # pragma: no cover -- optional dependency
            self.skipTest("reolink_aio is not installed")
        self.assertTrue(inspect.iscoroutinefunction(Host.ONVIF_event_callback))

    async def test_an_async_host_is_awaited_and_its_channels_come_back(self):
        from simorgh.domains.home.cameras import ReolinkNvr

        class _Host:
            def __init__(self) -> None:
                self.seen: list[str] = []

            async def ONVIF_event_callback(self, data, root=None):  # noqa: N802 -- the library's name
                self.seen.append(data)
                return [0, 6]

        nvr = object.__new__(ReolinkNvr)
        nvr._host = _Host()  # noqa: SLF001
        self.assertEqual(await nvr.events("<xml/>"), [0, 6])
        self.assertEqual(nvr._host.seen, ["<xml/>"])  # noqa: SLF001 -- the body actually ran

    async def test_a_callback_returning_nothing_is_no_channels(self):
        from simorgh.domains.home.cameras import ReolinkNvr

        class _Host:
            async def ONVIF_event_callback(self, data, root=None):  # noqa: N802
                return None

        nvr = object.__new__(ReolinkNvr)
        nvr._host = _Host()  # noqa: SLF001
        self.assertEqual(await nvr.events("<xml/>"), [])

    async def test_no_host_is_no_channels_rather_than_a_crash(self):
        from simorgh.domains.home.cameras import ReolinkNvr

        nvr = object.__new__(ReolinkNvr)
        nvr._host = None  # noqa: SLF001
        self.assertEqual(await nvr.events("<xml/>"), [])


class TheFailureIsNotSwallowedTestCase(unittest.TestCase):
    def test_the_watch_handler_no_longer_returns_in_silence(self):
        """The bare `except Exception: return` is what kept this
        invisible for as long as it was invisible."""
        import inspect as _inspect

        from simorgh.domains.home import cameras

        src = _inspect.getsource(cameras.CamWatchTool._watch)  # noqa: SLF001
        self.assertIn("await nvr.events(", src, "the call must be awaited")
        self.assertNotIn("except Exception:  # noqa: BLE001\n                return", src,
                         "a silent return here hid a total outage")


if __name__ == "__main__":
    unittest.main()

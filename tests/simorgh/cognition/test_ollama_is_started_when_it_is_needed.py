"""Sim starts the local engine rather than going blind without it.

2026-09-16, 23:46: seven cameras fired motion and every one of them
failed with "nothing here can look at a picture". The vision model was
configured and pulled (`qwen2.5vl:3b`); the only thing wrong was that
`ollama serve` was not running. Started by hand, the same frames were
described in seventeen seconds each -- including a bear in the backyard.

The creator, 2026-09-17, choosing between a LaunchAgent, doing it
himself, and this: "Sim starts it when needed".

Two properties carry the weight here.

It hangs off the EXISTING probe, inside its 30-second cache. A machine
with no Ollama installed must try occasionally, not once per request --
the difference between a retry and a fork bomb aimed at the user's own
laptop.

And it spawns detached. A child of Sim's process tree dies when Sim
exits, which is precisely the fault being fixed: that same evening a
30 GB download died twice because it was running inside a subprocess of
something that got closed.
"""

from __future__ import annotations

import unittest
from unittest import mock

from simorgh.cognition.providers.ollama import OllamaProvider


class _Down:
    """A local server that never answers."""

    def __init__(self):
        self.calls = 0

    def __call__(self, method, url, body, timeout):
        self.calls += 1
        raise OSError("connection refused")


class _UpAfterStart:
    """Answers only once something has started it."""

    def __init__(self):
        self.started = False
        self.calls = 0

    def __call__(self, method, url, body, timeout):
        self.calls += 1
        if not self.started:
            raise OSError("connection refused")
        return '{"version": "0.1.0"}'


class StartingItTestCase(unittest.TestCase):
    def test_a_dead_server_is_started_and_then_answers(self):
        transport = _UpAfterStart()
        provider = OllamaProvider(model="qwen3:4b-instruct", transport=transport)

        def _start():
            transport.started = True
            return True

        with mock.patch.object(provider, "_start_server", side_effect=_start) as started:
            self.assertTrue(provider.available())
            started.assert_called_once()

    def test_a_server_already_answering_is_not_started(self):
        provider = OllamaProvider(model="m", transport=lambda *a, **k: '{"version": "0.1.0"}')
        with mock.patch.object(provider, "_start_server") as started:
            self.assertTrue(provider.available())
            started.assert_not_called()

    def test_a_machine_without_ollama_stays_unavailable_and_does_not_raise(self):
        provider = OllamaProvider(model="m", transport=_Down())
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(provider.available())

    def test_it_tries_once_per_probe_window_not_once_per_request(self):
        """A permanently dead Ollama must not become a fork bomb."""
        provider = OllamaProvider(model="m", transport=_Down())
        with mock.patch.object(provider, "_start_server", return_value=False) as started:
            for _ in range(20):
                provider.available()
            self.assertEqual(started.call_count, 1, "it tried to start the server on every call")

    def test_no_model_configured_never_starts_anything(self):
        provider = OllamaProvider(model="", transport=_Down())
        with mock.patch.object(provider, "_start_server") as started:
            self.assertFalse(provider.available())
            started.assert_not_called()


class HowItSpawnsTestCase(unittest.TestCase):
    def test_it_is_detached_so_it_outlives_sim(self):
        provider = OllamaProvider(model="m")
        with mock.patch("shutil.which", return_value="/usr/local/bin/ollama"), \
                mock.patch("subprocess.Popen") as popen, mock.patch("time.sleep"):
            self.assertTrue(provider._start_server())  # noqa: SLF001
        kwargs = popen.call_args.kwargs
        self.assertTrue(kwargs.get("start_new_session"), "a child of Sim dies with Sim")
        self.assertEqual(popen.call_args.args[0], ["/usr/local/bin/ollama", "serve"])
        self.assertNotIn("shell", kwargs)

    def test_a_spawn_that_fails_is_false_not_an_exception(self):
        provider = OllamaProvider(model="m")
        with mock.patch("shutil.which", return_value="/usr/local/bin/ollama"), \
                mock.patch("subprocess.Popen", side_effect=OSError("no exec")):
            self.assertFalse(provider._start_server())  # noqa: SLF001

    def test_nothing_to_spawn_is_false_not_an_error(self):
        provider = OllamaProvider(model="m")
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(provider._start_server())  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()

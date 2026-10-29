"""tools/voice_setup.py on a Python newer than a package's cap.

The new Mac (Python 3.14, 2026-10-29): kokoro-onnx 0.6.1 declares
`<3.14`, so the whole pinned batch failed and `voice on` had no voice.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

_PATH = Path(__file__).resolve().parents[2] / "tools" / "voice_setup.py"
_spec = importlib.util.spec_from_file_location("voice_setup", _PATH)
voice_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(voice_setup)


class PastTheCapTestCase(unittest.TestCase):
    def _pip(self, fails_when):
        calls: list[tuple[str, ...]] = []

        def pip(*args):
            calls.append(args)
            return 1 if fails_when(args) else 0

        return pip, calls

    def test_a_batch_that_installs_is_one_call(self):
        pip, calls = self._pip(lambda args: False)
        self.assertEqual(voice_setup.install(("kokoro-onnx==0.6.1", "numpy"), pip=pip), 0)
        self.assertEqual(calls, [("kokoro-onnx==0.6.1", "numpy")])

    def test_kokoro_goes_in_past_its_cap_and_its_dependencies_normally(self):
        pip, calls = self._pip(lambda args: "kokoro-onnx==0.6.1" in args and "--ignore-requires-python" not in args)
        with mock.patch("importlib.metadata.requires", return_value=["onnxruntime>=1.20.1", "pytest; extra == 'dev'"]):
            rc = voice_setup.install(("kokoro-onnx==0.6.1", "numpy"), pip=pip)
        self.assertEqual(rc, 0)
        self.assertEqual(calls[1:], [("numpy",), ("--ignore-requires-python", "--no-deps", "kokoro-onnx==0.6.1"),
                                     ("onnxruntime>=1.20.1",)])

    def test_any_other_failure_is_still_a_failure(self):
        pip, _calls = self._pip(lambda args: "numpy" in args)
        self.assertEqual(voice_setup.install(("kokoro-onnx==0.6.1", "numpy"), pip=pip), 1)


if __name__ == "__main__":
    unittest.main()

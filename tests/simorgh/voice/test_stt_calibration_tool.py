"""`tools/stt_calibration.py` over a calibration set, with the fake
engine: no model, no microphone, no paid call."""

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.voice.calibration import CalibrationRun
from simorgh.voice.calibration_script import by_id

from tests.simorgh.voice.test_calibration import GOOD, _speech


class TheMeasurementTool(unittest.TestCase):
    """`tools/stt_calibration.py` over a set, with the fake engine: no
    model, no microphone, no paid call."""

    def test_it_prints_wer_and_latency_per_language(self):
        import contextlib
        import importlib.util
        import io

        root = Path(__file__).resolve().parents[3]
        spec = importlib.util.spec_from_file_location("stt_calibration", root / "tools" / "stt_calibration.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory() as tmp:
            run = CalibrationRun("Saeed", tmp, script=[by_id("en-038"), by_id("fa-001")],
                                 measure_fn=lambda p, r: GOOD)
            run.consider(_speech(1.0), transcript="Sim, thank you.")
            run.consider(_speech(1.0), transcript="سیم، ساعت چنده؟")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = tool.main(["--dir", tmp, "--engine", "fake", "--config", str(Path(tmp) / "none.toml"),
                                  "--json", str(Path(tmp) / "out.json")])
            self.assertEqual(code, 0, out.getvalue())
            numbers = json.loads((Path(tmp) / "out.json").read_text())["results"]
            (engine, per), = numbers.items()
            self.assertEqual(sorted(per), ["en", "fa"])
            self.assertEqual(per["en"]["takes"], 1)
            self.assertIn("latency_p95_s", per["fa"])
            self.assertIn("WER", out.getvalue())
            # the fake hears "hello sim" whatever is said: its WER is honest
            self.assertGreater(per["en"]["wer"], 0.0)


if __name__ == "__main__":
    unittest.main()

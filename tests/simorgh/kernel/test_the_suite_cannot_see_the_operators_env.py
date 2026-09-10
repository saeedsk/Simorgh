"""The test suite must not inherit `SIMORGH_*` from whoever ran it
(observer wave, 2026-09-10).

`LoadedConfig.__init__` applies `SIMORGH_<SECTION>_<KEY>` overrides
unconditionally, so `SIMORGH_RUNTIME_DATA_DIR` in the ambient
environment silently beats the explicit temp directory ~40 integration
tests pass in code:

    LoadedConfig({"runtime": {"data_dir": tmp.name}}, None)

Caught live. Sim was running with a non-default `data_dir` exported; its
own autonomous patch work calls `run_tests`; pytest inherited the
variable; and `tests/simorgh/integration` wrote a real jsonl Ledger into
the LIVE store -- 84 `memory:semantic` records in one session, several
of them the literal fixture string "the real answer", tagged
`consolidation` and stamped by a `FakeClock`, so the stream contained
memories dated decades apart and out of order. Recall serves those like
any other memory, and nothing afterwards can tell them from real ones.

Measured, same command, same machine, `tests/simorgh/integration`:

    without the guard:  54 failed, 194 passed -- and 5,007 files
                        written into the live data_dir
    with it:           248 passed -- and 0

`conftest.py`'s session fixture is the guard. This test is what stops
someone deleting it as unused.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from simorgh.kernel.config import LoadedConfig


class TestNoAmbientSimorghEnv(unittest.TestCase):
    def test_no_simorgh_env_override_is_visible_during_a_test(self):
        leaked = sorted(
            key for key in os.environ
            if key.startswith("SIMORGH_") and key != "SIMORGH_OBSERVER_RUN_ID"
        )
        self.assertEqual(leaked, [], f"conftest.py's session fixture is not stripping {leaked}")

    def test_an_explicitly_passed_data_dir_is_the_one_that_is_used(self):
        """The property the leak broke, stated directly: a data_dir
        handed to `LoadedConfig` in code is where the Ledger goes."""
        with tempfile.TemporaryDirectory() as tmp:
            config = LoadedConfig({"runtime": {"data_dir": tmp}}, None)
            self.assertEqual(config.runtime.data_dir, Path(tmp))

    def test_the_override_still_works_when_a_test_sets_it_on_purpose(self):
        """Stripping the ambient environment must not disable the
        feature -- a test that opts in still gets it."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["SIMORGH_RUNTIME_DATA_DIR"] = tmp
            try:
                config = LoadedConfig({"runtime": {"data_dir": "/nowhere"}}, None)
                self.assertEqual(config.runtime.data_dir, Path(tmp))
            finally:
                del os.environ["SIMORGH_RUNTIME_DATA_DIR"]


if __name__ == "__main__":
    unittest.main()

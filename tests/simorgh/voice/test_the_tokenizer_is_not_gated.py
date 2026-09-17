"""MisoTTS must not need a stranger's permission to say a word.

The creator, 2026-09-16, spent an evening hearing Kokoro while every
screen said `miso`. Under it all was this: `generator.py` asks Hugging
Face for `meta-llama/Llama-3.2-1B`, Meta's own Llama 3.2 tokenizer --
and that repo is `gated=manual`. A human at Meta grants each request by
hand. Until they do, the download is a 403, the engine dies during load,
and (with stderr going to /dev/null at the time) all anyone saw was
silence and a cheerful `spoken (miso)`.

Measured that night: `meta-llama/Llama-3.2-1B` gated=manual, download
403; `unsloth/Llama-3.2-1B` gated=False, download fine -- an ungated
mirror of the same tokenizer (vocab_size 128256, bos/eos 128000/128001,
model_type llama).

The wrinkle this file exists for: `workspace/` is gitignored, so the
patch to the vendored checkout cannot be committed. A later `voice
models miso` re-clones upstream and quietly restores the gated name, and
the whole evening happens again. So the override is re-applied by
`install()` after every clone, and these tests hold that.

The upstream-rewrite case matters most. If that line changes shape, the
patch must SAY so rather than silently do nothing -- a no-op reporting
success is how this class of fault survives.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from simorgh.voice.tts.miso import allow_an_ungated_tokenizer

UPSTREAM = '''def load_llama3_tokenizer():
    tokenizer_name = "meta-llama/Llama-3.2-1B"
    return tokenizer_name
'''


def _loaded(path: Path):
    namespace: dict = {}
    exec(compile(path.read_text(), "generator.py", "exec"), namespace)  # noqa: S102
    return namespace["load_llama3_tokenizer"]


class TheOverrideTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        previous = os.environ.get("MISO_TOKENIZER")

        def restore():
            os.environ.pop("MISO_TOKENIZER", None)
            if previous is not None:
                os.environ["MISO_TOKENIZER"] = previous

        self.addCleanup(restore)

    def _write(self, text: str = UPSTREAM) -> Path:
        path = self.repo / "generator.py"
        path.write_text(text)
        return path

    def test_a_fresh_checkout_is_patched(self):
        path = self._write()
        self.assertEqual(allow_an_ungated_tokenizer(self.repo, log=lambda *_: None), "")
        self.assertIn("MISO_TOKENIZER", path.read_text())

    def test_the_patched_source_really_reads_the_variable(self):
        """Not that the name appears -- that the code runs and uses it.
        A patch that parses and does nothing is the failure mode."""
        path = self._write()
        allow_an_ungated_tokenizer(self.repo, log=lambda *_: None)
        os.environ["MISO_TOKENIZER"] = "unsloth/Llama-3.2-1B"
        self.assertEqual(_loaded(path)(), "unsloth/Llama-3.2-1B")

    def test_the_gated_repo_is_still_the_fallback(self):
        """With nothing set it behaves exactly as upstream did, so a
        person who HAS been granted access loses nothing."""
        path = self._write()
        allow_an_ungated_tokenizer(self.repo, log=lambda *_: None)
        os.environ.pop("MISO_TOKENIZER", None)
        self.assertEqual(_loaded(path)(), "meta-llama/Llama-3.2-1B")

    def test_running_it_twice_changes_nothing(self):
        """`install()` runs on every `voice models miso`."""
        path = self._write()
        allow_an_ungated_tokenizer(self.repo, log=lambda *_: None)
        once = path.read_text()
        self.assertEqual(allow_an_ungated_tokenizer(self.repo, log=lambda *_: None), "")
        self.assertEqual(path.read_text(), once)

    def test_an_upstream_rewrite_is_reported_not_silently_ignored(self):
        self._write('def load_llama3_tokenizer():\n    tokenizer_name = SOMETHING_NEW\n')
        why = allow_an_ungated_tokenizer(self.repo, log=lambda *_: None)
        self.assertNotEqual(why, "")
        self.assertIn("gated", why)

    def test_a_missing_checkout_is_a_reason_not_a_crash(self):
        why = allow_an_ungated_tokenizer("/nonexistent-checkout", log=lambda *_: None)
        self.assertIn("could not read", why)


class TheDefaultTestCase(unittest.TestCase):
    def test_sim_asks_for_the_ungated_mirror_by_default(self):
        from simorgh.voice.config import Config

        self.assertEqual(Config().miso_tokenizer, "unsloth/Llama-3.2-1B")

    def test_it_can_be_pointed_back_at_meta(self):
        """Once Meta grants access, the gated repo is one setting away."""
        from simorgh.voice.config import Config

        self.assertEqual(
            Config.from_mapping({"miso_tokenizer": "meta-llama/Llama-3.2-1B"}).miso_tokenizer,
            "meta-llama/Llama-3.2-1B")


if __name__ == "__main__":
    unittest.main()

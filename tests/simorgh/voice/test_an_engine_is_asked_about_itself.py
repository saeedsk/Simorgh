"""A voice engine's readiness probe must import the engine, not a
dependency of it.

The creator, 2026-09-16: "misotts doesn't work, have you fixed it?"

It had not worked all evening, and nothing said so. `voice set tts miso`
was accepted, written into simorgh.toml, and answered "engines reopened;
listening again" -- while every spoken turn went on being synthesised by
Kokoro. Asked directly whether it was using Miso, Sim said no. Sim was
right and its own settings were wrong.

The cause was one argument. `available()` called

    engine_available("miso", "torch", venv_dir)

and `engine_available` runs `python -c "import <module>"` inside the
engine's venv. `torch` is a dependency of MisoTTS, not MisoTTS -- and
torch imported perfectly while the engine could not load at all, a numpy
2 ABI break further down the chain (torchtune -> datasets -> pyarrow).
Measured on the night: `torch: 2.4.0 | mps: True` printed from the same
interpreter run in which `import generator` raised
`numpy.core.multiarray failed to import`.

So the probe passed, `open_synthesiser` saw nothing to fall back from,
the refusal guard in `service._set` never fired -- and that guard is
good: it exists so a pick that cannot open is not kept. It was handed a
false answer. Chatterbox, which probes `chatterbox`, would have been
caught the same evening.

The rule this pins: ask an engine about ITSELF. A probe that names
something the engine merely depends on will pass for a broken engine
every time, and the failure then surfaces as silence rather than as a
refusal.
"""

from __future__ import annotations

import unittest


class TheProbeNamesTheEngineTestCase(unittest.TestCase):
    def test_miso_probes_its_own_module_not_torch(self):
        from simorgh.voice.tts import miso

        self.assertEqual(miso.ENGINE_MODULE, "generator")
        self.assertNotEqual(miso.ENGINE_MODULE, "torch", "probing a dependency passes for a broken engine")

    def test_the_synthesiser_probes_the_same_module(self):
        """`SubprocessSynthesiser.__init__` re-probes with `self.module`;
        if the two disagree, one of them is checking the wrong thing."""
        from simorgh.voice.tts import miso

        self.assertEqual(miso.MisoSynthesiser.module, miso.ENGINE_MODULE)

    def test_chatterbox_already_did_the_right_thing(self):
        """It probes `chatterbox`. This is the shape miso now matches --
        recorded so a later edit does not quietly swap it for `torch`."""
        import inspect

        from simorgh.voice.tts import chatterbox

        source = inspect.getsource(chatterbox.available)
        self.assertIn('"chatterbox"', source)

    def test_no_expressive_engine_probes_a_bare_dependency(self):
        """The guard against a second round of this. `torch` is the
        obvious wrong answer -- it is what every one of these engines is
        built on, so it always imports."""
        import inspect

        from simorgh.voice.tts import chatterbox, miso

        for module in (miso, chatterbox):
            with self.subTest(engine=module.__name__):
                source = inspect.getsource(module.available)
                self.assertNotIn('"torch"', source,
                                 "a readiness probe must import the engine, not what it depends on")


if __name__ == "__main__":
    unittest.main()

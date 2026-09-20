"""A whole Sim, booted where it can do no harm (stage 11 item 1).

Every real bug in this project was found by running the system, and
until now the running was done in the creator's kitchen, one turn at a
time, with his family in the room. This boots the same system -- the
real Kernel, the real Guardian, the real bus and ledger -- in a
temporary data directory with a fake house, a fake microphone and a
fake speaker, so a scenario can be as rude to it as it likes.

What is real, deliberately: the Kernel and every subsystem, Guardian's
whole pipeline (most of what is worth testing is whether it refuses),
the ledger, memory, the speaker book and its embedder. What is not:
the model (the floor provider answers unless a scenario pays for
better), the house (`FakeHomeAssistant`), the microphone, the speaker,
and anything that would reach a person -- `notify` has nowhere to go.

Nothing here touches `~/.simorgh`. The data directory is a temporary
one and dies with the sandbox unless `keep=` is given.
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
from pathlib import Path

from .record import Record

#: One frame of audio, in seconds. The fake microphone hands frames
#: over at this rate so the room runs in real time.
FRAME_SECONDS = 0.03

#: What the sandbox believes about the world unless a scenario says
#: otherwise. The floor provider is the default because a scenario that
#: costs money is a scenario nobody runs nightly.
DEFAULT_CONFIG: dict = {
    "cognition": {"provider_order": ["floor"]},
    # The fake engines: `voice/fakes.py`, the same ones the voice tests
    # drive. Real audio arrives with the scene (item 3).
    "voice": {"enabled": True, "stt": "fake", "tts": "fake",
              "microphone": "fake", "speaker": "fake",
              # `speakers_dir` is set per sandbox, in `start()`, to a
              # folder inside its own data directory. Without it the
              # sandbox reads and WRITES the live book at
              # `workspace/voice/speakers` -- which it did until
              # 2026-09-20, putting five synthetic personas among the
              # creator's family and letting scenarios be judged
              # against voices no scenario enrolled. "Never touches the
              # live data" has to mean every store, not just the
              # obvious one under ~/.simorgh.

              # A scenario says who is speaking; it does not mumble, and
              # an unheard word would be the scenario's bug rather than
              # Sim's.
              "min_confidence": 0.0},
    # Nothing in a sandbox may reach outside it, and the surest way to
    # mean that is to configure no way out. (`network` is not a key
    # anything reads -- the config checker said so on the first boot,
    # which is the check doing its job.)
    "execution": {"shell": False, "remote": False},
}


class Sandbox:
    """One booted Sim, with everything it said and did written down."""

    def __init__(self, *, config: dict | None = None, data_dir: str | Path | None = None,
                 keep: bool = False, spend_cap_usd: float = 0.0) -> None:
        self._extra = dict(config or {})
        self._tmp: tempfile.TemporaryDirectory | None = None
        self._given_dir = Path(data_dir) if data_dir else None
        self._keep = keep
        self._spend_cap_usd = float(spend_cap_usd)
        self.data_dir: Path | None = None
        self.kernel = None
        self.record = Record()
        self._subs: list = []
        self._voice_fakes: dict = {}
        #: The house the home tools reach, once booted: `FakeHomeAssistant`.
        self.house = None

    # -- lifecycle ----------------------------------------------------------------
    async def start(self) -> "Sandbox":
        from simorgh.kernel.config import LoadedConfig
        from simorgh.kernel.secrets import EnvSecretStore
        from simorgh.kernel.service import Kernel

        if self._given_dir is not None:
            self.data_dir = self._given_dir
            self.data_dir.mkdir(parents=True, exist_ok=True)
        else:
            self._tmp = tempfile.TemporaryDirectory(prefix="simorgh-house-")
            self.data_dir = Path(self._tmp.name)
        config = _merge(DEFAULT_CONFIG,
                        {"runtime": {"data_dir": str(self.data_dir)},
                         "voice": {"speakers_dir": str(self.data_dir / "speakers")}},
                        self._extra)
        with _voice_fakes(self._voice_fakes):
            self.kernel = Kernel(LoadedConfig(config, None), secrets=EnvSecretStore({}))
            await self.kernel.boot()
        await self._watch()
        self._wire_the_house()
        return self

    async def stop(self) -> None:
        for sub in self._subs:
            with contextlib.suppress(Exception):
                await sub.unsubscribe()
        self._subs.clear()
        if self.kernel is not None:
            with contextlib.suppress(Exception):
                await self.kernel.shutdown()
            self.kernel = None
        if self._tmp is not None and not self._keep:
            with contextlib.suppress(Exception):
                self._tmp.cleanup()
            self._tmp = None

    async def __aenter__(self) -> "Sandbox":
        return await self.start()

    async def __aexit__(self, *_exc) -> None:
        await self.stop()

    def copy_data_dir(self, into: str | Path) -> Path:
        """The data directory as it stands, kept. What `restart()` needs
        and what a failed scenario leaves for somebody to look at."""
        into = Path(into)
        shutil.copytree(self.data_dir, into, dirs_exist_ok=True)
        return into

    # -- what it can see ------------------------------------------------------------
    async def _watch(self) -> None:
        """Everything on the bus, every line printed, everything said."""
        from simorgh.contracts import topics

        async def _saw(message) -> None:
            self.record.saw(message)

        # Registered on the BACKEND, not through a client. A client is
        # policed -- `action.proposed` may be subscribed by Guardian and
        # nobody else, and a `#` from any other source is refused, which
        # is the policy working. But an observer that cannot see the
        # approval path cannot test the approval path, and the whole
        # point of this sandbox is watching Guardian refuse things. So
        # it watches below the policy rather than around it: it never
        # publishes, and nothing it sees changes what Sim does.
        from simorgh.bus.api import SubscriptionSpec

        self._subs.append(await self._bus_backend().register(
            SubscriptionSpec(pattern="#", group=None, durable=False, source="house-observer",
                             max_inflight=64), _saw))
        interface = self.service("interface")
        if interface is not None:
            interface._out = self.record.printed_line  # noqa: SLF001 -- the seam scenario.py already uses
        synthesiser = self._voice_fakes.get("synthesiser")
        if synthesiser is not None:
            _record_speech(synthesiser, self.record)
        assert topics  # the import documents that "#" is a bus pattern, not a topic

    def _wire_the_house(self) -> None:
        """Give the home tools a house they can really change.

        Until 2026-09-20 this docstring claimed `FakeHomeAssistant` and
        nothing connected it, so `home_call` could only ever fail --
        which meant every safety scenario asserting "the door did not
        unlock" passed with the whole tier system disabled. The
        absence of a door is not a locked door. This is the
        unconnected-wire bug written into the harness built to find it.

        Injection is by the seam the tool already has: `_HomeTool`
        takes `client=` and keeps it in `_given`, which the domain
        tests use. Every call is recorded at the far end, so an
        expectation can ask what the house DID rather than what
        Guardian said.
        """
        from simorgh.contracts.home.fakes import FakeHomeAssistant

        execution = self.service("execution")
        if execution is None:
            return
        self.house = FakeHomeAssistant()
        original = self.house.call

        async def _watched(service: str, *, entity_ids=(), data=None, **rest):
            # `**rest` on purpose: `home_call` passes `settle_s` too,
            # and a wrapper that pins today's signature turns a new
            # argument into a TypeError from inside the fake house.
            result = await original(service, entity_ids=entity_ids, data=data, **rest)
            self.record.house_did(service, entity_ids, data or {})
            return result

        self.house.call = _watched
        for tool in execution._registry.values():  # noqa: SLF001 -- the domain tools' own seam
            if getattr(tool, "name", "").startswith("home_"):
                tool._given = self.house  # noqa: SLF001

    def _bus_backend(self):
        return self.kernel._bus_backend  # noqa: SLF001 -- the observer seam; see `_watch`

    def service(self, name: str):
        """One subsystem's Service, or None. `growth` has parts:
        `sandbox.service("growth").monitors`."""
        holder = (self.kernel._supervisor.services.get(name) if self.kernel else None)  # noqa: SLF001
        return getattr(holder, "service", None) if holder is not None else None

    @property
    def microphone(self):
        return self._voice_fakes.get("microphone")

    @property
    def speaker(self):
        return self._voice_fakes.get("speaker")

    @property
    def recogniser(self):
        return self._voice_fakes.get("recogniser")


def _record_speech(synthesiser, record: Record) -> None:
    """Wrap the fake synthesiser so every piece is timed as it is asked
    for. Wrapping rather than replacing: the voice tests read
    `FakeSynthesiser.spoken`, and that must keep working."""
    original = synthesiser.synthesise

    async def _timed(text: str, *, voice: str = "", speed: float = 1.0, tone: str = ""):
        record.sim_spoke(text, voice=voice, speed=speed)
        return await original(text, voice=voice, speed=speed, tone=tone)

    synthesiser.synthesise = _timed


@contextlib.contextmanager
def _voice_fakes(into: dict):
    """Boot the Kernel with a voice Service holding fake engines.

    The Kernel builds its own factories (`kernel/registry.py`), and it
    is Guardian-protected, so rather than cutting a seam into it for a
    test harness this wraps the factory table for the length of one
    boot -- in a child process, in `simorgh/evals/`, which is itself
    protected. `voice.Service` already takes the four engines as
    arguments; this is only how they reach it.
    """
    from simorgh.kernel import service as kernel_service
    from simorgh.evals.house.hearing import ScriptedRecogniser
    from simorgh.voice.fakes import FakeMicrophone, FakeSpeaker, FakeSynthesiser

    original = kernel_service.build_factories

    def _wrapped(**kwargs):
        factories = original(**kwargs)
        if "voice" in factories:
            def _voice():
                from simorgh.voice.service import Service as VoiceService

                # Frames at the rate a microphone makes them. With the
                # default of 0 the fake room served 401 frames in 50 ms
                # -- minutes of "silence" delivered in an instant --
                # and the session's timers, which run on the wall
                # clock, never lined up with them: the first utterance
                # worked and every one after it was never heard
                # (2026-09-20). 30 ms is one frame.
                into["microphone"] = FakeMicrophone(frame_delay=FRAME_SECONDS)
                into["speaker"] = FakeSpeaker()
                into["recogniser"] = ScriptedRecogniser()
                into["synthesiser"] = FakeSynthesiser()
                return VoiceService(microphone=into["microphone"], speaker=into["speaker"],
                                    recogniser=into["recogniser"], synthesiser=into["synthesiser"])

            factories["voice"] = _voice
        return factories

    kernel_service.build_factories = _wrapped
    try:
        yield
    finally:
        kernel_service.build_factories = original


def _merge(*layers: dict) -> dict:
    """Later layers win, one level into each section."""
    out: dict = {}
    for layer in layers:
        for key, value in (layer or {}).items():
            if isinstance(value, dict) and isinstance(out.get(key), dict):
                out[key] = {**out[key], **value}
            else:
                out[key] = value
    return out


__all__ = ["DEFAULT_CONFIG", "FRAME_SECONDS", "Sandbox"]

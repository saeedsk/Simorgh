"""Stage 3 item 5: a tool known to be slow says so while it runs.

The wait a person in the kitchen sits through is usually the tool, not
the model. Sim already says "okay" when the turn ends and "still on it"
twenty seconds later; between those, a six-second `web_fetch` is a dead
line. `tool.started` carries the tool's recent p95, and the live voice
session says one short thing over it.

The three rules that matter are all about not becoming a tic: a fast
tool says nothing, an untimed tool says nothing (unknown is not slow),
and a turn that runs four slow tools still says it once.
"""

import unittest

from simorgh.orchestration.session import SessionRunner
from simorgh.voice.backchannel import LOOKING
from simorgh.voice.config import Config
from simorgh.voice.turns import THINKING


class _Turns:
    state = THINKING
    turn_id = 7


class _Pipeline:
    on_tool_started = None
    speaking = False


class _Session:
    """The three collaborators `_on_tool_started` actually touches."""

    def __init__(self, **overrides):
        from simorgh.voice.backchannel import Backchannel

        self._config = Config(**overrides)
        self._backchannel = Backchannel()
        self._pipeline = _Pipeline()
        self.turns = _Turns()
        self._answered: set[int] = set()
        self._filled: set[int] = set()
        self._last_aside_at = -1e9
        self._last_user_text = "what is the weather"
        self.said: list[str] = []

    async def _say_aside(self, request_id: str, text: str, *, delivery=None) -> bool:
        self.said.append(text)
        return True

    def _now(self) -> float:
        return 0.0

    # the method under test, bound from the real class
    from simorgh.voice.session import VoiceSession  # noqa: PLC0415

    _on_tool_started = VoiceSession._on_tool_started


class ASlowToolIsCoveredOutLoud(unittest.IsolatedAsyncioTestCase):
    async def test_a_slow_tool_says_something(self):
        session = _Session()
        await session._on_tool_started("web_fetch", 6000)  # noqa: SLF001
        self.assertEqual(len(session.said), 1)
        self.assertIn(session.said[0], LOOKING["en"])

    async def test_a_fast_tool_says_nothing(self):
        session = _Session()
        await session._on_tool_started("read_file", 120)  # noqa: SLF001
        self.assertEqual(session.said, [])

    async def test_a_tool_nobody_has_timed_says_nothing(self):
        """-1 is "no idea", which is not the same as fast -- but guessing
        slow would make every first call of a boot talk."""
        session = _Session()
        await session._on_tool_started("brand_new_tool", -1)  # noqa: SLF001
        self.assertEqual(session.said, [])

    async def test_once_per_turn_however_many_slow_tools(self):
        session = _Session()
        for tool in ("web_fetch", "run_tests", "search_code", "web_fetch"):
            await session._on_tool_started(tool, 9000)  # noqa: SLF001
        self.assertEqual(len(session.said), 1, "twice would be the tic, not a listener")

    async def test_nothing_is_said_once_the_answer_is_back(self):
        session = _Session()
        session._answered.add(7)  # noqa: SLF001
        await session._on_tool_started("web_fetch", 9000)  # noqa: SLF001
        self.assertEqual(session.said, [])

    async def test_the_setting_turns_it_off(self):
        session = _Session(filler_over_ms=0)
        await session._on_tool_started("web_fetch", 9000)  # noqa: SLF001
        self.assertEqual(session.said, [])

    async def test_backchannel_off_means_off(self):
        session = _Session(backchannel=False)
        await session._on_tool_started("web_fetch", 9000)  # noqa: SLF001
        self.assertEqual(session.said, [])


class TheRecentP95(unittest.TestCase):
    """Orchestration measures what each tool costs, so `tool.started`
    can carry it without a telemetry query on the very path it is
    trying to make feel faster."""

    def setUp(self):
        self.runner = SessionRunner.__new__(SessionRunner)
        self.runner._tool_ms = {}  # noqa: SLF001

    def test_an_unmeasured_tool_is_minus_one_not_zero(self):
        self.assertEqual(self.runner.recent_p95_ms("web_fetch"), -1)

    def test_a_tool_that_is_usually_slow_reads_as_slow(self):
        for ms in [6000.0] * 18 + [100.0, 200.0]:
            self.runner._note_tool_ms("web_fetch", ms)  # noqa: SLF001
        self.assertEqual(self.runner.recent_p95_ms("web_fetch"), 6000)

    def test_one_slow_call_in_twenty_is_not_a_slow_tool(self):
        """A p95, not a maximum: a tool that hangs once a month must not
        make Sim talk over every other call it makes."""
        for ms in [100.0] * 19 + [8000.0]:
            self.runner._note_tool_ms("read_file", ms)  # noqa: SLF001
        self.assertEqual(self.runner.recent_p95_ms("read_file"), 100)

    def test_only_the_recent_calls_count(self):
        """A tool that was slow a thousand calls ago is not slow now."""
        self.runner._note_tool_ms("run_tests", 60_000.0)  # noqa: SLF001
        for _ in range(SessionRunner.TOOL_MS_KEEP):
            self.runner._note_tool_ms("run_tests", 200.0)  # noqa: SLF001
        self.assertEqual(self.runner.recent_p95_ms("run_tests"), 200)


class TheEventIsPublishedWhenTheCallGoesOut(unittest.IsolatedAsyncioTestCase):
    """`tool.invoked` fires when a call FINISHES, which is exactly too
    late for anything covering the wait -- so there is a second event
    for the start, and the pipeline hands it to the live session."""

    async def test_the_pipeline_passes_the_name_and_the_p95_along(self):
        from simorgh.contracts import topics
        from simorgh.contracts.envelope import Message
        from simorgh.voice.pipeline import Pipeline

        pipeline = Pipeline.__new__(Pipeline)
        seen = []

        async def _handler(name, p95):
            seen.append((name, p95))

        pipeline.on_tool_started = _handler
        await pipeline._on_tool_started(Message.new(  # noqa: SLF001
            topics.TOOL_STARTED, source="orchestration",
            payload={"name": "web_fetch", "action_id": "a1", "recent_p95_ms": 6000}))
        self.assertEqual(seen, [("web_fetch", 6000)])

    async def test_no_live_session_means_nothing_is_said(self):
        from simorgh.contracts import topics
        from simorgh.contracts.envelope import Message
        from simorgh.voice.pipeline import Pipeline

        pipeline = Pipeline.__new__(Pipeline)
        pipeline.on_tool_started = None
        await pipeline._on_tool_started(Message.new(  # noqa: SLF001
            topics.TOOL_STARTED, source="orchestration",
            payload={"name": "web_fetch", "action_id": "a1", "recent_p95_ms": 6000}))


if __name__ == "__main__":
    unittest.main()

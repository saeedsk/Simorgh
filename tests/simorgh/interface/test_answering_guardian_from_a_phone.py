"""Answering Guardian's questions from somewhere other than the terminal.

Stage 12 item 3, and the spine of that stage. `ui.prompt` and
`ui.prompt.answered` have been on the Bus since Guardian could escalate,
and until now only the REPL ever published the answer -- so every
irreversible action waited for somebody sitting at that terminal, and
Sim's autonomy ended at the desk.

The rules here are the design, not the plumbing: the prompt's own timeout
still governs, the first answer wins and the second is told so, `approve`
is required and named when it is missing, and the question text passes
through unchanged because the point is that a person can judge what
Guardian escalated.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.protocols import Context
from simorgh.interface.config import Config as InterfaceConfig
from simorgh.interface.devices import DeviceBook
from simorgh.interface.httpapi import HttpApi
from simorgh.interface.service import Service
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock

from .test_service import _Logger


async def _never(_seconds: float) -> None:
    """A sleep that outlives the test: the watchdog must not fire."""
    await asyncio.sleep(3600)


class AnsweringFromAPhoneTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(self.backend, source="interface", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()
        self.ctx = Context(
            name="interface", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=_Logger(), data_dir=Path(self._tmp.name) / "data",
        )
        self.service = Service(InterfaceConfig(chat_reply_timeout_s=0.3), run_repl=False)
        await self.service.start(self.ctx)
        # `FakeClock.sleep` returns at once, so the prompt watchdog would
        # default every question in the same loop turn it arrived and there
        # would be nothing left to answer. The watchdog is the subject of
        # its own tests; here the question has to stay open, so this clock
        # sleeps for real.
        self.clock.sleep = _never                                   # noqa: SLF001
        self.other = make_client(self.backend, source="guardian", ledger=self.ledger, clock=self.clock.now)
        await self.other.start()
        self.answered: list[dict] = []

        async def _seen(message):
            self.answered.append(dict(message.payload))

        self.sub = await self.other.subscribe(topics.UI_PROMPT_ANSWERED, _seen)

        self.book = DeviceBook(Path(self._tmp.name) / "devices.json")
        self.api = HttpApi(bus=self.bus, ledger=self.ledger, token="shared", devices=self.book,
                           prompts=self.service.open_prompts, answer_prompt=self.service.answer_prompt)

    async def asyncTearDown(self):
        await self.sub.unsubscribe()
        await self.service.stop()
        await self.other.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    # ------------------------------------------------------------- helpers
    def _token(self, *, capabilities=("read", "chat", "approve")) -> str:
        pending = self.book.begin_pairing(name="iPhone", capabilities=capabilities)
        _, token = self.book.redeem(pending.code)
        return token

    def _bearer(self, token: str) -> dict:
        return {"authorization": f"Bearer {token}"}

    async def _ask(self, prompt_id: str = "p1", *, question: str = "run `rm -rf /tmp/x`?",
                   options=("yes", "no"), timeout_s: float = 120.0) -> None:
        """Guardian escalating, as it really does."""
        await self.other.publish(self.other.new(topics.UI_PROMPT, {
            "prompt_id": prompt_id, "question": question, "options": list(options),
            "timeout_s": timeout_s, "default": "no"}))
        for _ in range(200):
            await asyncio.sleep(0.005)
            if prompt_id in self.service._pending_prompts:      # noqa: SLF001
                return
        self.fail("the prompt never reached the interface")

    async def _answer(self, prompt_id: str, answer: str, *, token: str | None = None):
        handler = next(h for m, prefix, h in self.api._prefixes                 # noqa: SLF001
                       if m == "POST" and prefix == "/api/prompts/")
        headers = self._bearer(token) if token else {}
        status, body, _ = await handler({"rest": prompt_id}, json.dumps({"answer": answer}).encode(), headers)
        return status, json.loads(body)

    # --------------------------------------------------------------- tests
    async def test_a_question_can_be_read_and_answered_from_a_device(self):
        token = self._token()
        await self._ask()

        listed = self.service.open_prompts()
        self.assertEqual([p["prompt_id"] for p in listed], ["p1"])
        # Unchanged: a summary would be Sim deciding what matters about its
        # own request.
        self.assertEqual(listed[0]["question"], "run `rm -rf /tmp/x`?")
        self.assertEqual(listed[0]["options"], ["yes", "no"])

        status, body = await self._answer("p1", "yes", token=token)
        self.assertEqual(status, 200, body)
        for _ in range(200):
            await asyncio.sleep(0.005)
            if self.answered:
                break
        self.assertEqual(self.answered, [{"prompt_id": "p1", "answer": "yes"}])

    async def test_the_first_answer_wins_and_the_second_is_told(self):
        """The terminal and the phone can both be looking at the same
        question; Guardian has acted by the time the second arrives."""
        token = self._token()
        await self._ask()
        self.assertEqual((await self._answer("p1", "yes", token=token))[0], 200)
        for _ in range(200):
            await asyncio.sleep(0.005)
            if self.answered:
                break
        status, body = await self._answer("p1", "no", token=token)
        self.assertEqual(status, 409)
        self.assertIn("already been answered", body["error"]["detail"])
        self.assertEqual(len(self.answered), 1, "a second ui.prompt.answered was published")

    async def test_a_device_without_approve_is_refused_and_told_which_word(self):
        token = self._token(capabilities=("read", "chat"))
        await self._ask()
        status, body = await self._answer("p1", "yes", token=token)
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["capability"], "approve")
        self.assertIn("with approve", body["error"]["detail"])
        self.assertEqual(self.answered, [], "it answered anyway")

    async def test_no_token_answers_nothing(self):
        await self._ask()
        status, _ = await self._answer("p1", "yes")
        self.assertEqual(status, 403)
        self.assertEqual(self.answered, [])

    async def test_an_answer_outside_the_options_is_refused(self):
        token = self._token()
        await self._ask()
        status, body = await self._answer("p1", "maybe", token=token)
        self.assertEqual(status, 409)
        self.assertIn("one of", body["error"]["detail"])
        self.assertEqual(self.answered, [])

    async def test_a_question_that_is_not_there_is_not_invented(self):
        token = self._token()
        status, body = await self._answer("never-asked", "yes", token=token)
        self.assertEqual(status, 409)
        self.assertIn("already been answered", body["error"]["detail"])

    async def test_it_reports_how_long_is_left(self):
        await self._ask(timeout_s=60.0)
        left = self.service.open_prompts()[0]["seconds_left"]
        self.assertGreater(left, 0.0)
        self.assertLessEqual(left, 60.0)

    async def test_reading_the_list_needs_only_read(self):
        """Seeing that Sim is stuck rather than slow matters even without
        the grant to unstick it."""
        handler = self.api._routes[("GET", "/api/prompts")].handler       # noqa: SLF001
        await self._ask()
        status, body, _ = await handler({}, b"", self._bearer(self._token(capabilities=("read",))))
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["prompts"]), 1)

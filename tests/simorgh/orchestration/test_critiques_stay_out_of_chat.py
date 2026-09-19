"""Reflection's critiques are procedural memory: task sessions recall
them, chat turns do not (2026-09-18 evaluation, C7)."""

import unittest

from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.context import Assembler


class _Recorder:
    def __init__(self):
        self.kinds: list[list[str]] = []

    async def __call__(self, type_, payload, *, trace_id=None):
        self.kinds.append(list(payload.get("kinds") or []))
        return None, "test"


class CritiquesStayOutOfChat(unittest.IsolatedAsyncioTestCase):
    async def _kinds_for(self, profile):
        assembler = Assembler(bus=None)
        rec = _Recorder()
        assembler._request_with_reason = rec  # noqa: SLF001
        await assembler.assemble(Session(task_id="t", kind="x", mode="execute", profile=profile), "chat", user_text="hi")
        return [k for k in rec.kinds if k != ["working"]]

    async def test_a_chat_turn_never_asks_for_procedural_memory(self):
        for kinds in await self._kinds_for(profiles.CHAT):
            self.assertNotIn("procedural", kinds)

    async def test_a_patch_session_recalls_procedural_memory(self):
        kinds = await self._kinds_for(profiles.PATCH)
        self.assertTrue(any("procedural" in k for k in kinds), kinds)

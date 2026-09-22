"""A paused system does not verify (stage 0 item 32).

`_paused` was written and never read, so a verification -- the task's
tests, the model's own tests on a copy of its tree, a reviewer's model
calls -- went on running through a pause. It now waits for the resume,
and never answers early: "insufficient_evidence" is accepted by
Orchestration, so an early answer would be the false pass.
"""

import asyncio
import unittest
from types import SimpleNamespace

from simorgh.verification.service import VerificationService


class _Reached(Exception):
    pass


def _service():
    service = VerificationService()
    service._ctx = SimpleNamespace(bus=None)
    service.emitted = []

    async def _none(_vid):
        return None

    async def _emit(message, vid, tid, verdict, *rest):
        service.emitted.append(verdict)

    async def _resolve(_ref):
        raise _Reached()

    service._find_existing_result = _none
    service._emit_result = _emit
    service._resolve_subject = _resolve
    return service


def _request():
    return SimpleNamespace(payload={"verification_id": "v1", "task_id": "t1", "kind": "task", "subject_ref": "x"})


def _state(state):
    return SimpleNamespace(payload={"state": state})


class APause(unittest.IsolatedAsyncioTestCase):
    async def test_nothing_runs_until_the_resume(self):
        service = _service()
        await service._on_state_changed(_state("paused"))
        run = asyncio.ensure_future(service._run_verification(_request()))
        await asyncio.sleep(0.05)
        self.assertFalse(run.done(), "a verification ran through a pause")
        self.assertEqual(service.emitted, [], "a paused verification answered early")
        await service._on_state_changed(_state("running"))
        with self.assertRaises(_Reached):
            await asyncio.wait_for(run, 1)

    async def test_stopping_during_a_pause_answers_as_stopping(self):
        service = _service()
        await service._on_state_changed(_state("paused"))
        run = asyncio.ensure_future(service._run_verification(_request()))
        await asyncio.sleep(0.01)
        await service._on_state_changed(_state("stopping"))
        await asyncio.wait_for(run, 1)
        self.assertEqual(service.emitted, ["insufficient_evidence"])

    async def test_a_running_system_is_not_held(self):
        service = _service()
        with self.assertRaises(_Reached):
            await asyncio.wait_for(service._run_verification(_request()), 1)


if __name__ == "__main__":
    unittest.main()

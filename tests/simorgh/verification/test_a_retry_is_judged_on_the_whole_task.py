"""`did_anything` on a retry reads every attempt (stage 4 item 8).

A retry's verify subject carries only its own attempt's steps, so the
check stood itself down (`complete_log=False`) -- a retry that wrote
nothing in ANY attempt and said it had was never caught mechanically.
The `task:<id>` stream holds every attempt; Verification now reads it.
"""

import asyncio
import unittest
from types import SimpleNamespace

from simorgh.verification.api import CheckContext, VerifyRequest
from simorgh.verification.checks.didanything import DidAnythingCheck
from simorgh.verification.config import VerificationConfig
from simorgh.verification.trajectory import writes_in_task


class _Ledger:
    def __init__(self, steps):
        self.steps = steps

    async def read(self, stream):
        return [SimpleNamespace(type="task.step", payload=p) for p in self.steps]


def _req(task_writes):
    subject = {"kind": "patch", "result": "The change is applied and committed.", "complete_log": False,
               "steps": [{"phase": "act", "tool": "run_tests", "ok": True}]}
    if task_writes is not None:
        subject["task_writes"] = task_writes
    return VerifyRequest(verification_id="v", task_id="t", kind="task", subject=subject)


_CTX = CheckContext(act=None, think=None, review=None, clock=None, config=VerificationConfig())


class TheWholeTask(unittest.TestCase):
    def test_the_stream_names_every_attempts_writes_and_not_the_denied_ones(self):
        ledger = _Ledger([
            {"phase": "act", "tool": "replace_in_file", "summary": "1 change(s) applied"},
            {"phase": "act", "tool": "git_commit", "summary": "denied: protected path"},
            {"phase": "act", "tool": "read_file", "summary": "..."},
        ])
        self.assertEqual(asyncio.run(writes_in_task(ledger, "t")), ["replace_in_file"])

    def test_a_retry_after_an_earlier_write_passes(self):
        check = DidAnythingCheck()
        req = _req(["replace_in_file"])
        self.assertTrue(check.applies(req))
        self.assertEqual(asyncio.run(check.run(req, _CTX)).status, "passed")

    def test_a_retry_when_no_attempt_ever_wrote_fails(self):
        check = DidAnythingCheck()
        req = _req([])
        self.assertTrue(check.applies(req))
        self.assertEqual(asyncio.run(check.run(req, _CTX)).status, "failed")

    def test_without_the_stream_a_retry_is_still_left_alone(self):
        self.assertFalse(DidAnythingCheck().applies(_req(None)))


if __name__ == "__main__":
    unittest.main()

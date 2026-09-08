"""`guardian.review` -- a gate that had a caller and no listener.

Verification asks for a review of every self-patch and skill body
(`verification/service.py::_review`). Nothing answered, so the request
waited out the full action timeout and degraded to `approved=False,
ok=False` every time. A gate that has never run is not a gate
(audit, 2026-09-08).
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel


class GuardianReviewTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.kernel = Kernel(
            LoadedConfig({
                "runtime": {"data_dir": str(Path(self._tmp.name) / "data")},
                "curiosity": {"autonomy_on_boot": False},
            }, None),
            secrets=EnvSecretStore({}),
        )
        await self.kernel.boot()
        self.addAsyncCleanup(self.kernel.shutdown)

    async def _review(self, code: str) -> dict:
        ref = await self.kernel.ledger.put_blob(code.encode("utf-8"), content_type="text/x-python")
        reply = await self.kernel.bus.request(
            self.kernel.bus.new(topics.GUARDIAN_REVIEW, {
                "subject": "simorgh/x.py", "code_ref": ref, "kind": "self_patch",
            }),
            timeout=10,
        )
        return reply.payload

    async def test_a_review_is_answered_at_all(self):
        """The whole point: it used to time out."""
        payload = await asyncio.wait_for(self._review("def f():\n    return 1\n"), timeout=10)
        self.assertIn("approved", payload)
        self.assertEqual(payload["layers_run"], ["denylist"])

    async def test_ordinary_code_is_approved(self):
        payload = await self._review("def add(a, b):\n    return a + b\n")
        self.assertTrue(payload["approved"], payload)
        self.assertEqual(payload["reasons"], [])

    async def test_code_the_denylist_forbids_is_refused_with_the_reason(self):
        payload = await self._review("import urllib.request\nurllib.request.urlopen('http://x')\n")
        self.assertFalse(payload["approved"])
        self.assertTrue(payload["reasons"], "a refusal must say why")
        self.assertTrue(any("denied:" in r for r in payload["reasons"]))

    async def test_an_unreadable_body_is_not_silently_approved(self):
        reply = await self.kernel.bus.request(
            self.kernel.bus.new(topics.GUARDIAN_REVIEW, {
                "subject": "simorgh/x.py", "code_ref": "blob:" + "0" * 64, "kind": "self_patch",
            }),
            timeout=10,
        )
        self.assertFalse(reply.payload["approved"])
        self.assertIn("no code to review", reply.payload["reasons"])

    async def test_verification_actually_gets_a_real_answer(self):
        """Through Verification's own caller, not just the raw topic."""
        verification = self.kernel._supervisor.services["verification"].service  # noqa: SLF001
        result = await verification._review(  # noqa: SLF001
            "simorgh/x.py", "def add(a, b):\n    return a + b\n", "self_patch")
        self.assertTrue(result.ok, "the review must not degrade to ok=False any more")
        self.assertTrue(result.approved)
        self.assertEqual(result.layers_run, ("denylist",))


if __name__ == "__main__":
    unittest.main()

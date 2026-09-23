"""A rollback Sim never hears about is a regression it will make again.

`simloader.py` cannot write to the Ledger -- it never imports this
package, and that independence is the whole point of a bootloader -- so
it leaves `last_rollback.json` where `SIMORGH_LOADER_NOTES` points, and
the World Model reads it at boot and records a limitation.

That much worked. But `learn.self_patch.reverted` -- the counterpart of
the `applied` event a landing publishes, subscribed by Growth's monitors
AND by this service -- had no publisher anywhere
(`tools/scan_half_wired.py`, 2026-09-23). So a rollback became a private
note in the Self Model and the two subsystems built to learn from one
never heard a word.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts import topics


class _Bus:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def new(self, type, payload, **_kw):
        return (type, payload)

    async def publish(self, message):
        self.published.append(message)


class _Clock:
    def now(self):
        return 1000.0


class _Ctx:
    def __init__(self, bus):
        self.bus = bus
        self.clock = _Clock()


class ARollbackIsSaidOutLoud(unittest.IsolatedAsyncioTestCase):
    async def _ingest(self, note: dict | None, *, twice: bool = False):
        from simorgh.worldmodel.service import Service

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        notes = Path(tmp.name)
        if note is not None:
            (notes / "last_rollback.json").write_text(json.dumps(note))
        service = Service.__new__(Service)
        recorded: list[tuple] = []

        async def _record(kind, payload, *, section="", reason=""):
            recorded.append((kind, payload, reason))

        service._record = _record                          # noqa: SLF001
        bus = _Bus()
        ctx = _Ctx(bus)
        with mock.patch.dict("os.environ", {"SIMORGH_LOADER_NOTES": str(notes)}):
            await service._ingest_loader_rollback(ctx)     # noqa: SLF001
            if twice:
                await service._ingest_loader_rollback(ctx)  # noqa: SLF001
        return bus, recorded

    async def test_the_rollback_is_both_remembered_and_announced(self):
        bus, recorded = await self._ingest({"from": "abc123", "to": "def456",
                                            "reason": "the house gate failed", "ts": "1"})
        self.assertEqual([k for k, _p, _r in recorded], ["limitation"], "it is still a fact about itself")
        self.assertEqual(len(bus.published), 1)
        topic, payload = bus.published[0]
        self.assertEqual(topic, topics.LEARN_SELF_PATCH_REVERTED)
        self.assertEqual(payload["commit"], "def456")
        self.assertIn("house gate", payload["reason"])

    async def test_a_second_boot_does_not_announce_it_again(self):
        bus, recorded = await self._ingest({"from": "abc123", "to": "def456", "reason": "x", "ts": "1"},
                                           twice=True)
        self.assertEqual(len(bus.published), 1, "one rollback, one event, however often Sim restarts")
        self.assertEqual(len(recorded), 1)

    async def test_no_rollback_no_event(self):
        bus, recorded = await self._ingest(None)
        self.assertEqual((bus.published, recorded), ([], []))


if __name__ == "__main__":
    unittest.main()

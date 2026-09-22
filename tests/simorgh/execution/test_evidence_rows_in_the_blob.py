"""A read's rows are evidence, and a small copy of them stays in the blob.

`metadata_for_blob` swaps `rows` for a pointer string (W21-07: the full
list already lives in `results/`, capped). That left the World Model no
way to fold what Sim had just READ about the house: `home_state` and
`media_now` report current state only in `rows`. A tool that declares
`evidence_fields` now gets a bounded, projected copy as `rows_kept`
(stage 6 item 3, 2026-09-22); every other tool is exactly as before.
"""

from __future__ import annotations

import json
import unittest

from simorgh.contracts import topics
from simorgh.contracts.protocols import ToolResult
from simorgh.domains.home.tools import HomeCallTool, HomeStateTool
from simorgh.domains.media.tools import MediaNowTool
from simorgh.execution.service import (
    EVIDENCE_MAX_BYTES,
    EVIDENCE_MAX_CHARS,
    EVIDENCE_MAX_ROWS,
    evidence_fields_of,
    metadata_for_blob,
)
from tests.simorgh.execution.test_service import _ExecutionServiceTestCase


class WhatIsKept(unittest.TestCase):
    def test_a_tool_that_declares_nothing_keeps_no_rows(self):
        meta = metadata_for_blob({"rows": [{"entity_id": "light.a", "state": "on"}]})
        self.assertNotIn("rows_kept", meta)
        self.assertEqual(meta["rows"], "<1 rows -- see the results file named in the output>")

    def test_declared_fields_are_kept_beside_the_pointer(self):
        rows = [{"entity_id": "light.a", "state": "on", "attributes": {"brightness": 200}}]
        meta = metadata_for_blob({"rows": rows}, evidence_fields=("entity_id", "state"))
        self.assertEqual(meta["rows"], "<1 rows -- see the results file named in the output>")
        self.assertEqual(meta["rows_kept"], [{"entity_id": "light.a", "state": "on"}])
        self.assertEqual(meta["rows_total"], 1)

    def test_only_scalars_survive_and_strings_are_cut(self):
        rows = [{"entity_id": "media_player.a", "state": "x" * 5000, "title": {"nested": 1},
                 "volume": None}]
        kept = metadata_for_blob({"rows": rows}, evidence_fields=("entity_id", "state", "title", "volume"))
        row = kept["rows_kept"][0]
        self.assertEqual(len(row["state"]), EVIDENCE_MAX_CHARS)
        self.assertNotIn("title", row)
        self.assertIsNone(row["volume"])

    def test_the_count_is_bounded_and_the_total_is_honest(self):
        rows = [{"entity_id": f"light.l{i}", "state": "on"} for i in range(900)]
        meta = metadata_for_blob({"rows": rows}, evidence_fields=("entity_id", "state"))
        self.assertEqual(len(meta["rows_kept"]), EVIDENCE_MAX_ROWS)
        self.assertEqual(meta["rows_total"], 900)

    def test_the_size_is_bounded_whatever_the_rows_look_like(self):
        rows = [{"entity_id": f"sensor.s{i}", "state": "y" * 1000} for i in range(EVIDENCE_MAX_ROWS)]
        meta = metadata_for_blob({"rows": rows}, evidence_fields=("entity_id", "state"))
        self.assertLessEqual(len(json.dumps(meta["rows_kept"]).encode("utf-8")), EVIDENCE_MAX_BYTES)
        self.assertLess(len(meta["rows_kept"]), EVIDENCE_MAX_ROWS)
        self.assertGreater(len(meta["rows_kept"]), 0)

    def test_the_callers_rows_are_not_mutated(self):
        rows = [{"entity_id": "light.a", "state": "on", "attributes": {}}]
        metadata_for_blob({"rows": rows}, evidence_fields=("entity_id",))
        self.assertEqual(rows, [{"entity_id": "light.a", "state": "on", "attributes": {}}])


class WhoDeclaresIt(unittest.TestCase):
    def test_the_house_reads_declare_their_evidence(self):
        self.assertEqual(evidence_fields_of(HomeStateTool), ("entity_id", "state"))
        self.assertEqual(evidence_fields_of(MediaNowTool), ("entity_id", "state", "title", "volume"))

    def test_a_tool_that_declares_nothing_or_nonsense_keeps_nothing(self):
        self.assertEqual(evidence_fields_of(HomeCallTool), ())
        self.assertEqual(evidence_fields_of(type("T", (), {"evidence_fields": "entity_id"})), ())
        self.assertEqual(evidence_fields_of(type("T", (), {"evidence_fields": 3})), ())


class _Read:
    name, description, args_schema = "evidence_read", "reads", {}
    read_only, reversibility = True, "read_only"
    evidence_fields = ("entity_id", "state")

    async def run(self, args, *, ctx):
        return ToolResult(ok=True, output="1 thing", metadata={
            "rows": [{"entity_id": "light.a", "state": "on", "attributes": {"big": "x" * 100}}]})


class TheServiceWritesTheKeptRows(_ExecutionServiceTestCase):
    """Through `_on_approved`: the blob the live `action.result` names
    carries `rows_kept` for a tool that declares `evidence_fields`."""

    async def test_the_blob_named_by_metadata_ref_holds_the_kept_rows(self):
        await self._start()
        await self._guardian(approve=True)
        self.service._registry["evidence_read"] = _Read()  # noqa: SLF001
        seen: list[dict] = []

        async def _on(message):
            if message.payload.get("tool") == "evidence_read":
                seen.append(message.payload)

        sub = await self.bus.subscribe(topics.ACTION_RESULT, _on)
        self.addAsyncCleanup(sub.unsubscribe)
        await self.service._self_actions.run("evidence_read", {}, rationale="test", timeout=5)  # noqa: SLF001
        self.assertEqual(len(seen), 1)
        blob = json.loads((await self.ledger.get_blob(seen[0]["metadata_ref"])).decode("utf-8"))
        self.assertEqual(blob["rows_kept"], [{"entity_id": "light.a", "state": "on"}])
        self.assertEqual(blob["rows_total"], 1)
        self.assertIsInstance(blob["rows"], str)


if __name__ == "__main__":
    unittest.main()

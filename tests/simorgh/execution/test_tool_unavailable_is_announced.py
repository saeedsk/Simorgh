"""A failed capability probe has to reach the World Model.

`tool.unavailable {name, reason}` is in the contract catalog, is listed
in 08-execution.md section 8 as what a builtin with a missing dependency
"registers as", and is listed in 06-worldmodel.md section 5 as one of
the events that updates the Self Model's capability inventory.
`WorldModel._on_tool_unavailable` subscribes to it and
`ToolsFacet.on_unavailable` flips `available`. Both halves worked.

Nothing in the tree ever published the message (tools/scan_half_wired.py,
2026-09-10), so `available` was set True at registration and could never
become False: on a machine with no Node and no Docker, asking Sim what
tools it has got a list saying all of them work.
"""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.execution.capabilities import ProbeResult


class _Bus:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, message) -> None:
        self.published.append(message)


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class _Ctx:
    def __init__(self) -> None:
        self.bus = _Bus()
        self.logger = _Logger()


class AnnouncingTestCase(unittest.IsolatedAsyncioTestCase):
    def _service(self):
        from simorgh.execution.service import Service

        service = Service.__new__(Service)  # no boot: `_announce_unavailable` needs only `_ctx`
        service._ctx = _Ctx()  # noqa: SLF001
        return service

    def _unavailable(self, service):
        return [m for m in service._ctx.bus.published  # noqa: SLF001
                if m.type == topics.TOOL_UNAVAILABLE]

    async def test_a_failed_free_probe_names_every_tool_it_takes_down(self):
        service = self._service()
        # `node` covers run_js_sandboxed and render_page (capabilities.PROBES).
        await service._announce_unavailable(  # noqa: SLF001
            ProbeResult(name="node", ok=False, detail="node is not installed", cost="free"))
        published = self._unavailable(service)
        self.assertEqual({m.payload["name"] for m in published},
                         {"run_js_sandboxed", "render_page"})
        for message in published:
            self.assertEqual(message.payload["reason"], "node is not installed")

    async def test_a_passing_probe_announces_nothing(self):
        service = self._service()
        await service._announce_unavailable(  # noqa: SLF001
            ProbeResult(name="node", ok=True, detail="node v22", cost="free"))
        self.assertEqual(self._unavailable(service), [])

    async def test_a_failed_network_probe_announces_nothing(self):
        """A `cheap` probe failing may only mean the laptop is offline,
        and `degraded_detail` already refuses to call that degradation."""
        service = self._service()
        await service._announce_unavailable(  # noqa: SLF001
            ProbeResult(name="puppeteer", ok=False, detail="timed out", cost="cheap"))
        self.assertEqual(self._unavailable(service), [])

    async def test_the_payload_satisfies_the_contract(self):
        from simorgh.contracts.envelope import validate

        service = self._service()
        await service._announce_unavailable(  # noqa: SLF001
            ProbeResult(name="docker", ok=False, detail="docker is not installed", cost="free"))
        for message in self._unavailable(service):
            validate(message)  # raises if `name`/`reason` are wrong

    async def test_execution_declares_what_it_now_produces(self):
        from simorgh.execution.service import Service

        self.assertIn(topics.TOOL_UNAVAILABLE, Service.produces)


class ToolsFacetTestCase(unittest.TestCase):
    """`available` used to be a one-way latch."""

    def _facet(self):
        from simorgh.worldmodel.facets.registry_facets import ToolsFacet

        facet = ToolsFacet()
        facet.on_registered("run_js_sandboxed", {"read_only": True})
        return facet

    def test_unavailable_flips_it_and_keeps_the_reason(self):
        facet = self._facet()
        facet.on_unavailable("run_js_sandboxed", "node is not installed")
        entry = facet._tools["run_js_sandboxed"]  # noqa: SLF001
        self.assertFalse(entry["available"])
        self.assertEqual(entry["reason"], "node is not installed")

    def test_a_passing_probe_puts_it_back(self):
        facet = self._facet()
        facet.on_unavailable("run_js_sandboxed", "node is not installed")
        facet.on_available("run_js_sandboxed")
        entry = facet._tools["run_js_sandboxed"]  # noqa: SLF001
        self.assertTrue(entry["available"])
        self.assertNotIn("reason", entry, "a stale reason beside a working tool is its own lie")

    def test_an_unknown_tool_is_ignored_either_way(self):
        facet = self._facet()
        facet.on_unavailable("nope", "x")
        facet.on_available("nope")
        self.assertNotIn("nope", facet._tools)  # noqa: SLF001


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

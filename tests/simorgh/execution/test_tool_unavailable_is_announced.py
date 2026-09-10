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


class OneFailingProbeBeatsAPassingOneTestCase(unittest.IsolatedAsyncioTestCase):
    """`render_page` needs BOTH `node` and `puppeteer`.

    The announcement half only fires for a FAILED FREE probe; the
    recovery half (`WorldModel._on_tool_probed`) puts a tool back on ANY
    passing probe that covers it. Interleaved per result -- publish
    `tool.probed{node, ok:false}`, announce `render_page` unavailable,
    then publish `tool.probed{puppeteer, ok:true}` -- the last word
    belonged to the passing probe, and `render_page` came out available
    on a machine with no Node at all. That is the latch this pair of
    messages was added to break, restored one probe order over
    (observer, 2026-09-10).
    """

    def _service(self, results):
        from simorgh.execution import service as service_module

        service = service_module.Service.__new__(service_module.Service)
        service._ctx = _Ctx()  # noqa: SLF001
        service._connectors = []  # noqa: SLF001

        async def _fake_run_probes(probes, **kwargs):
            return results

        self._original = service_module.run_probes
        service_module.run_probes = _fake_run_probes
        self.addCleanup(setattr, service_module, "run_probes", self._original)
        return service

    async def test_render_page_stays_unavailable_when_node_is_missing(self):
        from simorgh.worldmodel.facets.registry_facets import ToolsFacet

        service = self._service([
            ProbeResult(name="node", ok=False, detail="node is not installed", cost="free"),
            ProbeResult(name="puppeteer", ok=True, detail="puppeteer 24.1.0", cost="cheap"),
        ])
        await service._probe_capabilities()  # noqa: SLF001

        facet = ToolsFacet()
        for name in ("run_js_sandboxed", "render_page"):
            facet.on_registered(name, {"read_only": True})
        # Exactly what `worldmodel/service.py` does with each message, in
        # the order Execution published them.
        for message in service._ctx.bus.published:  # noqa: SLF001
            if message.type == topics.TOOL_PROBED and message.payload.get("ok"):
                for tool in message.payload.get("tools") or []:
                    facet.on_available(str(tool))
            elif message.type == topics.TOOL_UNAVAILABLE:
                facet.on_unavailable(message.payload["name"], message.payload["reason"])

        entry = facet._tools["render_page"]  # noqa: SLF001
        self.assertFalse(entry["available"], "a passing probe must not overrule a failing dependency")
        self.assertEqual(entry["reason"], "node is not installed")
        self.assertFalse(facet._tools["run_js_sandboxed"]["available"])  # noqa: SLF001

    async def test_a_pass_on_every_probe_leaves_everything_available(self):
        from simorgh.worldmodel.facets.registry_facets import ToolsFacet

        service = self._service([
            ProbeResult(name="node", ok=True, detail="node v22", cost="free"),
            ProbeResult(name="puppeteer", ok=True, detail="puppeteer 24.1.0", cost="cheap"),
        ])
        await service._probe_capabilities()  # noqa: SLF001
        facet = ToolsFacet()
        facet.on_registered("render_page", {"read_only": True})
        facet.on_unavailable("render_page", "stale from an earlier pass")
        for message in service._ctx.bus.published:  # noqa: SLF001
            if message.type == topics.TOOL_PROBED and message.payload.get("ok"):
                for tool in message.payload.get("tools") or []:
                    facet.on_available(str(tool))
            elif message.type == topics.TOOL_UNAVAILABLE:
                facet.on_unavailable(message.payload["name"], message.payload["reason"])
        self.assertTrue(facet._tools["render_page"]["available"])  # noqa: SLF001


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

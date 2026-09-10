"""Capability probes (execution/capabilities.py) and the one line of
prompt they are allowed to write.

Half the toolset added on 2026-09-09 stands on something outside this
repository. Each is allowed to be absent -- every tool refuses cleanly
-- but "absent" was invisible until a task tried and failed, and an
unofficial source that quietly stops returning anything is worse: the
tool still answers, so nothing looks broken.
"""

from __future__ import annotations

import unittest
from pathlib import Path
import tempfile
import types
import unittest.mock

from simorgh.execution.capabilities import (
    Probe, ProbeResult, degraded_detail, run_probes,
)
from simorgh.orchestration import scaffolds


def _probe(name, ok, detail="d", cost="free", tools=()):
    async def _run():
        return ok, detail

    return Probe(name, cost, _run, tools=tools)


class RunProbesTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_only_the_requested_costs_run(self):
        probes = (_probe("a", True), _probe("b", True, cost="network"))
        results = await run_probes(probes, include=("free",))
        self.assertEqual([r.name for r in results], ["a"])

    async def test_a_probe_that_raises_is_a_failed_probe_not_a_crash(self):
        async def _boom():
            raise RuntimeError("no")

        results = await run_probes((Probe("x", "free", _boom),), include=("free",))
        self.assertFalse(results[0].ok)
        self.assertIn("probe raised", results[0].detail)

    async def test_results_carry_the_clock_time(self):
        results = await run_probes((_probe("a", True),), include=("free",), clock=lambda: 123.0)
        self.assertEqual(results[0].at, 123.0)


class DegradedDetailTestCase(unittest.TestCase):
    def test_a_failed_free_probe_degrades_health(self):
        results = [ProbeResult("node", False, "not on PATH", "free")]
        self.assertIn("node", degraded_detail(results))

    def test_a_failed_network_probe_does_not(self):
        # The laptop may simply be offline; that is not a broken install.
        results = [ProbeResult("geocode", False, "no route to host", "network")]
        self.assertEqual(degraded_detail(results), "")

    def test_all_well_says_nothing(self):
        self.assertEqual(degraded_detail([ProbeResult("node", True, "ok", "free")]), "")


class PromptWarningTestCase(unittest.TestCase):
    def setUp(self):
        scaffolds._UNAVAILABLE.clear()
        self.addCleanup(scaffolds._UNAVAILABLE.clear)

    def test_a_broken_tool_that_is_offered_is_named(self):
        scaffolds.note_capability("puppeteer", ok=False, detail="not installed", tools=("render_page",))
        note = scaffolds.unavailable_note(["read_file", "render_page"])
        self.assertIn("render_page", note)
        self.assertIn("not installed", note)

    def test_a_broken_tool_that_is_not_offered_is_not_mentioned(self):
        scaffolds.note_capability("docker", ok=False, detail="daemon down", tools=("run_container",))
        self.assertEqual(scaffolds.unavailable_note(["read_file"]), "")

    def test_everything_working_costs_nothing_in_the_prompt(self):
        scaffolds.note_capability("node", ok=True, detail="ok", tools=("run_js_sandboxed",))
        self.assertEqual(scaffolds.unavailable_note(["run_js_sandboxed"]), "")

    def test_a_recovered_capability_stops_being_reported(self):
        scaffolds.note_capability("node", ok=False, detail="gone", tools=("run_js_sandboxed",))
        self.assertNotEqual(scaffolds.unavailable_note(["run_js_sandboxed"]), "")
        scaffolds.note_capability("node", ok=True, detail="back", tools=("run_js_sandboxed",))
        self.assertEqual(scaffolds.unavailable_note(["run_js_sandboxed"]), "")

    def test_the_warning_reaches_the_rendered_scaffold(self):
        from simorgh.orchestration import profiles

        scaffolds.note_capability("puppeteer", ok=False, detail="not installed", tools=("render_page",))
        text = scaffolds.render(profiles.PATCH, subject=None, task="do a thing",
                                unavailable=scaffolds.unavailable_note(profiles.PATCH.tools))
        self.assertIn("Do not spend steps on these", text)
        self.assertIn("render_page", text)

    def test_a_clean_session_renders_exactly_as_before(self):
        from simorgh.orchestration import profiles

        with_note = scaffolds.render(profiles.PATCH, task="x", unavailable="")
        self.assertNotIn("Do not spend steps", with_note)


class RealProbesTestCase(unittest.IsolatedAsyncioTestCase):
    """The real table against this machine. Asserts shape, not outcome:
    whether node or docker happens to be installed is not this test's
    business -- that every probe answers honestly is."""

    async def test_every_free_and_cheap_probe_answers(self):
        results = await run_probes()
        self.assertTrue(results)
        for result in results:
            self.assertIsInstance(result.ok, bool)
            self.assertTrue(result.detail, f"{result.name} gave no detail")

    async def test_bandit_and_homeharvest_are_seen_as_installed_here(self):
        # Both were installed on 2026-09-09 for StaticAnalysisRule and
        # search_listings; if this fails, the probe is lying or the
        # dependency is gone -- either is worth knowing.
        import importlib.util

        results = {r.name: r for r in await run_probes()}
        for name in ("bandit", "homeharvest"):
            expected = importlib.util.find_spec(name) is not None
            self.assertEqual(results[name].ok, expected)


class SourcebookTestCase(unittest.TestCase):
    """The keyless-source index in the RESEARCH prompt and
    `docs/sourcebook.md` are two renderings of one fact, and a prompt
    that names a source the doc does not explain is worse than useless."""

    def test_every_source_named_in_the_prompt_appears_in_the_doc(self):
        from pathlib import Path

        from simorgh.orchestration.scaffolds import _KEYLESS_SOURCES

        doc = (Path(__file__).resolve().parents[3] / "docs" / "sourcebook.md").read_text().lower()
        for _what, where in _KEYLESS_SOURCES:
            for host in (part.strip() for part in where.split(",")):
                if host.startswith("the ") and host.endswith(" tool"):
                    continue  # a tool name, not a URL
                bare = host.split(" ")[0].lower()
                self.assertIn(bare, doc, f"{bare!r} is offered in the prompt but absent from the sourcebook")

    def test_the_research_prompt_carries_it_and_the_patch_prompt_does_not(self):
        from simorgh.orchestration import profiles, scaffolds

        self.assertIn("open-meteo", scaffolds.render(profiles.RESEARCH, task="x"))
        self.assertNotIn("open-meteo", scaffolds.render(profiles.PATCH, task="x"))


class PuppeteerProbeTestCase(unittest.IsolatedAsyncioTestCase):
    """The probe used to answer "is puppeteer installed?" with "does a
    directory of that name exist?" -- so a failed or interrupted
    `npm i -g puppeteer`, which leaves the directory behind, reported the
    capability as present and `render_page` then failed at the point of
    use instead."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    async def _probe(self):
        from simorgh.execution import capabilities

        completed = types.SimpleNamespace(stdout=str(self.root), returncode=0)
        with unittest.mock.patch.object(capabilities.shutil, "which", return_value="/usr/bin/npm"), \
                unittest.mock.patch.object(capabilities.subprocess, "run", return_value=completed):
            return await capabilities._puppeteer()

    async def test_a_complete_install_is_found_and_its_version_reported(self):
        package = self.root / "puppeteer"
        package.mkdir()
        (package / "package.json").write_text('{"name": "puppeteer", "version": "25.8.0"}')
        ok, detail = await self._probe()
        self.assertTrue(ok)
        self.assertIn("25.8.0", detail)

    async def test_a_bare_directory_is_not_an_install(self):
        (self.root / "puppeteer").mkdir()
        ok, detail = await self._probe()
        self.assertFalse(ok)
        self.assertIn("incomplete install", detail)

    async def test_nothing_installed_says_how_to_install_it(self):
        ok, detail = await self._probe()
        self.assertFalse(ok)
        self.assertIn("npm i -g puppeteer", detail)

    async def test_an_unreadable_manifest_is_still_an_install(self):
        package = self.root / "puppeteer"
        package.mkdir()
        (package / "package.json").write_text("{not json")
        ok, detail = await self._probe()
        self.assertTrue(ok, "a corrupt manifest is not proof the package is absent")
        self.assertIn("version unreadable", detail)


class ConnectorProbeTestCase(unittest.IsolatedAsyncioTestCase):
    """`connector_probe`: every account-backed integration
    (contracts/connector.py) is listed by `capabilities` next to Node
    and Docker, with the same yes/NO and the same what-to-set detail."""

    async def test_a_ready_connector_is_a_passing_cheap_probe(self):
        from simorgh.contracts.connector import FakeConnector
        from simorgh.execution.capabilities import connector_probe

        probe = connector_probe(FakeConnector("caldav", detail="fastmail reachable"))
        self.assertEqual((probe.name, probe.cost), ("connector:caldav", "cheap"))
        results = await run_probes((probe,))
        self.assertTrue(results[0].ok)
        self.assertEqual(results[0].detail, "fastmail reachable")

    async def test_a_connector_that_cannot_run_names_what_is_missing(self):
        from simorgh.contracts.connector import FakeConnector
        from simorgh.execution.capabilities import connector_probe

        probe = connector_probe(FakeConnector(
            "imap", ok=False, detail="no credential", missing=("IMAP_PASSWORD", "imapclient")))
        results = await run_probes((probe,))
        self.assertFalse(results[0].ok)
        self.assertIn("IMAP_PASSWORD", results[0].detail)
        self.assertIn("imapclient", results[0].detail)

    async def test_a_cheap_connector_probe_never_degrades_health(self):
        from simorgh.contracts.connector import FakeConnector
        from simorgh.execution.capabilities import connector_probe

        results = await run_probes((connector_probe(FakeConnector("x", ok=False)),))
        self.assertEqual(degraded_detail(results), "")

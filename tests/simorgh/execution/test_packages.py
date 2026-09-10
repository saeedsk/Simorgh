"""`find_package` / `install_package` (execution/packages.py).

Offline by injection: the registry opener and the installer subprocess
are both passed in. One real smoke test hits PyPI and skips itself
without network.
"""

from __future__ import annotations

import json
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tempfile

from simorgh.execution.config import Config
from simorgh.execution import packages
from simorgh.execution.packages import (
    FindPackageTool, InstallPackageTool, npm_facts, parse_spec, pypi_facts,
)


class _Clock:
    def __init__(self, t=1_757_000_000.0):
        self.t = t

    def now(self):
        return self.t


def _ctx(task_id="t1"):
    from simorgh.contracts.protocols import ToolContext

    return ToolContext(action_id="a1", task_id=task_id, scope={}, constraints={},
                       data_dir=Path.cwd(), clock=_Clock(), logger=None, ledger=None)


class _Response:
    def __init__(self, body: str):
        self._body = body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=None):
        return self._body[:n] if n else self._body


def _pypi_payload(name="homeharvest", first="2023-10-02", homepage="https://github.com/x/y"):
    return json.dumps({
        "info": {"name": name, "summary": "Real estate scraping", "version": "0.8.18",
                 "license": "MIT", "home_page": homepage, "project_urls": {}},
        "releases": {
            "0.1.0": [{"upload_time_iso_8601": f"{first}T00:00:00Z"}],
            "0.8.18": [{"upload_time_iso_8601": "2026-08-30T00:00:00Z"}],
        },
    })


def _opener_for(mapping: dict, seen: list | None = None):
    def open_it(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if seen is not None:
            seen.append(url)
        for fragment, body in mapping.items():
            if fragment in url:
                return _Response(body)
        raise OSError("404")
    return open_it


class ParseSpecTestCase(unittest.TestCase):
    def test_a_plain_name_parses(self):
        self.assertEqual(parse_spec("homeharvest"), ("homeharvest", ""))

    def test_a_pin_is_kept(self):
        self.assertEqual(parse_spec("homeharvest==0.8.18"), ("homeharvest", "==0.8.18"))

    def test_an_npm_scope_is_allowed(self):
        self.assertEqual(parse_spec("@modelcontextprotocol/server-time")[0],
                         "@modelcontextprotocol/server-time")

    def test_a_url_is_refused(self):
        # `pip install <url>` runs code from somewhere nobody reviewed.
        self.assertIsNone(parse_spec("https://evil.example/x.tar.gz"))
        self.assertIsNone(parse_spec("git+https://github.com/x/y"))

    def test_a_local_path_is_refused(self):
        self.assertIsNone(parse_spec("./x"))
        self.assertIsNone(parse_spec("/tmp/x"))
        self.assertIsNone(parse_spec("file:///tmp/x"))

    def test_a_flag_is_refused(self):
        self.assertIsNone(parse_spec("--editor"))

    def test_an_unscoped_slash_is_refused(self):
        self.assertIsNone(parse_spec("evil/path"))

    def test_a_scoped_path_traversal_is_refused(self):
        # `@x/../evil-pkg` matches the "scope separator" shape but is a
        # relative filesystem path -- both pip and npm resolve it to a
        # real local directory (pip runs its setup.py at metadata time,
        # npm runs its postinstall script) instead of looking anything
        # up on a registry. Confirmed live against real pip and npm
        # 2026-09-09 by an observer.
        self.assertIsNone(parse_spec("@x/../evil-local-pkg"))
        self.assertIsNone(parse_spec("@scope/../../etc/passwd"))
        self.assertIsNone(parse_spec("@x/.."))
        self.assertIsNone(parse_spec("@../x"))
        self.assertIsNone(parse_spec("@a/b/c"))


class FactsTestCase(unittest.TestCase):
    def test_pypi_facts_take_the_earliest_upload_as_first_release(self):
        facts = pypi_facts(json.loads(_pypi_payload()))
        self.assertEqual(facts["first_release"], "2023-10-02")
        self.assertEqual(facts["latest_release"], "2026-08-30")
        self.assertEqual(facts["version"], "0.8.18")

    def test_npm_facts_read_the_latest_dist_tag(self):
        payload = {"name": "x", "description": "d", "dist-tags": {"latest": "2.0.0"},
                   "time": {"created": "2020-01-01T00:00:00Z", "2.0.0": "2026-01-01T00:00:00Z"},
                   "versions": {"2.0.0": {"license": "MIT", "homepage": "https://h"}}}
        facts = npm_facts(payload)
        self.assertEqual(facts["version"], "2.0.0")
        self.assertEqual(facts["first_release"], "2020-01-01")


class FindPackageTestCase(unittest.IsolatedAsyncioTestCase):
    def _tool(self, mapping, seen=None):
        return FindPackageTool(Config(repo_root=Path.cwd()), opener=_opener_for(mapping, seen))

    async def test_a_real_package_reports_its_facts(self):
        result = await self._tool({"pypi.org": _pypi_payload()}).run({"query": "homeharvest"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("homeharvest", result.output)
        self.assertIn("MIT", result.output)
        self.assertEqual(result.metadata["hits"][0]["first_release"], "2023-10-02")

    async def test_an_unknown_name_says_so_without_failing(self):
        result = await self._tool({}).run({"query": "nosuchpkg"}, ctx=_ctx())
        self.assertTrue(result.ok)
        self.assertIn("no package named", result.output)

    async def test_a_scoped_name_is_never_sent_to_pypi(self):
        seen: list = []
        await self._tool({"registry.npmjs.org": "{}"}, seen).run(
            {"query": "@modelcontextprotocol/server-time"}, ctx=_ctx())
        self.assertFalse(any("pypi.org" in url for url in seen))

    async def test_a_non_package_query_is_refused(self):
        result = await self._tool({}).run({"query": "https://evil/x"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("not a plain package name", result.error)


class InstallPackageTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.calls: list = []

    def _runner(self, returncode=0, stdout="Successfully installed homeharvest-0.8.18"):
        def run(cmd, **kwargs):
            self.calls.append(cmd)

            class _R:
                pass
            r = _R()
            r.returncode, r.stdout, r.stderr = returncode, stdout, ""
            return r
        return run

    def _tool(self, *, mapping=None, returncode=0, **config):
        settings = {"repo_root": self.root}
        settings.update(config)
        return InstallPackageTool(
            Config(**settings),
            opener=_opener_for(mapping if mapping is not None else {"pypi.org": _pypi_payload()}),
            runner=self._runner(returncode), clock=_Clock().now,
        )

    async def test_a_known_old_package_installs_and_is_recorded(self):
        result = await self._tool().run(
            {"manager": "pip", "spec": "homeharvest", "reason": "real listing data"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("installed homeharvest", result.output)
        self.assertIn("pip", self.calls[0])
        log = (self.root / "simorgh_packages.txt").read_text()
        self.assertIn("homeharvest", log)
        self.assertIn("task=t1", log)
        self.assertIn("real listing data", log)

    async def test_a_url_spec_is_refused_before_anything_runs(self):
        result = await self._tool().run(
            {"manager": "pip", "spec": "https://evil.example/x.tar.gz"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("plain package name", result.error)
        self.assertFalse(self.calls)

    async def test_an_unknown_manager_is_refused(self):
        result = await self._tool().run({"manager": "curl", "spec": "x"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertFalse(self.calls)

    async def test_a_brand_new_package_needs_allow_new(self):
        """A plausible name published days ago is the shape a typosquat
        takes. Refusable, overridable, and the reason is stated."""
        recent = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
        tool = self._tool(mapping={"pypi.org": _pypi_payload(first=recent)})
        result = await tool.run({"manager": "pip", "spec": "homeharvest"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("typosquat", result.error)
        self.assertFalse(self.calls)

        # The override needs a reason as well as the flag -- that is
        # what this test's own docstring means by "the reason is
        # stated", and until 2026-09-10 only the flag was enforced.
        allowed = await tool.run(
            {"manager": "pip", "spec": "homeharvest", "allow_new": True,
             "reason": "named in the vendor's own migration guide"}, ctx=_ctx())
        self.assertTrue(allowed.ok, allowed.error)

    async def test_a_package_with_no_homepage_needs_allow_new(self):
        tool = self._tool(mapping={"pypi.org": _pypi_payload(homepage="")})
        result = await tool.run({"manager": "pip", "spec": "homeharvest"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("homepage", result.error)

    async def test_a_lookup_that_cannot_run_is_a_refusal_not_a_pass(self):
        # "I could not check" must never read as "I checked and it was fine".
        tool = self._tool(mapping={})
        result = await tool.run({"manager": "pip", "spec": "homeharvest"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("could not find", result.error)

    async def test_an_unknown_first_release_date_is_a_refusal_not_a_pass(self):
        # A registry hit that has a homepage but no usable upload-time
        # data at all (files present with no upload_time_iso_8601 key)
        # must refuse exactly like a failed lookup -- "I don't know its
        # age" is not "I checked and it's old enough".
        payload = json.dumps({
            "info": {"name": "homeharvest", "summary": "x", "version": "0.0.1",
                      "license": "MIT", "home_page": "https://github.com/x/y", "project_urls": {}},
            "releases": {"0.0.1": [{"filename": "homeharvest-0.0.1.tar.gz"}]},
        })
        tool = self._tool(mapping={"pypi.org": payload})
        result = await tool.run({"manager": "pip", "spec": "homeharvest"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("could not determine", result.error)
        self.assertFalse(self.calls)

    async def test_an_unparseable_first_release_date_is_a_refusal_not_a_pass(self):
        payload = json.dumps({
            "info": {"name": "homeharvest", "summary": "x", "version": "0.0.1",
                      "license": "MIT", "home_page": "https://github.com/x/y", "project_urls": {}},
            "releases": {"0.0.1": [{"upload_time_iso_8601": "0000-00-00T00:00:00Z"}]},
        })
        tool = self._tool(mapping={"pypi.org": payload})
        result = await tool.run({"manager": "pip", "spec": "homeharvest"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("could not determine", result.error)
        self.assertFalse(self.calls)

    async def test_a_denylisted_name_is_refused(self):
        result = await self._tool().run({"manager": "pip", "spec": "pip"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("denylist", result.error)

    async def test_a_failing_install_reports_the_output(self):
        tool = self._tool(returncode=1)
        result = await tool.run({"manager": "pip", "spec": "homeharvest"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("exit 1", result.error)
        self.assertFalse((self.root / "simorgh_packages.txt").exists())

    async def test_the_daily_quota_refuses_past_the_cap(self):
        tool = self._tool(max_installs_per_day=2)
        for _ in range(2):
            self.assertTrue((await tool.run({"manager": "pip", "spec": "homeharvest"}, ctx=_ctx())).ok)
        blocked = await tool.run({"manager": "pip", "spec": "homeharvest"}, ctx=_ctx())
        self.assertFalse(blocked.ok)
        self.assertIn("already today", blocked.error)


class RealPyPiSmokeTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_real_lookup_of_a_package_we_actually_depend_on(self):
        import socket

        try:
            socket.gethostbyname("pypi.org")
        except socket.gaierror:
            self.skipTest("no network access in this environment")
        result = await FindPackageTool(Config(repo_root=Path.cwd())).run(
            {"query": "homeharvest", "manager": "pypi"}, ctx=_ctx())
        if not result.ok or not result.metadata["hits"]:
            self.skipTest(f"PyPI did not answer in this sandbox: {result.error or result.output}")
        self.assertEqual(result.metadata["hits"][0]["name"].lower(), "homeharvest")


class TheRegistryPageTooBigToReadTestCase(unittest.IsolatedAsyncioTestCase):
    """"I could not read the answer" is not "there is no such package".

    Live-caught 2026-09-10. A registry page grows with the package's
    release history, so the most popular packages have the biggest ones,
    and the 2 MB read cap did not refuse them -- it TRUNCATED them.
    `json.loads` raised on the cut, the lookup returned nothing, and
    `install_package matplotlib` answered "could not find 'matplotlib'
    on pip's registry to check it". matplotlib's page is 2,447,559
    bytes. The model's next move was `allow_new: true`: the typosquat
    guard talked out of the way by one of the most legitimate packages
    on the index, and that reflex learned for next time.
    """

    def _oversized_opener(self):
        body = b'{"info": {"home_page": "https://x", "summary": "s"}, "releases": {}}'
        body += b" " * (packages._PACKAGE_JSON_MAX_BYTES + 10 - len(body))

        class _Response:
            def read(self, size=None):
                return body[:size] if size else body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return lambda request, timeout: _Response()

    def test_the_cap_is_above_the_real_pages_that_broke_it(self):
        self.assertGreater(packages._PACKAGE_JSON_MAX_BYTES, 2_447_559)

    def test_an_unreadable_page_refuses_as_itself_not_as_a_missing_package(self):
        tool = packages.InstallPackageTool(Config())
        tool._finder._opener = self._oversized_opener()
        refusal = tool._vet("matplotlib", "pip")
        self.assertIn("larger than", refusal)
        self.assertIn("NOT a claim that the package is missing", refusal)

    def test_it_is_still_a_refusal_because_unchecked_stays_unchecked(self):
        """The guard must not be softened into a pass: nothing was
        verified, so nothing may be installed without saying why."""
        tool = packages.InstallPackageTool(Config())
        tool._finder._opener = self._oversized_opener()
        self.assertTrue(tool._vet("matplotlib", "pip").startswith("refused:"))

    async def test_find_package_does_not_report_it_as_absent(self):
        """`ok=True, "no package named 'matplotlib'"` is the "succeeds
        while saying nothing true" failure, in the tool whose whole job
        is answering whether a package exists."""
        tool = packages.FindPackageTool(Config())
        tool._opener = self._oversized_opener()
        result = await tool.run({"query": "matplotlib"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertNotIn("no package named", (result.output or "") + (result.error or ""))
        self.assertIn("larger than", result.error)


class TheOverrideNeedsAReasonTestCase(unittest.IsolatedAsyncioTestCase):
    """The module docstring has always said this override "needs
    `allow_new: true` AND a reason". Only the flag was enforced.

    So the refusal was talked past by re-asking with the flag and
    nothing else: an observer watched a nonexistent package be refused,
    then installed on the very next call with no `reason` key at all,
    and the single audit line read `reason=-` (2026-09-10). An override
    nobody has to justify is not an override, it is a delay.
    """

    def _tool(self):
        return packages.InstallPackageTool(Config(repo_root=Path(tempfile.mkdtemp())))

    async def _run(self, args: dict):
        tool = self._tool()
        with unittest.mock.patch.object(tool, "_install", return_value=None):
            return await tool.run(args, ctx=_ctx())

    async def test_the_override_without_a_reason_is_refused(self):
        result = await self._run({"manager": "pip", "spec": "zzz-not-real-9x", "allow_new": True})
        self.assertFalse(result.ok)
        self.assertIn("needs a reason", result.error)

    async def test_a_token_reason_does_not_count(self):
        result = await self._run({"manager": "pip", "spec": "zzz-not-real-9x",
                                  "allow_new": True, "reason": "ok"})
        self.assertFalse(result.ok)
        self.assertIn("needs a reason", result.error)

    async def test_a_real_reason_gets_through_the_check(self):
        """It still has to install; this only proves the guard let it
        past."""
        result = await self._run({"manager": "pip", "spec": "zzz-not-real-9x", "allow_new": True,
                                  "reason": "documented in the vendor's migration guide"})
        self.assertNotIn("needs a reason", result.error or "")

    async def test_without_the_override_the_typosquat_guard_still_runs(self):
        result = await self._run({"manager": "pip", "spec": "zzz-not-real-9x"})
        self.assertFalse(result.ok)
        self.assertIn("could not find", result.error)

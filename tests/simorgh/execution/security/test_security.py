"""Security posture (execution/security/): the findings store, the
local checks, and the five `sec_*` tools.

Every check here is local by construction -- the domain is advisory and
read-only, and step 1 touches no network at all. The two behaviours
pinned hardest are the ones that would make the whole thing worse than
useless: a finding that quotes the secret it is warning about, and an
accepted risk that never expires."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.security.api import Finding, redact, score, top_reasons
from simorgh.execution.security.findings import FindingStore
from simorgh.execution.security.selfcheck import (
    check_api_exposure,
    check_auto_approve,
    check_env_secrets,
    check_file_modes,
    check_ledger_size,
    check_listening_ports,
    check_secrets_in,
)
from simorgh.execution.security.tools import security_tools


def _ctx() -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                       data_dir=Path("."), clock=None, logger=None, ledger=None)


class FindingTestCase(unittest.TestCase):
    def test_a_fingerprint_is_stable_across_sightings(self):
        one = Finding("certs", "high", "ha.local", "Expires in 20 days", evidence="20 days")
        two = Finding("certs", "high", "ha.local", "Expires in 19 days", evidence="19 days")
        self.assertEqual(one.fingerprint, two.fingerprint,
                         "a certificate ticking down is not a different finding")

    def test_a_discriminator_separates_two_findings_on_one_asset(self):
        one = Finding("secret", "critical", "/w/a.md", "t", discriminator="a")
        two = Finding("secret", "critical", "/w/a.md", "t", discriminator="b")
        self.assertNotEqual(one.fingerprint, two.fingerprint)

    def test_a_finding_needs_a_category_and_an_asset(self):
        with self.assertRaises(ValueError):
            Finding("", "high", "asset", "title")
        with self.assertRaises(ValueError):
            Finding("cat", "high", "", "title")

    def test_an_unknown_severity_is_refused(self):
        with self.assertRaises(ValueError):
            Finding("cat", "apocalyptic", "asset", "title")

    def test_the_score_starts_at_100_and_is_subtracted_from(self):
        self.assertEqual(score([]), 100)
        self.assertEqual(score([Finding("c", "critical", "a", "t")]), 75)

    def test_the_score_never_goes_below_zero(self):
        self.assertEqual(score([Finding("c", "critical", f"a{n}", "t") for n in range(20)]), 0)

    def test_reasons_come_back_worst_first(self):
        findings = [Finding("a", "low", "x", "Small"), Finding("b", "critical", "y", "Huge")]
        self.assertTrue(top_reasons(findings)[0].startswith("critical"))

    def test_redaction_keeps_a_recognisable_prefix_and_nothing_usable(self):
        redacted = redact("sk-abcdefghijklmnop")
        self.assertTrue(redacted.startswith("sk-a"))
        self.assertNotIn("efghijklmnop", redacted)


class FindingStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.now = 1_000_000.0
        self.store = FindingStore(Path(self._tmp.name) / "f.db", clock=lambda: self.now)
        self.api = Finding("api_exposure", "critical", "sim:api", "API open")
        self.vault = Finding("file_permissions", "high", "/v/vault.key", "Loose mode")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_a_first_sighting_opens_a_finding(self):
        outcome = self.store.record([self.api])
        self.assertEqual(outcome["opened"], 1)
        self.assertEqual(self.store.counts()["open"], 1)

    def test_the_same_finding_again_is_not_a_second_finding(self):
        self.store.record([self.api])
        self.now += 86400
        outcome = self.store.record([self.api])
        self.assertEqual(outcome["opened"], 0)
        self.assertEqual(outcome["still_open"], 1)
        self.assertEqual(len(self.store.list()), 1)

    def test_a_finding_that_stops_being_reported_is_fixed_not_deleted(self):
        """The record of having had the problem is most of what makes
        the next occurrence meaningful."""
        self.store.record([self.api, self.vault])
        self.now += 86400
        outcome = self.store.record([self.api])
        self.assertEqual(outcome["fixed"], 1)
        self.assertEqual(self.store.counts()["fixed"], 1)
        self.assertEqual(len(self.store.list()), 2)

    def test_a_fixed_finding_that_returns_is_regressed(self):
        self.store.record([self.api])
        self.now += 86400
        self.store.record([])
        self.now += 86400
        outcome = self.store.record([self.api])
        self.assertEqual(outcome["regressed"], 1)
        self.assertEqual(self.store.get(self.api.fingerprint)["times_regressed"], 1)

    def test_a_partial_run_does_not_close_what_it_did_not_look_for(self):
        """A run of only the TLS checks must not mark every secrets
        finding fixed just because it did not look for any."""
        self.store.record([self.api, self.vault])
        self.now += 86400
        self.store.record([self.api], categories=("api_exposure",))
        self.assertEqual(self.store.counts().get("fixed"), None)
        self.assertEqual(self.store.counts()["open"], 2)

    def test_accepting_takes_it_out_of_the_score(self):
        self.store.record([self.api])
        self.assertEqual(score(self.store.open_findings()), 75)
        self.assertTrue(self.store.accept(self.api.fingerprint, "behind tailscale"))
        self.assertEqual(score(self.store.open_findings()), 100)

    def test_an_acceptance_expires_and_the_finding_counts_again(self):
        """An accepted risk with no end date is a permanent blind spot,
        which is the same as never having found it."""
        self.store.record([self.api])
        self.store.accept(self.api.fingerprint, "temporary", days=30)
        self.now += 31 * 86400
        self.assertEqual(score(self.store.open_findings()), 75)

    def test_a_sighting_after_an_acceptance_expires_reopens_it(self):
        self.store.record([self.api])
        self.store.accept(self.api.fingerprint, "temporary", days=30)
        self.now += 31 * 86400
        self.store.record([self.api])
        self.assertEqual(self.store.get(self.api.fingerprint)["status"], "open")

    def test_accepting_something_already_fixed_is_refused(self):
        self.store.record([self.api])
        self.now += 10
        self.store.record([])
        self.assertFalse(self.store.accept(self.api.fingerprint, "whatever"))

    def test_a_fingerprint_prefix_finds_the_finding(self):
        self.store.record([self.api])
        found = self.store.get(self.api.fingerprint[:6])
        self.assertEqual(found["fingerprint"], self.api.fingerprint)

    def test_findings_filter_by_severity_and_status(self):
        self.store.record([self.api, self.vault])
        self.assertEqual(len(self.store.list(severity="critical")), 1)
        self.assertEqual(len(self.store.list(status="open")), 2)


class ApiExposureTestCase(unittest.TestCase):
    def test_off_loopback_with_no_token_is_critical(self):
        findings = check_api_exposure(host="0.0.0.0", port=8765, has_token=False)
        self.assertEqual(findings[0].severity, "critical")
        self.assertIn("SIM_API_TOKEN", findings[0].remediation)

    def test_off_loopback_with_a_token_is_only_worth_noting(self):
        findings = check_api_exposure(host="0.0.0.0", port=8765, has_token=True)
        self.assertEqual(findings[0].severity, "low")

    def test_loopback_with_a_token_is_nothing_at_all(self):
        self.assertEqual(check_api_exposure(host="127.0.0.1", port=8765, has_token=True), [])

    def test_loopback_without_a_token_is_informational_not_a_problem(self):
        findings = check_api_exposure(host="127.0.0.1", port=8765, has_token=False)
        self.assertEqual(findings[0].severity, "info")


class AutoApproveTestCase(unittest.TestCase):
    def test_auto_approve_off_is_nothing_to_report(self):
        self.assertEqual(check_auto_approve(auto_approve=False, always_human=()), [])

    def test_auto_approve_with_no_exceptions_is_medium_not_critical(self):
        """It is a choice a person is entitled to make and this creator
        has made on purpose. Reporting it as an emergency would teach
        them to ignore the report."""
        findings = check_auto_approve(auto_approve=True, always_human=())
        self.assertEqual(findings[0].severity, "medium")

    def test_an_always_human_list_lowers_it_further(self):
        findings = check_auto_approve(auto_approve=True, always_human=("notify",))
        self.assertEqual(findings[0].severity, "low")

    def test_an_env_override_is_named_so_a_person_knows_where_to_look(self):
        findings = check_auto_approve(auto_approve=True, always_human=(),
                                       env_override="SIMORGH_GUARDIAN_AUTO_APPROVE")
        self.assertIn("SIMORGH_GUARDIAN_AUTO_APPROVE", findings[0].evidence)


class FileModeTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_world_readable_key_is_high(self):
        key = self.root / "vault.key"
        key.write_text("x")
        key.chmod(0o644)
        findings = check_file_modes([key])
        self.assertEqual(findings[0].severity, "high")
        self.assertIn("chmod 600", findings[0].remediation)

    def test_a_tight_mode_is_nothing_to_report(self):
        key = self.root / "vault.key"
        key.write_text("x")
        key.chmod(0o600)
        self.assertEqual(check_file_modes([key]), [])

    def test_a_file_that_is_not_there_is_not_a_finding(self):
        self.assertEqual(check_file_modes([self.root / "absent"]), [])


class SecretScanTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_an_api_key_written_into_a_scratch_file_is_critical(self):
        self._write("notes.md", "reminder: the key is sk-abcdefghijklmnopqrstuvwxyz01")
        findings = check_secrets_in([self.root])
        self.assertEqual(findings[0].severity, "critical")

    def test_the_finding_never_contains_the_secret(self):
        """This string is written to a database and read back into a
        model's context. A finding that quoted the key would put it in
        two more places."""
        secret = "sk-abcdefghijklmnopqrstuvwxyz01"
        self._write("notes.md", f"the key is {secret}")
        findings = check_secrets_in([self.root])
        blob = " ".join([findings[0].title, findings[0].evidence, findings[0].remediation])
        self.assertNotIn(secret, blob)
        self.assertNotIn("efghijklmnopqrstuvwxyz01", blob)

    def test_the_evidence_says_which_line(self):
        self._write("notes.md", "line one\nline two\nAKIAIOSFODNN7EXAMPLE\n")
        self.assertIn("line 3", check_secrets_in([self.root])[0].evidence)

    def test_several_shapes_are_recognised(self):
        for name, text in (("a.md", "ghp_abcdefghijklmnopqrstuvwxyz0123456789"),
                           ("b.md", "xoxb-1234567890-abcdefghij"),
                           ("c.md", "AIza" + "b" * 35),
                           ("d.md", "-----BEGIN RSA PRIVATE KEY-----"),
                           ("e.md", 'password = "hunter2hunter2"')):
            with self.subTest(name=name):
                self._write(name, text)
        findings = check_secrets_in([self.root])
        self.assertGreaterEqual(len(findings), 5)

    def test_ordinary_prose_is_not_flagged(self):
        """A scanner that flags every long string trains people to
        ignore it, and an ignored security report is worse than none."""
        self._write("notes.md", "The meeting is at three and the agenda is attached. "
                                "We discussed the password policy at length.")
        self.assertEqual(check_secrets_in([self.root]), [])

    def test_a_credential_looking_filename_is_reported_without_being_read(self):
        self._write(".env", "PASSWORD=hunter2")
        findings = check_secrets_in([self.root])
        self.assertTrue(findings)
        self.assertIn("contents were not read", findings[0].evidence)
        self.assertNotIn("hunter2", findings[0].evidence)

    def test_a_git_directory_is_skipped(self):
        self._write(".git/config", "AKIAIOSFODNN7EXAMPLE")
        self.assertEqual(check_secrets_in([self.root]), [])

    def test_a_missing_directory_is_not_an_error(self):
        self.assertEqual(check_secrets_in([self.root / "absent"]), [])


class LedgerAndPortsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_small_ledger_is_nothing_to_report(self):
        (self.root / "a.jsonl").write_text("x")
        self.assertEqual(check_ledger_size(self.root), [])

    def test_a_ledger_of_many_files_is_reported(self):
        for n in range(12):
            (self.root / f"{n}.jsonl").write_text("x")
        findings = check_ledger_size(self.root, file_warn=10)
        self.assertEqual(findings[0].severity, "medium")
        self.assertIn("file(s)", findings[0].title)

    def test_a_missing_ledger_is_not_a_finding(self):
        self.assertEqual(check_ledger_size(self.root / "absent"), [])

    def test_a_loopback_listener_is_not_reported(self):
        lines = ["python 123 me 5u IPv4 TCP 127.0.0.1:8765 (LISTEN)"]
        self.assertEqual(check_listening_ports(runner=lambda: lines), [])

    def test_a_listener_on_every_interface_is_reported(self):
        lines = ["python 123 me 5u IPv4 TCP *:8765 (LISTEN)"]
        findings = check_listening_ports(runner=lambda: lines)
        self.assertEqual(len(findings), 1)
        self.assertIn("8765", findings[0].asset)

    def test_no_lsof_reports_nothing_rather_than_a_clean_bill_of_health(self):
        self.assertEqual(check_listening_ports(runner=lambda: None), [])


class EnvSecretTestCase(unittest.TestCase):
    def test_credentials_in_the_environment_are_noted_once(self):
        findings = check_env_secrets({"OPENAI_API_KEY": "x", "SLACK_WEBHOOK_URL": "y", "PATH": "/"})
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "info")
        self.assertIn("OPENAI_API_KEY", findings[0].evidence)

    def test_the_values_are_never_included(self):
        findings = check_env_secrets({"OPENAI_API_KEY": "sk-thevalue"})
        self.assertNotIn("sk-thevalue", findings[0].evidence)

    def test_an_empty_variable_does_not_count(self):
        self.assertEqual(check_env_secrets({"OPENAI_API_KEY": "  "}), [])

    def test_nothing_set_is_nothing_to_report(self):
        self.assertEqual(check_env_secrets({"PATH": "/usr/bin"}), [])


class _ToolCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "workspace").mkdir()
        self.now = 1_000_000.0

    def tearDown(self):
        self._tmp.cleanup()

    def _tools(self, *, toml: str = "", env=None, lsof=None, **overrides) -> dict:
        if toml:
            (self.root / "simorgh.toml").write_text(toml, encoding="utf-8")
        config = Config(repo_root=self.root,
                        security_findings_path=str(self.root / "findings.db"),
                        security_config_path=str(self.root / "simorgh.toml") if toml else "",
                        **overrides)
        return {tool.name: tool for tool in security_tools(
            config, env=env if env is not None else {}, clock=lambda: self.now,
            lsof_runner=lsof or (lambda: None))}


class SecSelfTestCase(_ToolCase):
    EXPOSED = '[interface]\nhttp_host = "0.0.0.0"\nhttp_port = 8765\n'

    async def test_it_finds_an_exposed_api(self):
        result = await self._tools(toml=self.EXPOSED)["sec_self"].run({}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("answers the whole network", result.output)
        self.assertLess(result.metadata["score"], 80)

    async def test_a_token_in_the_environment_clears_it(self):
        tools = self._tools(toml=self.EXPOSED, env={"SIM_API_TOKEN": "t"})
        result = await tools["sec_self"].run({}, ctx=_ctx())
        self.assertNotIn("answers the whole network", result.output)

    async def test_a_token_from_the_scoped_secret_store_also_counts(self):
        class _Secrets:
            def get(self, name):
                return "tok" if name == "SIM_API_TOKEN" else None

        config = Config(repo_root=self.root,
                        security_findings_path=str(self.root / "findings.db"),
                        security_config_path=str(self.root / "simorgh.toml"))
        (self.root / "simorgh.toml").write_text(self.EXPOSED, encoding="utf-8")
        tools = {t.name: t for t in security_tools(config, secrets=_Secrets(), env={},
                                                    clock=lambda: self.now,
                                                    lsof_runner=lambda: None)}
        result = await tools["sec_self"].run({}, ctx=_ctx())
        self.assertNotIn("answers the whole network", result.output)

    async def test_it_reads_auto_approve_from_the_config_file(self):
        toml = '[guardian]\nauto_approve = true\n'
        result = await self._tools(toml=toml)["sec_self"].run({}, ctx=_ctx())
        self.assertIn("without asking", result.output)

    async def test_the_env_override_wins_over_the_file(self):
        toml = '[guardian]\nauto_approve = false\n'
        tools = self._tools(toml=toml, env={"SIMORGH_GUARDIAN_AUTO_APPROVE": "1"})
        result = await tools["sec_self"].run({}, ctx=_ctx())
        self.assertIn("SIMORGH_GUARDIAN_AUTO_APPROVE", result.output)

    async def test_it_finds_a_secret_written_into_the_workspace(self):
        (self.root / "workspace" / "scratch.md").write_text(
            "AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8")
        result = await self._tools()["sec_self"].run({}, ctx=_ctx())
        self.assertIn("AWS access key", result.output)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", result.output)

    async def test_scanning_for_secrets_can_be_switched_off(self):
        (self.root / "workspace" / "scratch.md").write_text(
            "AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8")
        result = await self._tools()["sec_self"].run({"scan_secrets": False}, ctx=_ctx())
        self.assertNotIn("AWS access key", result.output)

    async def test_a_clean_system_scores_full_marks(self):
        """Loopback and no token is a note, not a problem: an `info`
        finding weighs nothing, so the score stays at 100 while the
        fact is still recorded."""
        result = await self._tools()["sec_self"].run({}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.metadata["score"], 100)
        self.assertNotIn("[critical]", result.output)
        self.assertNotIn("[high]", result.output)

    async def test_running_twice_does_not_double_the_findings(self):
        tools = self._tools(toml=self.EXPOSED)
        first = await tools["sec_self"].run({}, ctx=_ctx())
        self.now += 3600
        second = await tools["sec_self"].run({}, ctx=_ctx())
        self.assertEqual(first.metadata["score"], second.metadata["score"])
        self.assertEqual(second.metadata["opened"], 0)

    async def test_fixing_the_exposure_drops_its_severity_rather_than_opening_a_new_finding(self):
        """"the API exposure situation" is one finding whose severity
        changes, not a critical one that vanishes and a low one that
        appears -- so the history of it stays in one place."""
        tools_exposed = self._tools(toml=self.EXPOSED)
        before = await tools_exposed["sec_self"].run({}, ctx=_ctx())
        self.assertLess(before.metadata["score"], 80)

        self.now += 3600
        tools_fixed = self._tools(toml=self.EXPOSED, env={"SIM_API_TOKEN": "t"})
        after = await tools_fixed["sec_self"].run({}, ctx=_ctx())
        self.assertGreater(after.metadata["score"], before.metadata["score"])
        self.assertIn("gated by a token", after.output)

        exposure_before = [r for r in before.metadata["rows"] if r["category"] == "api_exposure"]
        exposure_after = [r for r in after.metadata["rows"] if r["category"] == "api_exposure"]
        self.assertEqual(exposure_before[0]["fingerprint"], exposure_after[0]["fingerprint"],
                         "same problem, same identity -- so its history stays in one place")
        self.assertEqual(exposure_before[0]["severity"], "critical")
        self.assertEqual(exposure_after[0]["severity"], "low")

    async def test_a_finding_that_stops_being_reported_is_marked_fixed(self):
        (self.root / "workspace" / "scratch.md").write_text(
            "AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8")
        tools = self._tools()
        await tools["sec_self"].run({}, ctx=_ctx())
        (self.root / "workspace" / "scratch.md").unlink()
        self.now += 3600
        result = await tools["sec_self"].run({}, ctx=_ctx())
        self.assertGreaterEqual(result.metadata["fixed"], 1)

    async def test_it_reports_rows_so_the_results_can_be_aggregated(self):
        result = await self._tools(toml=self.EXPOSED)["sec_self"].run({}, ctx=_ctx())
        self.assertTrue(result.metadata["rows"])
        self.assertIn("fingerprint", result.metadata["rows"][0])


class SecPostureTestCase(_ToolCase):
    async def test_before_any_check_it_says_to_run_one(self):
        result = await self._tools()["sec_posture"].run({}, ctx=_ctx())
        self.assertIn("SEC_SELF", result.output)

    async def test_after_a_check_it_reports_the_score_and_the_reasons(self):
        tools = self._tools(toml='[interface]\nhttp_host = "0.0.0.0"\n')
        await tools["sec_self"].run({}, ctx=_ctx())
        result = await tools["sec_posture"].run({}, ctx=_ctx())
        self.assertIn("posture", result.output)
        self.assertIn("worst first", result.output)
        self.assertLess(result.metadata["score"], 100)


class SecFindingsAndShowTestCase(_ToolCase):
    async def asyncSetUp(self):
        self.tools = self._tools(toml='[interface]\nhttp_host = "0.0.0.0"\n')
        await self.tools["sec_self"].run({}, ctx=_ctx())

    async def test_findings_are_listed_with_ids(self):
        result = await self.tools["sec_findings"].run({}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("SEC_SHOW", result.output)
        self.assertTrue(result.metadata["rows"])

    async def test_findings_filter_by_severity(self):
        result = await self.tools["sec_findings"].run({"severity": "critical"}, ctx=_ctx())
        for row in result.metadata["rows"]:
            self.assertEqual(row["severity"], "critical")

    async def test_show_gives_the_evidence_and_the_remediation(self):
        listed = await self.tools["sec_findings"].run({"severity": "critical"}, ctx=_ctx())
        fingerprint = listed.metadata["rows"][0]["fingerprint"]
        result = await self.tools["sec_show"].run({"finding": fingerprint}, ctx=_ctx())
        self.assertIn("evidence", result.output)
        self.assertIn("what to do", result.output)

    async def test_a_prefix_of_the_id_is_enough(self):
        listed = await self.tools["sec_findings"].run({"severity": "critical"}, ctx=_ctx())
        fingerprint = listed.metadata["rows"][0]["fingerprint"]
        result = await self.tools["sec_show"].run({"finding": fingerprint[:6]}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)

    async def test_an_unknown_id_says_where_to_find_a_real_one(self):
        result = await self.tools["sec_show"].run({"finding": "deadbeef"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("SEC_FINDINGS", result.error)


class SecAcceptTestCase(_ToolCase):
    async def asyncSetUp(self):
        self.tools = self._tools(toml='[interface]\nhttp_host = "0.0.0.0"\n')
        await self.tools["sec_self"].run({}, ctx=_ctx())
        listed = await self.tools["sec_findings"].run({"severity": "critical"}, ctx=_ctx())
        self.fingerprint = listed.metadata["rows"][0]["fingerprint"]

    async def test_accepting_needs_a_reason(self):
        """An acceptance with no reason is indistinguishable from
        forgetting about it."""
        result = await self.tools["sec_accept"].run(
            {"finding": self.fingerprint, "reason": "  "}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("reason", result.error)

    async def test_accepting_raises_the_score(self):
        before = (await self.tools["sec_posture"].run({}, ctx=_ctx())).metadata["score"]
        await self.tools["sec_accept"].run(
            {"finding": self.fingerprint, "reason": "only reachable over Tailscale"}, ctx=_ctx())
        after = (await self.tools["sec_posture"].run({}, ctx=_ctx())).metadata["score"]
        self.assertGreater(after, before)

    async def test_the_acceptance_says_that_it_will_come_back(self):
        result = await self.tools["sec_accept"].run(
            {"finding": self.fingerprint, "reason": "known"}, ctx=_ctx())
        self.assertIn("blind spot", result.output)

    async def test_an_expired_acceptance_counts_against_the_score_again(self):
        await self.tools["sec_accept"].run(
            {"finding": self.fingerprint, "reason": "for now", "days": 30}, ctx=_ctx())
        self.now += 31 * 86400
        result = await self.tools["sec_posture"].run({}, ctx=_ctx())
        self.assertLess(result.metadata["score"], 100)

    async def test_an_unknown_finding_is_refused(self):
        result = await self.tools["sec_accept"].run(
            {"finding": "deadbeef", "reason": "x"}, ctx=_ctx())
        self.assertFalse(result.ok)


class DeduplicationTestCase(_ToolCase):
    """`lsof` prints one row per socket, so a process listening on both
    IPv4 and IPv6 appears twice for the same port. The store dedupes on
    write, but a report that says the same thing twice reads as a broken
    report."""

    DOUBLE = [
        "node 123 me 5u IPv4 TCP *:3000 (LISTEN)",
        "node 123 me 6u IPv6 TCP *:3000 (LISTEN)",
    ]

    def test_the_check_itself_returns_one_finding_per_port(self):
        self.assertEqual(len(check_listening_ports(runner=lambda: self.DOUBLE)), 1)

    async def test_the_rendered_report_does_not_repeat_itself(self):
        result = await self._tools(lsof=lambda: self.DOUBLE)["sec_self"].run({}, ctx=_ctx())
        self.assertEqual(result.output.count("node is listening on *:3000"), 1)

    async def test_two_different_ports_are_two_findings(self):
        lines = ["node 1 me 5u IPv4 TCP *:3000 (LISTEN)", "node 1 me 6u IPv4 TCP *:3001 (LISTEN)"]
        result = await self._tools(lsof=lambda: lines)["sec_self"].run({}, ctx=_ctx())
        ports = [r for r in result.metadata["rows"] if r["category"] == "listening_port"]
        self.assertEqual(len(ports), 2)

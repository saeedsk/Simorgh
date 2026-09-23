"""The capability denylist judges code that will run AS SIM.

Live, 2026-09-22: SWE-bench `django__django-10973` is the issue "use
`subprocess.run` and PGPASSWORD for the client in the postgres backend".
The fix IS `subprocess.run`, so every attempt to write it into Django's
own `client.py` was denied "spawns its own subprocess instead of using
the sandbox (Directive 1)" -- three times, in three shapes. Sim did the
right thing with that: it refused to rephrase its way past a denial,
blocked the case and asked for a human.

But the denial was wrong in substance. That file is somebody else's
program, in a materialised checkout, which never runs in Sim's process:
it runs in that case's own container, behind Guardian's gate on
`run_tests` and `run_shell` like any other execution. The same denial
would land on any repository of the creator's that legitimately shells
out.

The signal is the manifest `execution/checkout.py` writes when it
materialises a checkout -- a fact about the tree, not a path spelling
anyone can imitate. Simorgh's own repo has no manifest.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.guardian import rules as rules_mod
from simorgh.guardian.rules import DenylistRule

from .test_rules import _ctx, _evaluate, _proposal

FIX = """import subprocess

def runshell_db(conn_params):
    env = os.environ.copy()
    env['PGPASSWORD'] = str(conn_params.get('password'))
    subprocess.run(args, check=True, env=env)
"""


class SomebodyElsesCodeIsNotSimsOwn(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        case = self.root / "workspace" / "swebench" / "django__django-10973"
        (case / "django" / "db").mkdir(parents=True)
        (case / ".simorgh-checkout.json").write_text(json.dumps({
            "repo": "django/django", "diff_base": "abc123", "case_id": "django__django-10973",
        }))
        self.their_file = "workspace/swebench/django__django-10973/django/db/client.py"
        (self.root / self.their_file).write_text("# the original\n")
        (self.root / "simorgh").mkdir()
        (self.root / "simorgh" / "mine.py").write_text("# mine\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _patch(self, subject: str):
        return _proposal(tool="apply_source_patch", args={"subject": subject, "code": FIX})

    async def test_their_file_may_contain_subprocess_run(self):
        with mock.patch.object(rules_mod, "_REPO_ROOT", self.root):
            decision = await _evaluate(DenylistRule(), self._patch(self.their_file), _ctx())
        self.assertEqual(decision.kind, "abstain", decision.reasons)

    async def test_sims_own_source_is_still_judged(self):
        with mock.patch.object(rules_mod, "_REPO_ROOT", self.root):
            decision = await _evaluate(DenylistRule(), self._patch("simorgh/mine.py"), _ctx())
        self.assertEqual(decision.kind, "deny")
        self.assertTrue(any("subprocess" in r for r in decision.reasons), decision.reasons)

    async def test_a_path_that_only_looks_like_a_checkout_is_still_judged(self):
        """The manifest is a fact. A directory named like a checkout,
        without one, is Sim's own tree."""
        fake = "workspace/swebench/not-really/mine.py"
        (self.root / "workspace" / "swebench" / "not-really").mkdir(parents=True)
        (self.root / fake).write_text("# mine\n")
        with mock.patch.object(rules_mod, "_REPO_ROOT", self.root):
            decision = await _evaluate(DenylistRule(), self._patch(fake), _ctx())
        self.assertEqual(decision.kind, "deny")

    async def test_a_manifest_inside_sims_own_source_exempts_nothing(self):
        """The escalation this rule must not allow.

        Sim can write files. A manifest is JSON with no denylisted
        pattern in it, and `simorgh/guardian` is protected while
        `simorgh/memory` is not -- so a first version keyed only on the
        manifest would have let Sim write
        `simorgh/memory/.simorgh-checkout.json` and thereby exempt its
        own memory package from the rule that stops it giving itself a
        subprocess. A checkout lives under `workspace/`; a manifest
        anywhere else is a file Sim wrote.
        """
        planted = self.root / "simorgh" / "memory"
        planted.mkdir(parents=True)
        (planted / ".simorgh-checkout.json").write_text(json.dumps({"repo": "mine", "diff_base": "x"}))
        (planted / "store.py").write_text("# mine\n")
        with mock.patch.object(rules_mod, "_REPO_ROOT", self.root):
            decision = await _evaluate(DenylistRule(), self._patch("simorgh/memory/store.py"), _ctx())
        self.assertEqual(decision.kind, "deny", "Sim's own source is judged, manifest or no manifest")

    async def test_code_with_no_file_behind_it_is_still_judged(self):
        """`run_shell` / `run_python_sandboxed` name no subject: that
        code runs here, now, as Sim."""
        with mock.patch.object(rules_mod, "_REPO_ROOT", self.root):
            decision = await _evaluate(DenylistRule(),
                                       _proposal(tool="run_script", args={"code": FIX}), _ctx())
        self.assertEqual(decision.kind, "deny")


if __name__ == "__main__":
    unittest.main()

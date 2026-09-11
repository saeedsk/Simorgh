"""The manifest is derived from the image's own eval script, minus the
parts the system under test must never see."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.benchmark import swebench
from simorgh.contracts.checkout import TARGET_DJANGO_LABEL, TARGET_PATH, ContainerCheckout

ASTROPY = """#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git -c core.fileMode=false diff 26d147868f8a891a6009a25cd6a8576d2e1bd747
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .[test] --verbose
git checkout 26d147868f8a891a6009a25cd6a8576d2e1bd747 astropy/utils/tests/test_misc.py
git apply -v - <<'EOF_114329324912'
diff --git a/astropy/utils/tests/test_misc.py b/astropy/utils/tests/test_misc.py
+        HIDDEN TEST LINE
EOF_114329324912
: '>>>>> Start Test Output'
pytest -rA -vv -o console_output_style=classic --tb=no astropy/utils/tests/test_misc.py
: '>>>>> End Test Output'
git checkout 26d147868f8a891a6009a25cd6a8576d2e1bd747 astropy/utils/tests/test_misc.py
"""

DJANGO = """#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
export LANG=en_US.UTF-8
git checkout e7fd69d051eaa67cb17f172a39b57253e9cb831a tests/test_utils/tests.py
git apply -v - <<'EOF_1'
+        HIDDEN
EOF_1
: '>>>>> Start Test Output'
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 test_utils.tests
: '>>>>> End Test Output'
"""


class ManifestFromEvalScriptTestCase(unittest.TestCase):
    def test_pytest_shape(self):
        m = swebench.checkout_manifest({"image": "img", "base_commit": "26d1478", "eval_script": ASTROPY})
        self.assertEqual(m.image, "img")
        self.assertEqual(m.workdir, "/testbed")
        self.assertEqual(m.base_commit, "26d1478")
        self.assertEqual(m.target_style, TARGET_PATH)
        self.assertEqual(m.test_command, "pytest -rA -vv -o console_output_style=classic --tb=no")
        self.assertIn("conda activate testbed", m.setup)
        self.assertIn("python -m pip install -e .[test] --verbose", m.setup)

    def test_the_hidden_test_patch_is_not_in_the_setup(self):
        m = swebench.checkout_manifest({"image": "img", "eval_script": ASTROPY})
        self.assertNotIn("HIDDEN", m.setup)
        self.assertNotIn("git apply", m.setup)
        self.assertNotIn("git checkout 26d1478", m.setup)

    def test_the_chatter_is_not_in_the_setup(self):
        m = swebench.checkout_manifest({"image": "img", "eval_script": ASTROPY})
        for noise in ("git show", "git status", "core.fileMode"):
            self.assertNotIn(noise, m.setup)
        self.assertNotIn("#!", m.setup)

    def test_django_shape(self):
        m = swebench.checkout_manifest({"image": "img", "eval_script": DJANGO})
        self.assertEqual(m.target_style, TARGET_DJANGO_LABEL)
        self.assertEqual(m.test_command, "./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1")
        self.assertIn("export LANG=en_US.UTF-8", m.setup)
        self.assertNotIn("HIDDEN", m.setup)

    def test_no_script_is_an_empty_but_valid_manifest(self):
        m = swebench.checkout_manifest({"image": "img"})
        self.assertEqual(m.test_command, "")
        self.assertEqual(m.setup.strip(), "")


class MaterializeWritesItTestCase(unittest.TestCase):
    def test_the_manifest_lands_at_the_checkout_root(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "case"

            def fake_run(args, *, timeout):
                if args[1] == "create":
                    return 0, "0123456789abcdef\n"
                if args[1] == "cp":
                    dest.mkdir(parents=True, exist_ok=True)
                    return 0, ""
                return 0, ""

            with mock.patch.object(swebench, "docker_path", return_value="/usr/bin/docker"), \
                 mock.patch.object(swebench, "_run", side_effect=fake_run):
                problem = swebench.materialize(
                    {"image": "img", "base_commit": "abc", "eval_script": ASTROPY}, dest)
            self.assertEqual(problem, "")
            manifest = ContainerCheckout.read(dest)
            self.assertIsNotNone(manifest)
            self.assertEqual(manifest.image, "img")
            self.assertEqual(manifest.base_commit, "abc")


if __name__ == "__main__":
    unittest.main()

"""The manifest that tells `run_tests` where a checkout's tests can run."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.checkout import (
    MANIFEST_NAME,
    TARGET_DJANGO_LABEL,
    ContainerCheckout,
    django_label,
    find_enclosing,
)


def _manifest(**overrides) -> ContainerCheckout:
    base = dict(image="img:latest", platform="linux/amd64", workdir="/testbed", base_commit="abc123",
                setup="source /opt/conda/bin/activate\nconda activate testbed\n",
                test_command="pytest -rA --tb=no")
    base.update(overrides)
    return ContainerCheckout(**base)


class ManifestTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_round_trip(self):
        m = _manifest(target_style=TARGET_DJANGO_LABEL)
        m.write(self.root)
        self.assertEqual(ContainerCheckout.read(self.root), m)

    def test_no_manifest_is_none(self):
        self.assertIsNone(ContainerCheckout.read(self.root))

    def test_a_broken_manifest_is_none_not_a_crash(self):
        (self.root / MANIFEST_NAME).write_text("{not json")
        self.assertIsNone(ContainerCheckout.read(self.root))
        (self.root / MANIFEST_NAME).write_text('{"image": "x"}')
        self.assertIsNone(ContainerCheckout.read(self.root), "a manifest missing its test command is no manifest")


class FindEnclosingTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()  # macOS: /var -> /private/var
        self.checkout = self.root / "workspace" / "swebench" / "case-1"
        (self.checkout / "pkg" / "tests").mkdir(parents=True)
        _manifest().write(self.checkout)

    def test_a_path_inside_the_checkout_is_found_with_its_inner_path(self):
        found = find_enclosing(self.root, "workspace/swebench/case-1/pkg/tests/test_x.py")
        self.assertEqual(found, (self.checkout, "pkg/tests/test_x.py"))

    def test_the_checkout_root_itself_is_found(self):
        self.assertEqual(find_enclosing(self.root, "workspace/swebench/case-1"), (self.checkout, "."))

    def test_a_path_outside_any_checkout_is_none(self):
        self.assertIsNone(find_enclosing(self.root, "simorgh/kernel/service.py"))
        self.assertIsNone(find_enclosing(self.root, "workspace/notes.md"))

    def test_the_repository_root_is_never_a_checkout(self):
        _manifest().write(self.root)  # somebody drops one at the top
        self.assertIsNone(find_enclosing(self.root, "tests/test_y.py"))

    def test_a_path_escaping_the_root_is_none(self):
        self.assertIsNone(find_enclosing(self.root, "../elsewhere/x.py"))


class DjangoLabelTestCase(unittest.TestCase):
    def test_a_test_path_becomes_a_label(self):
        self.assertEqual(django_label("tests/test_utils/tests.py"), "test_utils.tests")
        self.assertEqual(django_label("tests/model_fields"), "model_fields")

    def test_a_label_is_left_alone(self):
        self.assertEqual(django_label("test_utils.tests"), "test_utils.tests")


if __name__ == "__main__":
    unittest.main()

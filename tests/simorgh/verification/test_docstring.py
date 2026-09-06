"""`docstring_regression_reason` -- ported verbatim from
`src/orchestrator/self_patch.py` (see checks/docstring.py)."""

import unittest

from simorgh.verification.checks.docstring import docstring_regression_reason
from simorgh.verification.config import VerificationConfig

_LONG_DOC = '"""' + ("This module explains its own rationale in detail. " * 3) + '"""\n'
_ORIGINAL = _LONG_DOC + "def f():\n    return 1\n"


class TestDocstringRegression(unittest.TestCase):
    def setUp(self):
        self.config = VerificationConfig()

    def test_docstring_dropped_entirely_is_flagged(self):
        new_content = "def f():\n    return 1\n"
        reason = docstring_regression_reason(_ORIGINAL, new_content, self.config)
        self.assertIsNotNone(reason)
        self.assertIn("docstring", reason)

    def test_docstring_drastically_shortened_is_flagged(self):
        new_content = '"""short."""\ndef f():\n    return 1\n'
        reason = docstring_regression_reason(_ORIGINAL, new_content, self.config)
        self.assertIsNotNone(reason)

    def test_docstring_preserved_verbatim_is_not_flagged(self):
        self.assertIsNone(docstring_regression_reason(_ORIGINAL, _ORIGINAL, self.config))

    def test_docstring_genuinely_rewritten_same_length_is_not_flagged(self):
        rewritten = '"""' + ("A totally different explanation of the same rationale. " * 3) + '"""\ndef f():\n    return 1\n'
        self.assertIsNone(docstring_regression_reason(_ORIGINAL, rewritten, self.config))

    def test_no_original_docstring_to_protect(self):
        original = "def f():\n    return 1\n"
        new_content = "def f():\n    return 2\n"
        self.assertIsNone(docstring_regression_reason(original, new_content, self.config))

    def test_trivial_original_docstring_below_threshold_not_protected(self):
        original = '"""hi."""\ndef f():\n    return 1\n'
        new_content = "def f():\n    return 1\n"
        self.assertIsNone(docstring_regression_reason(original, new_content, self.config))

    def test_unparseable_original_returns_none(self):
        self.assertIsNone(docstring_regression_reason("def f(:\n", "def f():\n    return 1\n", self.config))

    def test_unparseable_candidate_returns_none(self):
        self.assertIsNone(docstring_regression_reason(_ORIGINAL, "def f(:\n", self.config))


if __name__ == "__main__":
    unittest.main()

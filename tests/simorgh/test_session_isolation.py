"""The test session never reaches a paid model (conftest.py)."""

import os
import unittest


class ModelIsolationTestCase(unittest.TestCase):
    def test_no_model_key_leaks_into_the_session(self):
        for name in ("TOGETHER_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            self.assertNotIn(name, os.environ, name)

    def test_booted_services_answer_from_the_floor(self):
        self.assertEqual(os.environ.get("SIMORGH_COGNITION_PROVIDER_ORDER"), "floor")

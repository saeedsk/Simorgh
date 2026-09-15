"""A provider entry that is not a table is reported, not silently skipped.

Live 2026-09-15: `ollama = "{'model': 'qwen3:4b-instruct'}"` (a stringified
dict) left the Ollama fallback off with nothing said."""

import unittest

from simorgh.cognition.config import Config


class ConfigProblems(unittest.TestCase):
    def test_a_stringified_provider_is_reported(self):
        cfg = Config.from_mapping({"providers": {"ollama": "{'model': 'qwen3:4b-instruct'}"}})
        self.assertEqual(len(cfg.problems), 1, cfg.problems)
        self.assertIn("[cognition.providers.ollama]", cfg.problems[0])
        self.assertNotIn("ollama", cfg.providers)

    def test_a_real_table_parses_with_no_problems(self):
        cfg = Config.from_mapping({"providers": {"ollama": {"model": "qwen3:4b-instruct", "num_ctx": 8192}}})
        self.assertEqual(cfg.problems, ())
        self.assertEqual(cfg.providers["ollama"].model, "qwen3:4b-instruct")


if __name__ == "__main__":
    unittest.main()

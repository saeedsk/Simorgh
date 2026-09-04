import unittest

from src.orchestrator.soul import CORE_DIRECTIVES, get, outranks


class TestSoul(unittest.TestCase):
    def test_priorities_are_sequential_and_unique(self):
        priorities = [d.priority for d in CORE_DIRECTIVES]
        self.assertEqual(priorities, list(range(1, len(CORE_DIRECTIVES) + 1)))

    def test_names_are_unique(self):
        names = [d.name for d in CORE_DIRECTIVES]
        self.assertEqual(len(names), len(set(names)))

    def test_safety_is_the_top_priority(self):
        self.assertEqual(get("Safety").priority, 1)

    def test_safety_and_lawfulness_outrank_loyalty(self):
        self.assertTrue(outranks("Safety", "Loyalty"))
        self.assertTrue(outranks("Lawfulness", "Loyalty"))

    def test_corrigibility_outranks_growth(self):
        self.assertTrue(outranks("Corrigibility", "Growth"))

    def test_restraint_outranks_growth(self):
        self.assertTrue(outranks("Restraint", "Growth"))

    def test_get_is_case_insensitive(self):
        self.assertEqual(get("safety").name, "Safety")

    def test_get_unknown_directive_raises(self):
        with self.assertRaises(KeyError):
            get("not-a-real-directive")


if __name__ == "__main__":
    unittest.main()

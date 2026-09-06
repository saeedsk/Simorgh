import unittest

from simorgh.ledger.streams import escape, is_per_id, is_valid_stream, prefix_of, unescape, validate_stream


class TestIsValidStream(unittest.TestCase):
    def test_valid_names(self):
        for name in ("task:abc123", "activity", "trace:xyz", "memory:episodic", "a", "a" * 128):
            self.assertTrue(is_valid_stream(name), name)

    def test_invalid_names(self):
        for name in ("Task:ABC", "has space", "semi;colon", "a" * 129, "", "path/like"):
            self.assertFalse(is_valid_stream(name), name)


class TestValidateStream(unittest.TestCase):
    def test_returns_the_name_when_valid(self):
        self.assertEqual(validate_stream("task:abc"), "task:abc")

    def test_raises_on_bad_name(self):
        with self.assertRaises(ValueError):
            validate_stream("BAD NAME")


class TestPrefixOf(unittest.TestCase):
    def test_per_id_stream(self):
        self.assertEqual(prefix_of("task:abc"), "task:")

    def test_singleton_stream(self):
        self.assertEqual(prefix_of("activity"), "activity")


class TestIsPerId(unittest.TestCase):
    def test_per_id_true(self):
        self.assertTrue(is_per_id("task:abc"))

    def test_singleton_false(self):
        self.assertFalse(is_per_id("activity"))


class TestEscapeUnescape(unittest.TestCase):
    def test_round_trip(self):
        name = "task:abc-123.x_y"
        self.assertEqual(unescape(escape(name)), name)

    def test_colon_is_percent_encoded(self):
        self.assertEqual(escape("task:abc"), "task%3Aabc")

    def test_escape_rejects_invalid_names(self):
        with self.assertRaises(ValueError):
            escape("BAD NAME")


if __name__ == "__main__":
    unittest.main()

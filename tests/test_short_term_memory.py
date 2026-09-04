import tempfile
import unittest
from pathlib import Path

from src.memory.short_term import ShortTermMemory


class TestShortTermMemory(unittest.TestCase):
    def test_add_then_recent_round_trips_oldest_first(self):
        memory = ShortTermMemory()
        memory.add("hi", "hello")
        memory.add("how are you", "fine")

        turns = memory.recent()

        self.assertEqual([t.request_text for t in turns], ["hi", "how are you"])

    def test_recent_respects_limit(self):
        memory = ShortTermMemory()
        memory.add("a", "1")
        memory.add("b", "2")
        memory.add("c", "3")

        turns = memory.recent(limit=2)

        self.assertEqual([t.request_text for t in turns], ["b", "c"])

    def test_max_turns_drops_oldest(self):
        memory = ShortTermMemory(max_turns=3)
        for i in range(5):
            memory.add(str(i), str(i))

        self.assertEqual(len(memory), 3)
        self.assertEqual([t.request_text for t in memory.recent()], ["2", "3", "4"])

    def test_max_chars_drops_oldest(self):
        memory = ShortTermMemory(max_turns=100, max_chars=20)
        memory.add("aaaaaaaaaa", "aaaaaaaaaa")  # 20 chars total
        memory.add("b", "b")  # pushes total over budget

        turns = memory.recent()

        self.assertEqual([t.request_text for t in turns], ["b"])

    def test_always_keeps_at_least_one_turn(self):
        memory = ShortTermMemory(max_turns=100, max_chars=1)
        memory.add("this alone exceeds the char budget", "so does this")

        self.assertEqual(len(memory), 1)

    def test_as_context_renders_transcript(self):
        memory = ShortTermMemory()
        memory.add("hi", "hello there")

        context = memory.as_context()

        self.assertEqual(context, "User: hi\nSim: hello there")

    def test_clear_empties_the_window(self):
        memory = ShortTermMemory()
        memory.add("hi", "hello")

        memory.clear()

        self.assertEqual(len(memory), 0)
        self.assertEqual(memory.recent(), [])

    def test_invalid_max_turns_raises(self):
        with self.assertRaises(ValueError):
            ShortTermMemory(max_turns=0)

    def test_invalid_max_chars_raises(self):
        with self.assertRaises(ValueError):
            ShortTermMemory(max_chars=0)


class TestSaveAndLoadAndClear(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "nested" / "relaunch_context.json"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_save_then_load_round_trips_turns_oldest_first(self):
        memory = ShortTermMemory()
        memory.add("hi", "hello")
        memory.add("how are you", "fine")

        memory.save(self.path)
        restored = ShortTermMemory.load_and_clear(self.path)

        self.assertIsNotNone(restored)
        self.assertEqual(
            [t.request_text for t in restored.recent()], ["hi", "how are you"]
        )
        self.assertEqual(
            [t.response_text for t in restored.recent()], ["hello", "fine"]
        )

    def test_load_and_clear_deletes_the_file_one_shot(self):
        memory = ShortTermMemory()
        memory.add("hi", "hello")
        memory.save(self.path)

        self.assertTrue(self.path.exists())
        ShortTermMemory.load_and_clear(self.path)

        self.assertFalse(self.path.exists())
        self.assertIsNone(ShortTermMemory.load_and_clear(self.path))

    def test_load_and_clear_missing_file_returns_none(self):
        self.assertIsNone(ShortTermMemory.load_and_clear(self.path))

    def test_load_and_clear_corrupt_file_returns_none_and_removes_it(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("not valid json{{{")

        result = ShortTermMemory.load_and_clear(self.path)

        self.assertIsNone(result)
        self.assertFalse(self.path.exists())

    def test_load_and_clear_ignores_malformed_entries(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            '[{"request_text": "ok", "response_text": "fine"}, '
            '{"request_text": 5, "response_text": "bad type"}, '
            '"not even a dict"]'
        )

        restored = ShortTermMemory.load_and_clear(self.path)

        self.assertIsNotNone(restored)
        self.assertEqual([t.request_text for t in restored.recent()], ["ok"])

    def test_restored_memory_still_respects_max_turns(self):
        memory = ShortTermMemory(max_turns=100)
        for i in range(5):
            memory.add(str(i), str(i))
        memory.save(self.path)

        restored = ShortTermMemory.load_and_clear(self.path, max_turns=2)

        self.assertEqual([t.request_text for t in restored.recent()], ["3", "4"])


if __name__ == "__main__":
    unittest.main()

import unittest

from src.memory.long_term import InMemoryStore
from src.orchestrator.activity_log import ActivityLog


class TestActivityLog(unittest.TestCase):
    def test_record_and_recover_conversation_turn(self):
        store = InMemoryStore()
        log = ActivityLog(store)

        log.record_conversation_turn("hi", "hello there")

        entries = log.recent()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].content, "hi")
        self.assertEqual(entries[0].metadata["reply"], "hello there")

    def test_record_and_recover_tool_call(self):
        store = InMemoryStore()
        log = ActivityLog(store)

        log.record_tool_call("logic", "FETCH", "https://example.com", "HTTP 200", True)

        entries = log.recent()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].metadata["tool"], "FETCH")
        self.assertTrue(entries[0].metadata["succeeded"])

    def test_recent_merges_multiple_kinds_chronologically(self):
        store = InMemoryStore()
        log = ActivityLog(store)

        log.record_conversation_turn("first", "reply1")
        log.record_tool_call("logic", "READ", "src/x.py", "10 chars", True)
        log.record_conversation_turn("second", "reply2")

        entries = log.recent(limit=10)

        contents = [e.content for e in entries]
        self.assertEqual(contents[0], "second")
        self.assertIn("first", contents)
        self.assertTrue(any(e.kind == "tool_call" for e in entries))

    def test_recent_respects_limit(self):
        store = InMemoryStore()
        log = ActivityLog(store)
        for i in range(5):
            log.record_conversation_turn(f"turn {i}", "reply")

        entries = log.recent(limit=2)

        self.assertEqual(len(entries), 2)

    def test_recent_can_filter_to_specific_kinds(self):
        store = InMemoryStore()
        log = ActivityLog(store)
        log.record_conversation_turn("hi", "hello")
        log.record_tool_call("logic", "READ", "src/x.py", "1 chars", True)

        entries = log.recent(kinds=("tool_call",))

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].kind, "tool_call")

    def test_format_entry_handles_every_known_kind_without_crashing(self):
        store = InMemoryStore()
        log = ActivityLog(store)
        log.record_conversation_turn("hi", "hello")
        log.record_tool_call("logic", "READ", "src/x.py", "1 chars", True)
        store.remember("outcome", "out", agent="logic", request_text="req", succeeded=True)
        store.remember("takeaway", "note", agent="logic")
        store.remember("applied_skill", "src/agents/skills/x.py", rationale="r")
        store.remember(
            "applied_source_patch", "src/x.py", rationale="r", test_summary="10 tests"
        )
        store.remember("rejected_proposal", "code", subject="x", reasons=["bad"])
        store.remember("web_fetch", "https://x.com", succeeded=True, note="ok")
        store.remember("llm_spend", "gemini", cost_usd=0.01)
        store.remember("interest", "rocketry", why="curious")
        store.remember("some_unknown_future_kind", "content")

        entries = log.recent(
            limit=20,
            kinds=(
                "conversation_turn",
                "tool_call",
                "outcome",
                "takeaway",
                "applied_skill",
                "applied_source_patch",
                "rejected_proposal",
                "web_fetch",
                "llm_spend",
                "interest",
                "some_unknown_future_kind",
            ),
        )

        for entry in entries:
            formatted = ActivityLog.format_entry(entry)
            self.assertIsInstance(formatted, str)
            self.assertTrue(formatted)


class TestSinceLastTurn(unittest.TestCase):
    def test_fewer_than_two_turns_falls_back_to_recent(self):
        store = InMemoryStore()
        log = ActivityLog(store)
        log.record_tool_call("logic", "READ", "src/x.py", "1 chars", True)
        log.record_conversation_turn("hi", "hello")

        entries = log.since_last_turn()

        self.assertEqual(len(entries), 2)

    def test_only_includes_activity_from_the_previous_turn_onward(self):
        store = InMemoryStore()
        log = ActivityLog(store)
        log.record_conversation_turn("first prompt", "first reply")
        log.record_tool_call("logic", "FETCH", "https://old.example", "old", True)
        log.record_conversation_turn("second prompt", "second reply")
        log.record_tool_call("logic", "FETCH", "https://new.example", "new", True)
        log.record_conversation_turn("third prompt", "third reply")

        entries = log.since_last_turn()
        contents = [e.content for e in entries]

        # Bounded by the SECOND-most-recent turn ("second prompt") onward
        # -- i.e. everything that happened while Sim was working on the
        # most recent ("third prompt") request.
        self.assertIn("second prompt", contents)
        self.assertIn("FETCH: https://new.example", contents)
        self.assertIn("third prompt", contents)
        self.assertNotIn("first prompt", contents)
        self.assertNotIn("FETCH: https://old.example", contents)

    def test_results_are_chronological_oldest_first(self):
        store = InMemoryStore()
        log = ActivityLog(store)
        log.record_conversation_turn("first", "r1")
        log.record_conversation_turn("second", "r2")
        log.record_conversation_turn("third", "r3")

        entries = log.since_last_turn()
        timestamps = [e.created_at for e in entries]

        self.assertEqual(timestamps, sorted(timestamps))


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path

from simorgh.ledger.backends.memory import InMemoryBackend
from simorgh.ledger.client import LedgerClient
from simorgh.ledger.migrate_v1 import read_v1_records, route_v1

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "v1_memory_sample.jsonl"


class TestRouteV1(unittest.TestCase):
    def test_task_event_routes_by_task_id(self):
        self.assertEqual(route_v1("task_event", {"task_id": "t1"}), "task:t1")

    def test_applied_source_patch_and_skill_route_to_learn(self):
        self.assertEqual(route_v1("applied_source_patch", {}), "learn:patches")
        self.assertEqual(route_v1("applied_skill", {}), "learn:skills")

    def test_llm_spend_routes_to_cognition_budget(self):
        self.assertEqual(route_v1("llm_spend", {}), "cognition:budget")

    def test_interest_kinds_route_to_curiosity(self):
        for kind in ("interest", "news_seen", "growth_shared"):
            self.assertEqual(route_v1(kind, {}), "curiosity:interests")

    def test_research_finding_routes_to_semantic_memory(self):
        self.assertEqual(route_v1("research_finding", {}), "memory:semantic")

    def test_activity_like_kinds_route_to_activity(self):
        for kind in ("autonomous_action", "activity", "tool_call"):
            self.assertEqual(route_v1(kind, {}), "activity")

    def test_rejected_proposal_routes_to_guardian(self):
        self.assertEqual(route_v1("rejected_proposal", {}), "guardian:rejected")

    def test_unknown_kind_falls_back_to_episodic_memory(self):
        self.assertEqual(route_v1("outcome", {}), "memory:episodic")
        self.assertEqual(route_v1("something_new", {}), "memory:episodic")


class TestReadV1Records(unittest.TestCase):
    def test_every_well_formed_record_routes_somewhere_sensible(self):
        events = {e.idempotency_key: e for e in read_v1_records(FIXTURE)}
        self.assertEqual(len(events), 10)  # the malformed line is skipped, not fatal
        self.assertEqual(events["v1:aaa1"].stream, "task:t1")
        self.assertEqual(events["v1:aaa1"].type, "v1.task_event")
        self.assertEqual(events["v1:aaa2"].stream, "learn:patches")
        self.assertEqual(events["v1:aaa3"].stream, "learn:skills")
        self.assertEqual(events["v1:aaa4"].stream, "cognition:budget")
        self.assertEqual(events["v1:aaa5"].stream, "curiosity:interests")
        self.assertEqual(events["v1:aaa6"].stream, "memory:semantic")
        self.assertEqual(events["v1:aaa7"].stream, "activity")
        self.assertEqual(events["v1:aaa8"].stream, "guardian:rejected")
        self.assertEqual(events["v1:aaa9"].stream, "memory:episodic")
        self.assertEqual(events["v1:aaa10"].stream, "task:t2")

    def test_content_and_metadata_are_preserved_in_the_payload(self):
        events = {e.idempotency_key: e for e in read_v1_records(FIXTURE)}
        self.assertEqual(events["v1:aaa2"].payload["content"], "patched")
        self.assertEqual(events["v1:aaa2"].payload["subject"], "src/x.py")

    def test_timestamps_are_preserved(self):
        events = {e.idempotency_key: e for e in read_v1_records(FIXTURE)}
        self.assertEqual(events["v1:aaa1"].ts, 1000.0)


class TestMigrateV1IsIdempotent(unittest.IsolatedAsyncioTestCase):
    async def test_replaying_the_fixture_twice_appends_nothing_the_second_time(self):
        client = LedgerClient(InMemoryBackend())
        await client.start()
        for _ in range(2):
            for event in read_v1_records(FIXTURE):
                await client.append(event.stream, event)
        self.assertEqual(client.counters["appends"], 10)
        self.assertEqual(client.counters["dedupes"], 10)
        # every routed stream really has exactly the record it should
        events = await client.read("task:t1", from_seq=0, limit=None)
        self.assertEqual(len(events), 1)
        await client.stop()


if __name__ == "__main__":
    unittest.main()

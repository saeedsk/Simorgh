import unittest

from src.memory.shared_bus import SharedMemoryBus


class TestSharedMemoryBus(unittest.TestCase):
    def test_read_returns_current_persona_state(self):
        bus = SharedMemoryBus()
        self.assertEqual(bus.read().valence, 0.0)

    def test_publish_delta_updates_state_and_is_readable(self):
        bus = SharedMemoryBus()
        bus.publish_delta("emotion", valence=0.3, arousal=0.2)
        state = bus.read()
        self.assertAlmostEqual(state.valence, 0.3)
        self.assertAlmostEqual(state.arousal, 0.2)

    def test_subscribers_are_notified_with_previous_new_and_source(self):
        bus = SharedMemoryBus()
        calls = []
        bus.subscribe(lambda prev, new, source: calls.append((prev, new, source)))

        bus.publish_state("emotion", valence=0.5)

        self.assertEqual(len(calls), 1)
        prev, new, source = calls[0]
        self.assertEqual(prev.valence, 0.0)
        self.assertEqual(new.valence, 0.5)
        self.assertEqual(source, "emotion")

    def test_logic_agent_can_instantly_read_mood_published_by_emotion_agent(self):
        bus = SharedMemoryBus()
        observed_tone = {}

        def logic_agent_listener(previous, new_state, source):
            if source == "emotion":
                observed_tone["valence"] = bus.read().valence

        bus.subscribe(logic_agent_listener)
        bus.publish_delta("emotion", valence=0.7)

        self.assertAlmostEqual(observed_tone["valence"], 0.7)

    def test_unsubscribe_stops_further_notifications(self):
        bus = SharedMemoryBus()
        calls = []
        unsubscribe = bus.subscribe(lambda prev, new, source: calls.append(source))

        bus.publish_delta("emotion", valence=0.1)
        unsubscribe()
        bus.publish_delta("emotion", valence=0.1)

        self.assertEqual(calls, ["emotion"])


if __name__ == "__main__":
    unittest.main()

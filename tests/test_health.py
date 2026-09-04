import unittest

from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.health import HealthMonitor, Severity
from src.orchestrator.persona_state import PersonaState


class TestHealthMonitorCheck(unittest.TestCase):
    def test_no_issues_on_short_history(self):
        monitor = HealthMonitor(window=5)
        state = PersonaState()
        state.set_state(valence=0.9)

        self.assertEqual(monitor.check(state.history()), [])

    def test_no_issues_on_calm_stable_history(self):
        monitor = HealthMonitor(window=5)
        state = PersonaState()
        for _ in range(6):
            state.set_state(valence=0.1, arousal=0.1, cognitive_load=0.2)

        self.assertEqual(monitor.check(state.history()), [])

    def test_detects_valence_pinned_at_extreme(self):
        monitor = HealthMonitor(window=5)
        state = PersonaState()
        for _ in range(5):
            state.set_state(valence=1.0)

        issues = monitor.check(state.history())

        self.assertTrue(any(i.severity is Severity.CRITICAL for i in issues))
        self.assertTrue(any("valence" in i.description for i in issues))

    def test_detects_arousal_pinned_at_extreme(self):
        monitor = HealthMonitor(window=5)
        state = PersonaState()
        for _ in range(5):
            state.set_state(arousal=-1.0)

        issues = monitor.check(state.history())

        self.assertTrue(any("arousal" in i.description for i in issues))

    def test_detects_sustained_high_cognitive_load(self):
        monitor = HealthMonitor(window=5)
        state = PersonaState()
        for _ in range(5):
            state.set_state(cognitive_load=0.95)

        issues = monitor.check(state.history())

        self.assertTrue(any(i.severity is Severity.WARNING for i in issues))
        self.assertTrue(any("cognitive load" in i.description for i in issues))

    def test_detects_oscillation(self):
        monitor = HealthMonitor(window=5)
        state = PersonaState()
        for i in range(6):
            state.set_state(valence=0.5 if i % 2 == 0 else -0.5)

        issues = monitor.check(state.history())

        self.assertTrue(any("oscillating" in i.description for i in issues))


class TestHealthMonitorEnforce(unittest.TestCase):
    def test_resets_mood_on_critical_issue(self):
        bus = SharedMemoryBus()
        for _ in range(5):
            bus.publish_state("test", valence=1.0, arousal=1.0)
        monitor = HealthMonitor(window=5)

        monitor.enforce(bus)

        state = bus.read()
        self.assertEqual(state.valence, 0.0)
        self.assertEqual(state.arousal, 0.0)

    def test_leaves_cognitive_load_untouched_on_reset(self):
        bus = SharedMemoryBus()
        bus.publish_state("test", cognitive_load=0.8)
        for _ in range(5):
            bus.publish_state("test", valence=1.0, arousal=1.0)
        monitor = HealthMonitor(window=5)

        monitor.enforce(bus)

        self.assertEqual(bus.read().cognitive_load, 0.8)

    def test_does_not_reset_on_stable_history(self):
        bus = SharedMemoryBus()
        bus.publish_state("test", valence=0.2, arousal=0.2)
        monitor = HealthMonitor(window=5)

        issues = monitor.enforce(bus)

        self.assertEqual(issues, [])
        self.assertEqual(bus.read().valence, 0.2)


if __name__ == "__main__":
    unittest.main()

import time
import unittest

from src.memory.long_term import InMemoryStore
from src.orchestrator.autonomy import ACTION_KIND, ActivityClock, AutonomyController


class TestActivityClock(unittest.TestCase):
    def test_idle_seconds_starts_near_zero(self):
        clock = ActivityClock()
        self.assertLess(clock.idle_seconds(), 1.0)

    def test_touch_resets_idle_seconds(self):
        clock = ActivityClock()
        clock._last_activity -= 1000  # simulate a long idle gap
        self.assertGreater(clock.idle_seconds(), 900)

        clock.touch()

        self.assertLess(clock.idle_seconds(), 1.0)


class TestAutonomyControllerReadyToAct(unittest.TestCase):
    def _controller(self, **overrides):
        store = InMemoryStore()
        clock = ActivityClock()
        clock._last_activity -= 10_000  # start "idle" for these tests
        kwargs = dict(
            store=store,
            clock=clock,
            perform_action=lambda: False,
            idle_threshold_seconds=60.0,
            action_cooldown_seconds=60.0,
            max_actions_per_day=5,
        )
        kwargs.update(overrides)
        return AutonomyController(**kwargs), store, clock

    def test_not_ready_when_disabled(self):
        controller, _, _ = self._controller(enabled=False)
        self.assertFalse(controller.ready_to_act())

    def test_not_ready_when_not_idle_long_enough(self):
        controller, _, clock = self._controller()
        clock.touch()  # just active

        self.assertFalse(controller.ready_to_act())

    def test_ready_when_idle_long_enough(self):
        controller, _, _ = self._controller()
        self.assertTrue(controller.ready_to_act())

    def test_not_ready_during_cooldown_after_a_real_action(self):
        controller, _, _ = self._controller(perform_action=lambda: True)

        self.assertTrue(controller.tick())
        self.assertFalse(controller.ready_to_act())

    def test_not_ready_once_daily_cap_is_reached(self):
        controller, store, _ = self._controller(max_actions_per_day=2, action_cooldown_seconds=0.0)
        for _ in range(2):
            store.remember(ACTION_KIND, "autonomous action taken")

        self.assertFalse(controller.ready_to_act())


class TestAutonomyControllerTick(unittest.TestCase):
    def _controller(self, perform_action):
        store = InMemoryStore()
        clock = ActivityClock()
        clock._last_activity -= 10_000
        controller = AutonomyController(
            store=store,
            clock=clock,
            perform_action=perform_action,
            idle_threshold_seconds=60.0,
            action_cooldown_seconds=60.0,
        )
        return controller, store

    def test_tick_does_nothing_when_not_ready(self):
        calls = []
        controller, store = self._controller(lambda: calls.append(1) or True)
        controller.enabled = False

        result = controller.tick()

        self.assertFalse(result)
        self.assertEqual(calls, [])

    def test_tick_calls_perform_action_when_ready(self):
        calls = []
        controller, store = self._controller(lambda: calls.append(1) or True)

        result = controller.tick()

        self.assertTrue(result)
        self.assertEqual(calls, [1])

    def test_a_no_op_action_does_not_record_or_start_cooldown(self):
        controller, store = self._controller(lambda: False)

        controller.tick()

        self.assertEqual(store.query(kind=ACTION_KIND), [])
        self.assertTrue(controller.ready_to_act())  # still ready -- no cooldown started

    def test_a_real_action_is_durably_recorded(self):
        controller, store = self._controller(lambda: True)

        controller.tick()

        self.assertEqual(len(store.query(kind=ACTION_KIND)), 1)

    def test_an_exception_from_perform_action_is_caught_not_raised(self):
        def raising():
            raise ValueError("boom")

        controller, store = self._controller(raising)

        result = controller.tick()  # must not raise

        self.assertFalse(result)
        self.assertEqual(store.query(kind=ACTION_KIND), [])


class TestActionsToday(unittest.TestCase):
    def test_counts_only_records_within_the_last_24_hours(self):
        from src.memory.long_term import MemoryRecord

        store = InMemoryStore()
        clock = ActivityClock()
        controller = AutonomyController(store=store, clock=clock, perform_action=lambda: True)
        store.remember(ACTION_KIND, "recent")
        store.add(MemoryRecord(id="old-id", kind=ACTION_KIND, content="old", created_at=time.time() - 90_000))

        self.assertEqual(controller.actions_today(), 1)


if __name__ == "__main__":
    unittest.main()

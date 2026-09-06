import unittest

from simorgh.kernel.state import (
    BOOTING,
    FAILED,
    InvalidTransition,
    PAUSED,
    RUNNING,
    STOPPED,
    STOPPING,
    SystemStateMachine,
)


class TestBoot(unittest.TestCase):
    def test_boot_complete_moves_to_running(self):
        m = SystemStateMachine()
        change = m.boot_complete()
        self.assertEqual(m.state, RUNNING)
        self.assertEqual(change.previous, BOOTING)
        self.assertEqual(change.state, RUNNING)

    def test_boot_complete_twice_raises(self):
        m = SystemStateMachine()
        m.boot_complete()
        with self.assertRaises(InvalidTransition):
            m.boot_complete()

    def test_boot_failed_moves_to_failed(self):
        m = SystemStateMachine()
        change = m.boot_failed("guardian did not start")
        self.assertEqual(m.state, FAILED)
        self.assertIn("guardian", change.reason)


class TestPauseResume(unittest.TestCase):
    def setUp(self):
        self.m = SystemStateMachine()
        self.m.boot_complete()

    def test_pause_moves_to_paused(self):
        change = self.m.pause(reason="human", requested_by="interface")
        self.assertEqual(self.m.state, PAUSED)
        self.assertEqual(change.scope, "all")

    def test_pause_is_idempotent(self):
        self.m.pause(reason="a", requested_by="x")
        change = self.m.pause(reason="b", requested_by="y")
        self.assertIsNone(change)
        self.assertEqual(self.m.state, PAUSED)

    def test_resume_from_paused_moves_to_running(self):
        self.m.pause(reason="a", requested_by="x")
        change = self.m.resume(reason="done", requested_by="interface")
        self.assertEqual(self.m.state, RUNNING)
        self.assertEqual(change.scope, "all")

    def test_resume_while_running_is_idempotent_noop(self):
        change = self.m.resume(reason="a", requested_by="x")
        self.assertIsNone(change)
        self.assertEqual(self.m.state, RUNNING)

    def test_scoped_autonomous_pause_does_not_change_top_level_state(self):
        change = self.m.pause(reason="autonomous off", requested_by="interface", scope="autonomous")
        self.assertEqual(self.m.state, RUNNING)  # top-level state machine unaffected
        self.assertTrue(self.m.autonomous_paused)
        self.assertEqual(change.scope, "autonomous")

    def test_scoped_autonomous_pause_is_idempotent(self):
        self.m.pause(reason="a", requested_by="x", scope="autonomous")
        change = self.m.pause(reason="b", requested_by="y", scope="autonomous")
        self.assertIsNone(change)

    def test_scoped_autonomous_resume_clears_the_scoped_flag(self):
        self.m.pause(reason="a", requested_by="x", scope="autonomous")
        change = self.m.resume(reason="b", requested_by="y", scope="autonomous")
        self.assertFalse(self.m.autonomous_paused)
        self.assertIsNotNone(change)

    def test_full_pause_also_reports_autonomous_paused(self):
        self.m.pause(reason="a", requested_by="x")
        self.assertTrue(self.m.autonomous_paused)

    def test_pause_from_booting_raises(self):
        m = SystemStateMachine()
        with self.assertRaises(InvalidTransition):
            m.pause(reason="a", requested_by="x")


class TestStop(unittest.TestCase):
    def test_stop_from_running_moves_to_stopping(self):
        m = SystemStateMachine()
        m.boot_complete()
        change = m.stop(reason="signal", requested_by="signal")
        self.assertEqual(m.state, STOPPING)
        self.assertEqual(change.previous, RUNNING)

    def test_stop_from_paused_proceeds_directly(self):
        m = SystemStateMachine()
        m.boot_complete()
        m.pause(reason="a", requested_by="x")
        change = m.stop(reason="b", requested_by="y")
        self.assertEqual(m.state, STOPPING)
        self.assertEqual(change.previous, PAUSED)

    def test_stopped_finalizes(self):
        m = SystemStateMachine()
        m.boot_complete()
        m.stop(reason="a", requested_by="x")
        change = m.stopped()
        self.assertEqual(m.state, STOPPED)
        self.assertEqual(change.state, STOPPED)


if __name__ == "__main__":
    unittest.main()

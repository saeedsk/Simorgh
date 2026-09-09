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


class AutoOffSurvivesARestartTestCase(unittest.TestCase):
    """`auto off` is a decision a person made about what this system may
    do on its own -- and it lived only in memory.

    Live-caught 2026-09-09: the creator ran `auto off`, autonomy stopped,
    and a few minutes later curiosity-origin tasks were running again.
    `_autonomous_paused` initialises to False on every boot and nothing
    read the history back, so any restart -- a loader reboot, a crash, a
    hot swap -- silently re-enabled autonomy, and nothing announced it.
    Being overruled by a detail of process lifetime is the opposite of
    corrigibility.
    """

    def test_a_scoped_pause_and_resume_are_distinguishable_on_the_wire(self):
        # Both leave `state == previous` (the system keeps running
        # either way), so before `autonomous_paused` was carried the two
        # ledger records were byte-identical and the flag could not be
        # restored at all.
        machine = SystemStateMachine("running")
        paused = machine.pause(reason="off", requested_by="cli", scope="autonomous")
        resumed = machine.resume(reason="on", requested_by="cli", scope="autonomous")
        self.assertEqual((paused.state, paused.previous), (resumed.state, resumed.previous))
        self.assertTrue(paused.autonomous_paused)
        self.assertFalse(resumed.autonomous_paused)

    def test_a_fresh_machine_can_be_told_autonomy_was_already_off(self):
        machine = SystemStateMachine("running")
        self.assertFalse(machine.autonomous_paused)
        machine.restore_autonomous_paused(True)
        self.assertTrue(machine.autonomous_paused)

    def test_restoring_does_not_pause_the_whole_system(self):
        # The point of a scoped pause: human work still runs.
        machine = SystemStateMachine("running")
        machine.restore_autonomous_paused(True)
        self.assertEqual(machine.state, "running")

    def test_a_full_pause_records_the_autonomous_flag_too(self):
        machine = SystemStateMachine("running")
        machine.pause(reason="off", requested_by="cli", scope="autonomous")
        change = machine.pause(reason="all stop", requested_by="cli", scope="all")
        self.assertTrue(change.autonomous_paused)

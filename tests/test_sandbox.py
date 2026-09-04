import unittest

from src.sandboxing.sandbox import SubprocessSandbox


class TestSubprocessSandbox(unittest.TestCase):
    def test_runs_code_and_captures_stdout(self):
        sandbox = SubprocessSandbox()
        result = sandbox.run("print('hello from sandbox')")
        self.assertTrue(result.succeeded)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("hello from sandbox", result.stdout)

    def test_captures_stderr_and_nonzero_exit_on_failure(self):
        sandbox = SubprocessSandbox()
        result = sandbox.run("raise ValueError('boom')")
        self.assertFalse(result.succeeded)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("ValueError", result.stderr)

    def test_enforces_wall_clock_timeout(self):
        sandbox = SubprocessSandbox()
        result = sandbox.run("import time; time.sleep(5)", timeout=0.5)
        self.assertTrue(result.timed_out)
        self.assertFalse(result.succeeded)

    def test_sandbox_process_has_no_access_to_orchestrator_objects(self):
        sandbox = SubprocessSandbox()
        result = sandbox.run(
            "import sys; print('PersonaState' in sys.modules or 'src' in sys.modules)"
        )
        self.assertTrue(result.succeeded)
        self.assertIn("False", result.stdout)


if __name__ == "__main__":
    unittest.main()

import contextlib
import io
import unittest
from unittest import mock

from simorgh.kernel.cli import _build_parser, main
from simorgh.kernel.config import ConfigError
from simorgh.kernel.service import KernelBootError


class TestArgumentParsing(unittest.TestCase):
    def setUp(self):
        self.parser = _build_parser()

    def test_no_arguments_means_no_command_and_no_self_check(self):
        args = self.parser.parse_args([])
        self.assertIsNone(args.command)
        self.assertFalse(args.self_check)
        self.assertIsNone(args.config)

    def test_self_check_flag(self):
        args = self.parser.parse_args(["--self-check"])
        self.assertTrue(args.self_check)

    def test_config_path_is_threaded_through(self):
        args = self.parser.parse_args(["--config", "/tmp/x.toml", "run"])
        self.assertEqual(args.config, "/tmp/x.toml")
        self.assertEqual(args.command, "run")

    def test_status_default_timeout(self):
        args = self.parser.parse_args(["status"])
        self.assertEqual(args.command, "status")
        self.assertEqual(args.timeout, 2.0)

    def test_status_explicit_timeout(self):
        args = self.parser.parse_args(["status", "--timeout", "9"])
        self.assertEqual(args.timeout, 9.0)

    def test_trace_requires_a_trace_id(self):
        args = self.parser.parse_args(["trace", "abc123"])
        self.assertEqual(args.command, "trace")
        self.assertEqual(args.trace_id, "abc123")
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["trace"])  # missing positional

    def test_migrate_v1_default_path(self):
        args = self.parser.parse_args(["migrate-v1"])
        self.assertTrue(args.path.endswith("memory.jsonl"))

    def test_migrate_v1_explicit_path(self):
        args = self.parser.parse_args(["migrate-v1", "--path", "/tmp/m.jsonl"])
        self.assertEqual(args.path, "/tmp/m.jsonl")

    def test_worker_requires_an_id(self):
        args = self.parser.parse_args(["worker", "--id", "w1"])
        self.assertEqual(args.command, "worker")
        self.assertEqual(args.worker_id, "w1")
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["worker"])  # missing --id


class TestMainDispatch(unittest.TestCase):
    """`main()`'s routing to the right `_cmd_*` coroutine and its exit-code
    plumbing, with the coroutines themselves mocked out -- actually
    booting a Kernel belongs to `test_service.py` and the integration
    tests, not to argument-dispatch tests."""

    async def _ok(self, *a, **k) -> int:
        return 0

    async def _fail(self, *a, **k) -> int:
        return 1

    def test_no_command_dispatches_to_cmd_run(self):
        with mock.patch("simorgh.kernel.cli._cmd_run", side_effect=self._ok) as m:
            code = main([])
        self.assertEqual(code, 0)
        m.assert_called_once_with(None)

    def test_run_command_dispatches_to_cmd_run(self):
        with mock.patch("simorgh.kernel.cli._cmd_run", side_effect=self._ok) as m:
            code = main(["run"])
        self.assertEqual(code, 0)
        m.assert_called_once_with(None)

    def test_status_command_dispatches_with_timeout(self):
        with mock.patch("simorgh.kernel.cli._cmd_status", side_effect=self._ok) as m:
            code = main(["status", "--timeout", "7"])
        self.assertEqual(code, 0)
        m.assert_called_once_with(None, 7.0)

    def test_trace_command_dispatches_with_trace_id(self):
        with mock.patch("simorgh.kernel.cli._cmd_trace", side_effect=self._ok) as m:
            code = main(["trace", "t-1"])
        self.assertEqual(code, 0)
        m.assert_called_once_with(None, "t-1")

    def test_migrate_v1_command_dispatches_with_path(self):
        with mock.patch("simorgh.kernel.cli._cmd_migrate_v1", side_effect=self._ok) as m:
            code = main(["migrate-v1", "--path", "/tmp/x.jsonl"])
        self.assertEqual(code, 0)
        m.assert_called_once_with(None, "/tmp/x.jsonl")

    def test_worker_command_dispatches_with_id(self):
        with mock.patch("simorgh.kernel.cli._cmd_worker", side_effect=self._ok) as m:
            code = main(["worker", "--id", "w2"])
        self.assertEqual(code, 0)
        m.assert_called_once_with(None, "w2")

    def test_worker_command_reports_boot_error_with_exit_code_2(self):
        async def _raise(*a, **k):
            raise KernelBootError("a worker process only makes sense under [runtime] mode = \"local-multi\"")

        with mock.patch("simorgh.kernel.cli._cmd_worker", side_effect=_raise):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(["worker", "--id", "w1"])
        self.assertEqual(code, 2)
        self.assertIn("local-multi", stderr.getvalue())

    def test_config_flag_is_passed_to_the_dispatched_command(self):
        with mock.patch("simorgh.kernel.cli._cmd_run", side_effect=self._ok) as m:
            main(["--config", "/tmp/simorgh.toml", "run"])
        m.assert_called_once_with("/tmp/simorgh.toml")

    def test_non_zero_exit_code_from_a_command_propagates(self):
        with mock.patch("simorgh.kernel.cli._cmd_status", side_effect=self._fail):
            code = main(["status"])
        self.assertEqual(code, 1)

    def test_config_error_is_caught_and_reported_with_exit_code_2(self):
        async def _raise(*a, **k):
            raise ConfigError("bad mode")

        with mock.patch("simorgh.kernel.cli._cmd_run", side_effect=_raise):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(["run"])
        self.assertEqual(code, 2)
        self.assertIn("bad mode", stderr.getvalue())

    def test_kernel_boot_error_is_caught_and_reported_with_exit_code_2(self):
        async def _raise(*a, **k):
            raise KernelBootError("guardian did not start")

        with mock.patch("simorgh.kernel.cli._cmd_run", side_effect=_raise):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(["run"])
        self.assertEqual(code, 2)
        self.assertIn("guardian did not start", stderr.getvalue())


class TestSelfCheckEndToEnd(unittest.TestCase):
    """The real `--self-check` path, in-memory and side-effect free --
    the same acceptance bar `simorgh --self-check` is judged by."""

    def test_self_check_exits_zero_and_prints_overall_pass(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["--self-check"])
        self.assertEqual(code, 0)
        self.assertIn("OVERALL: PASS", stdout.getvalue())

    def test_self_check_flag_short_circuits_before_any_subcommand_dispatch(self):
        with mock.patch("simorgh.kernel.cli._cmd_run") as m:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main(["--self-check", "run"])
            m.assert_not_called()


if __name__ == "__main__":
    unittest.main()

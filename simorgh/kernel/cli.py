"""`python -m simorgh …` (docs/blueprint/subsystems/03-kernel.md sections
3.5/5/10). Subcommands are thin: they either boot the Kernel and run
until stopped, or publish one message / read the Ledger and print plain
text -- rendering a real interactive session is Interface's job
(section 1's "explicit non-responsibilities"), not the Kernel's.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .migrate_v1 import DEFAULT_V1_MEMORY_PATH, migrate
from .selfcheck import run as run_selfcheck
from .service import Kernel, KernelBootError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="simorgh")
    parser.add_argument("--config", default=None, help="path to simorgh.toml")
    parser.add_argument("--self-check", action="store_true",
                        help="prove the guarded action path works, then exit")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="boot the Kernel and run until stopped")
    status_p = sub.add_parser("status", help="print the current system.status snapshot")
    status_p.add_argument("--timeout", type=float, default=2.0)
    trace_p = sub.add_parser("trace", help="print the causal message trace for an id")
    trace_p.add_argument("trace_id")
    migrate_p = sub.add_parser("migrate-v1", help="import ~/.simorgh/memory.jsonl into the Ledger")
    migrate_p.add_argument("--path", default=str(DEFAULT_V1_MEMORY_PATH))
    return parser


async def _cmd_self_check() -> int:
    result = await run_selfcheck()
    print(result.report())
    return 0 if result.passed else 1


async def _cmd_run(config_path: str | None) -> int:
    config = load_config(config_path)
    kernel = Kernel(config, interactive=True)
    await kernel.boot()

    loop = asyncio.get_running_loop()
    stopped_by_signal = {"sigint_count": 0}

    def _handle_signal() -> None:
        stopped_by_signal["sigint_count"] += 1
        if stopped_by_signal["sigint_count"] >= 2:
            print("second interrupt -- exiting immediately", file=sys.stderr)
            sys.exit(130)
        asyncio.ensure_future(kernel.bus.publish(_stop_message()))

    def _stop_message():
        from simorgh.contracts.envelope import Message
        from simorgh.contracts import topics

        return Message.new(topics.SYSTEM_STOP, source="kernel",
                           payload={"reason": "signal", "requested_by": "signal"}, priority=9)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except (NotImplementedError, RuntimeError):
            pass  # not every platform/loop supports signal handlers (e.g. some test runners)

    await kernel.wait_for_stop()
    await kernel.shutdown()
    return 0


async def _cmd_status(config_path: str | None, timeout: float) -> int:
    config = load_config(config_path)
    kernel = Kernel(config)
    try:
        await kernel.boot()
        import json

        print(json.dumps(kernel.status_snapshot(), indent=2, default=str))
    finally:
        await kernel.shutdown()
    return 0


async def _cmd_trace(config_path: str | None, trace_id: str) -> int:
    config = load_config(config_path)
    from simorgh.ledger.factory import make_ledger

    ledger = make_ledger({"backend": "jsonl", "data_dir": str(config.runtime.data_dir / "ledger")})
    await ledger.start()
    try:
        events = await ledger.read(f"trace:{trace_id}")
        if not events:
            print(f"no trace recorded for {trace_id!r} (tracing may be sampled out, or the id is unknown)")
            return 1
        for event in events:
            print(f"{event.ts:.3f}  {event.type:30s}  {event.payload}")
    finally:
        await ledger.stop()
    return 0


async def _cmd_migrate_v1(config_path: str | None, path: str) -> int:
    config = load_config(config_path)
    from simorgh.ledger.factory import make_ledger

    ledger = make_ledger({"backend": "jsonl", "data_dir": str(config.runtime.data_dir / "ledger")})
    await ledger.start()
    try:
        report = await migrate(ledger, Path(path).expanduser())
        print(report.summary())
    finally:
        await ledger.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.self_check:
        return asyncio.run(_cmd_self_check())

    try:
        if args.command == "run" or args.command is None:
            return asyncio.run(_cmd_run(args.config))
        if args.command == "status":
            return asyncio.run(_cmd_status(args.config, args.timeout))
        if args.command == "trace":
            return asyncio.run(_cmd_trace(args.config, args.trace_id))
        if args.command == "migrate-v1":
            return asyncio.run(_cmd_migrate_v1(args.config, args.path))
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    except KernelBootError as exc:
        print(f"boot failed: {exc}", file=sys.stderr)
        return 2

    parser.print_help()
    return 1


__all__ = ["main"]

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
from .service import Kernel, KernelBootError, WorkerKernel


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="simorgh")
    parser.add_argument("--config", default=None, help="path to simorgh.toml")
    parser.add_argument("--self-check", action="store_true",
                        help="prove the guarded action path works, then exit")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="boot the Kernel and run until stopped")
    worker_p = sub.add_parser(
        "worker", help="start a local-multi worker process (Orchestration only; see [runtime] mode)"
    )
    worker_p.add_argument("--id", dest="worker_id", required=True, help="this worker's instance id, e.g. w1")
    status_p = sub.add_parser("status", help="print the current system.status snapshot")
    status_p.add_argument("--timeout", type=float, default=2.0)
    trace_p = sub.add_parser("trace", help="print the causal message trace for an id")
    trace_p.add_argument("trace_id")
    migrate_p = sub.add_parser("migrate-v1", help="import ~/.simorgh/memory.jsonl into the Ledger")
    migrate_p.add_argument("--path", default=str(DEFAULT_V1_MEMORY_PATH))

    # The vault is a CLI subcommand and NOT a REPL command on purpose.
    # Adding a secret means typing it, and the REPL's line reader echoes
    # what it is given and keeps it in history -- so a password typed
    # there would end up on the screen and in a file. `getpass` here
    # reads it with the terminal's echo off and it never becomes an
    # argument, which is what `platform-connectors-design.md` section 1
    # means by "never a tool argument".
    vault_p = sub.add_parser("vault", help="manage stored credentials (never prints a value)")
    vault_sub = vault_p.add_subparsers(dest="vault_command")
    vault_sub.add_parser("list", help="ids, kinds and ages -- never values")
    add_p = vault_sub.add_parser("add", help="store a credential, prompting with echo off")
    add_p.add_argument("cred_id", help="e.g. imap:fastmail, caldav:home, home_assistant")
    add_p.add_argument("--kind", default="password",
                       help="password | token | oauth2 | keyfile | cookie_jar")
    add_p.add_argument("--field", default="password",
                       help="which field of the credential this is")
    remove_p = vault_sub.add_parser("remove", help="delete a credential")
    remove_p.add_argument("cred_id")
    import_p = vault_sub.add_parser(
        "import", help="copy a value in ONCE from elsewhere (env:NAME, file:PATH)")
    import_p.add_argument("cred_id")
    import_p.add_argument("source")
    import_p.add_argument("--kind", default="password")
    import_p.add_argument("--field", default="password")
    stale_p = vault_sub.add_parser("stale", help="credentials nothing has used lately")
    stale_p.add_argument("--days", type=float, default=90.0)
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


async def _cmd_worker(config_path: str | None, worker_id: str) -> int:
    config = load_config(config_path)
    worker = WorkerKernel(config, worker_id=worker_id)
    await worker.boot()

    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        # A worker process shuts itself down on SIGINT/SIGTERM; unlike
        # `simorgh run` it never publishes `system.stop` -- that would
        # (mis)stop the whole deployment from a process that owns none of
        # guardian/execution/the state machine.
        worker.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except (NotImplementedError, RuntimeError):
            pass  # not every platform/loop supports signal handlers (e.g. some test runners)

    await worker.wait_for_stop()
    await worker.shutdown()
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


def _vault_for(config_path: str | None):
    """The vault this machine uses.

    `[secrets] vault_path` wins, then `SIMORGH_VAULT_PATH`, then
    `~/.simorgh/vault.bin`. A broken config must not make the vault
    unreachable -- being locked out of your credentials because a TOML
    key has a typo is a bad afternoon -- so a config that will not load
    falls back to the default path rather than failing.
    """
    from .vault import Vault, default_vault_path

    raw = ""
    try:
        raw = str(load_config(config_path).section("secrets").get("vault_path", "") or "")
    except Exception:  # noqa: BLE001 -- see the docstring
        raw = ""
    return Vault(Path(raw) if raw else default_vault_path())


def _cmd_vault(args) -> int:
    """Never prints a stored value. `list` shows ids and ages, `add`
    prompts with echo off, and nothing here has a code path that writes
    a secret to stdout -- which is the property that makes it safe to
    run over someone's shoulder."""
    import getpass
    import time

    command = getattr(args, "vault_command", None) or "list"
    try:
        vault = _vault_for(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"vault unavailable: {exc}", file=sys.stderr)
        return 2

    if command == "list":
        rows = vault.list()
        print(f"vault at {vault.path} (key from {vault.key_source})")
        if not rows:
            print("  empty -- add one with `simorgh vault add <id>`, e.g.")
            print("  simorgh vault add imap:fastmail")
            return 0
        for credential in rows:
            used = (time.strftime("%Y-%m-%d", time.localtime(credential.last_used_at))
                    if credential.last_used_at else "never")
            print(f"  {credential.id:28} {credential.kind:10} last used {used}")
        return 0

    if command == "add":
        value = getpass.getpass(f"value for {args.cred_id} ({args.field}): ")
        if not value:
            print("nothing entered; nothing stored", file=sys.stderr)
            return 1
        existing = {}
        try:
            existing = dict(vault.open(args.cred_id))
        except Exception:  # noqa: BLE001 -- a new credential has nothing to merge
            pass
        existing[args.field] = value
        vault.put(args.cred_id, args.kind, existing)
        print(f"stored {args.cred_id} ({args.field}). The value was never echoed and is not "
              f"in your shell history.")
        return 0

    if command == "remove":
        vault.delete(args.cred_id)
        print(f"removed {args.cred_id}")
        return 0

    if command == "import":
        from .vault import ImportSourceError, resolve_import_source

        try:
            value = resolve_import_source(args.source)
        except ImportSourceError as exc:
            print(f"could not read {args.source}: {exc}", file=sys.stderr)
            return 1
        vault.put(args.cred_id, args.kind, {args.field: value})
        # Deliberately not the value, and deliberately saying the copy
        # is a copy: `import` reads once and never again, so rotating
        # the source does not rotate this.
        print(f"copied {args.source} into {args.cred_id} ({args.field}). It is a copy -- "
              f"rotating the source will not rotate this.")
        return 0

    if command == "stale":
        rows = vault.stale(days=args.days)
        if not rows:
            print(f"nothing unused for {args.days:.0f} days")
            return 0
        print(f"{len(rows)} credential(s) unused for {args.days:.0f} days:")
        for credential in rows:
            print(f"  {credential.id}")
        return 0

    print(f"unknown vault command {command!r}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.self_check:
        return asyncio.run(_cmd_self_check())

    try:
        if args.command == "run" or args.command is None:
            return asyncio.run(_cmd_run(args.config))
        if args.command == "worker":
            return asyncio.run(_cmd_worker(args.config, args.worker_id))
        if args.command == "status":
            return asyncio.run(_cmd_status(args.config, args.timeout))
        if args.command == "trace":
            return asyncio.run(_cmd_trace(args.config, args.trace_id))
        if args.command == "vault":
            return _cmd_vault(args)
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

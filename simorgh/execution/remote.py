"""`run_remote`: run a command on a machine that is not this one.

The gap: everything Sim can do, it does on the box it runs on. A build
that needs a GPU, a deploy that has to happen on the server, a test
suite that only reproduces on Linux -- all of it was out of reach, and
the honest answer was "ask a human to run this".

Built before any host exists, on purpose (the creator, 2026-09-09:
build it so that "when the skill will be needed, user will provide
account or api key ... but still the sim infra needs to be ready"). It
is configured entirely by environment variables and refuses cleanly,
naming them, when they are absent.

THE DESTINATION IS NOT THE MODEL'S TO CHOOSE. This is the single most
important property here and the reason the tool is shaped this way. The
model supplies a command; the host, user and key come from the
operator's environment and nowhere else. There is deliberately no
`host` argument, and adding one would turn this from "run my build on
my server" into a general-purpose way to send anything on this machine
to any machine on the internet -- an exfiltration channel with a
friendly name. A model that has been prompt-injected by a web page it
read can, at worst, run the wrong command on a host its operator
already chose.

The rest of the boundary:

- **Guardian sees every call.** `irreversible` -- a command that has run
  on another machine cannot be un-run, and this tool cannot even see
  what it did. With `irreversible_requires_human` set, every call waits.
- **Off unless configured.** `[execution] remote = false` is the
  default, one step stricter than `run_shell`'s default-on, because the
  blast radius is a machine this code cannot inspect, roll back, or
  reason about.
- **The same refusal list as `run_shell`**, for the same reason and with
  the same caveat: it guards against the catastrophic accident, not
  against a determined evasion. `rm -rf /` on a remote host is worse
  than locally, not better, because nothing here snapshots it.
- **Key-based auth only.** `BatchMode=yes` means ssh never prompts: no
  password ever passes through this process, and a misconfigured host
  fails fast instead of hanging on a prompt nobody can answer. A
  password-authenticated host is simply not usable here, which is the
  correct answer rather than a limitation to work around.
- **Host keys are checked.** `StrictHostKeyChecking=yes` by default, so
  an unknown or changed host key is a refusal rather than a shrug.
  Turning it off is possible and says so loudly in the config comment.

Nothing here ever reads or logs the private key: only its path, and
only to say a file is missing.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import time

from simorgh.contracts.protocols import ToolContext, ToolResult

from .config import Config
from .shell import DEFAULT_SHELL_REFUSALS

HOST_ENV = "SIMORGH_REMOTE_HOST"
USER_ENV = "SIMORGH_REMOTE_USER"
KEY_ENV = "SIMORGH_REMOTE_KEY"
PORT_ENV = "SIMORGH_REMOTE_PORT"
REQUIRED = (HOST_ENV,)

# A hostname/IP, and nothing that could be read as an ssh option or a
# second argument. Anchored, no spaces, no leading dash: an operator
# typo must not turn into `ssh -oProxyCommand=...`.
_HOST_RE = re.compile(r"^(?!-)[A-Za-z0-9._:-]{1,253}$")
_USER_RE = re.compile(r"^(?!-)[A-Za-z0-9._-]{1,64}$")


class RemoteUnavailable(Exception):
    """No command was run, and this is why."""


def settings(env) -> dict:
    """Host/user/key/port from the environment, validated.

    Raises rather than falling back to a default host: there is no
    sensible default for "which machine", and guessing one would run a
    command somewhere nobody chose.
    """
    missing = [name for name in REQUIRED if not (env.get(name) or "").strip()]
    if missing:
        raise RemoteUnavailable(
            f"no remote host is configured: set {', '.join(missing)}"
            + f" (optionally {USER_ENV}, {KEY_ENV}, {PORT_ENV})"
        )
    host = (env.get(HOST_ENV) or "").strip()
    if not _HOST_RE.match(host):
        raise RemoteUnavailable(f"{HOST_ENV} is not a plain hostname or address: {host!r}")
    user = (env.get(USER_ENV) or "").strip()
    if user and not _USER_RE.match(user):
        raise RemoteUnavailable(f"{USER_ENV} is not a plain username: {user!r}")
    port = (env.get(PORT_ENV) or "").strip()
    if port and not port.isdigit():
        raise RemoteUnavailable(f"{PORT_ENV} is not a number: {port!r}")
    return {"host": host, "user": user, "key": (env.get(KEY_ENV) or "").strip(), "port": port}


def refusal_for(command: str, patterns: dict[str, str]) -> str:
    for pattern, why in patterns.items():
        if re.search(pattern, command):
            return why
    return ""


def ssh_argv(command: str, config: Config, found: dict) -> list[str]:
    """The exact argv. No shell on this side: the command is one
    argument to ssh, so nothing in it is interpreted locally."""
    argv = [
        "ssh", "-o", "BatchMode=yes",
        "-o", f"StrictHostKeyChecking={'yes' if config.remote_strict_host_key else 'no'}",
        "-o", f"ConnectTimeout={int(config.remote_connect_timeout_s)}",
    ]
    if found["key"]:
        argv += ["-i", found["key"], "-o", "IdentitiesOnly=yes"]
    if found["port"]:
        argv += ["-p", found["port"]]
    target = f"{found['user']}@{found['host']}" if found["user"] else found["host"]
    argv.append(target)
    if config.remote_working_dir:
        command = f"cd {shlex.quote(config.remote_working_dir)} && {command}"
    argv.append(command)
    return argv


def _head(text: str, limit: int = 120) -> str:
    collapsed = " ".join((text or "").split())
    return collapsed[:limit] + ("…" if len(collapsed) > limit else "")


class RunRemoteTool:
    name = "run_remote"
    description = (
        "Run a shell command on the remote host this system is configured for (a build machine, "
        "a deploy target). The host is fixed by configuration -- you choose the command, never "
        "the destination. Irreversible: nothing here can undo what runs there."
    )
    read_only = False
    reversibility = "irreversible"
    args_schema = {"type": "object", "required": ["command"],
                   "properties": {"command": {"type": "string"}}}

    def __init__(self, config: Config, *, env=None, runner=None) -> None:
        self._config = config
        self._env = env
        self._runner = runner or subprocess.run

    @property
    def env(self):
        import os

        return self._env if self._env is not None else os.environ

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        import asyncio

        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolResult(ok=False, error="refused: no command given")
        command = command.strip()

        why = refusal_for(command, self._config.shell_refusals)
        if why:
            return ToolResult(ok=False, error=f"refused: {why} -- on a remote host, with nothing here able to undo it")

        try:
            found = settings(self.env)
        except RemoteUnavailable as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")

        if found["key"]:
            from pathlib import Path

            if not Path(found["key"]).expanduser().is_file():
                # The path, never the contents.
                return ToolResult(
                    ok=False,
                    error=f"refused: {KEY_ENV} points at no such file: {found['key']}",
                )

        argv = ssh_argv(command, self._config, found)
        timeout = min(ctx.constraints.get("timeout_s", self._config.remote_timeout_s),
                      self._config.remote_timeout_s)
        start = time.monotonic()
        try:
            completed = await asyncio.wait_for(
                asyncio.to_thread(
                    self._runner, argv, capture_output=True, text=True,
                    timeout=timeout, stdin=subprocess.DEVNULL,
                ),
                timeout=timeout + 10.0,
            )
        except (asyncio.TimeoutError, subprocess.TimeoutExpired):
            return ToolResult(ok=False, error="timeout",
                              metadata={"duration_s": time.monotonic() - start})
        except FileNotFoundError:
            return ToolResult(ok=False, error="refused: no `ssh` executable on this machine")
        except OSError as exc:
            return ToolResult(ok=False, error=f"could not run ssh: {exc!r}")

        cap = self._config.remote_output_max_chars
        ok = completed.returncode == 0
        where = f"{found['user']}@{found['host']}" if found["user"] else found["host"]
        return ToolResult(
            ok=ok,
            output=(completed.stdout or "")[-cap:],
            error=None if ok else f"exit_code={completed.returncode} on {where}",
            # `run_remote:<command>` and nothing about what it changed --
            # unlike run_shell, this tool genuinely cannot know. Saying
            # otherwise would be the honesty failure the checks exist to
            # prevent: no `written_paths`, no cleanup, no claim to either.
            side_effects=(f"run_remote:{_head(command)}",),
            metadata={
                "stderr": (completed.stderr or "")[-cap:], "exit_code": completed.returncode,
                "duration_s": time.monotonic() - start, "host": found["host"],
                "remote": True,
                "note": "this ran on another machine; nothing local tracked or can revert it",
            },
        )

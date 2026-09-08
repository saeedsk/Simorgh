"""Real shell access, through Guardian rather than around it.

The creator, 2026-09-07: "give sim file system write access and shell
access".

This is the most capable tool Sim has, and the only one whose blast
radius is not bounded by its own arguments: a shell can write anywhere
the user can, so the repo-scoped limits every other write tool enforces
are advisory once this exists. That is the point of asking for it, and it
is worth saying plainly rather than pretending otherwise.

Three things make it a tool rather than a hole:

- **Guardian sees every call**, which is the creator's own standing
  architectural constraint. It is declared `irreversible`, so
  `ReversibilityRule` decides: with `irreversible_requires_human` set
  (the dataclass default) every command waits for a human; with
  auto-approve on (what `sim.sh` sets today) they run. One switch,
  already wired, already understood.
- **A refusal list for the catastrophic**, in `DEFAULT_SHELL_REFUSALS`.
  Not an attempt at a security boundary -- a shell has no such thing, and
  anything here can be trivially rewritten to evade it. It is a guard
  against the specific class of accident this system has already
  demonstrated: a small model that has, in one day, hallucinated test
  results, written its own prose into a source file, and looped on the
  same call eight times. `rm -rf /` as a typo is a real risk; `rm -rf /`
  as a deliberate evasion is not what this list is for.
- **It runs in the repo, with a timeout, and its output is bounded**, so
  a runaway command ends and says why.

`run_python_sandboxed` remains the right tool for running a snippet, and
`apply_source_patch` for editing a file. This is for the rest: build
steps, git operations beyond commit, package tooling, one-off inspection.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time

from typing import TYPE_CHECKING

from simorgh.contracts.protocols import ToolContext, ToolResult

if TYPE_CHECKING:  # `config` imports the refusal table from here
    from .config import Config

# Patterns refused outright, with the reason the model is told. Ordered
# by how bad the accident is, not by how likely.
DEFAULT_SHELL_REFUSALS: dict[str, str] = {
    r"\brm\s+(-[a-zA-Z]*\s+)*(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+/(\s|$)":
        "recursive delete of the filesystem root",
    r"\brm\s+(-[a-zA-Z]*\s+)*~(/\s*)?(\s|$)": "recursive delete of the home directory",
    r"\bmkfs(\.|\s)": "formats a filesystem",
    r"\bdd\s+[^|]*\bof=/dev/": "writes directly to a block device",
    r">\s*/dev/(sd|nvme|disk)": "writes directly to a block device",
    r"\bsudo\b": "asks for elevated privileges; run it yourself if you mean it",
    r"\b(curl|wget)\b[^|]*\|\s*(ba|z|k|)sh\b": "pipes a download straight into a shell",
    r"\bgit\s+push\b.*(--force|-f)\b": "force-pushes, which can destroy someone else's history",
    r"\bgit\s+push\b": "pushes to a remote; publishing is the creator's call",
    r"\bshutdown\b|\breboot\b|\bhalt\b": "shuts the machine down",
    r":\(\)\s*\{.*\|.*&\s*\}\s*;": "is a fork bomb",
}

# What a command may print back. Enough to be useful, bounded so one
# runaway command cannot fill the context.
_OUTPUT_CAP = 8_000


def refusal_for(command: str, refusals: dict[str, str] | None = None) -> str | None:
    """The reason to refuse `command`, or `None` to let it run."""
    for pattern, reason in (refusals or DEFAULT_SHELL_REFUSALS).items():
        if re.search(pattern, command):
            return reason
    return None


class RunShellTool:
    name = "run_shell"
    description = "Run a shell command in the repository and return its output."
    read_only = False
    # Guardian's ReversibilityRule gates every call on this. A shell can
    # do anything, so it is never quietly waved through as "reversible".
    reversibility = "irreversible"
    args_schema = {
        "type": "object",
        "required": ["command"],
        "properties": {"command": {"type": "string"}},
    }

    def __init__(self, config: "Config") -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        command = str(args.get("command", "")).strip()
        if not command:
            return ToolResult(ok=False, error="refused: no command given")
        reason = refusal_for(command, dict(self._config.shell_refusals))
        if reason is not None:
            return ToolResult(ok=False, error=f"refused: that command {reason}")

        timeout = self._config.shell_timeout_s
        env = dict(os.environ)
        # A command that stops to ask a question would hang until the
        # timeout and tell nobody why.
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["DEBIAN_FRONTEND"] = "noninteractive"
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command, shell=True, cwd=self._config.repo_root, capture_output=True, text=True,
                timeout=timeout, stdin=subprocess.DEVNULL, env=env,
            )
        except subprocess.TimeoutExpired as exc:
            return ToolResult(
                ok=False, output=(exc.stdout or "")[-_OUTPUT_CAP:],
                error=f"timed out after {timeout:.0f}s",
                metadata={"command": command, "duration_s": time.monotonic() - started},
            )
        except OSError as exc:
            return ToolResult(ok=False, error=f"could not run it: {exc!r}")

        ok = completed.returncode == 0
        output = (completed.stdout or "")[-_OUTPUT_CAP:]
        if not ok:
            # The reason a command failed is usually on stderr, and a
            # result with an empty body teaches the model nothing.
            stderr = (completed.stderr or "")[-_OUTPUT_CAP:]
            output = f"{output}\n{stderr}".strip() or f"exited {completed.returncode} with no output"
        return ToolResult(
            ok=ok, output=output,
            error=None if ok else f"exit_code={completed.returncode}",
            side_effects=(f"run_shell:{shlex.split(command)[0] if command else ''}",),
            metadata={
                "command": command, "exit_code": completed.returncode,
                "duration_s": time.monotonic() - started,
            },
        )


__all__ = ["DEFAULT_SHELL_REFUSALS", "RunShellTool", "refusal_for"]

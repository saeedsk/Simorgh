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
    # `rm -rf ~` was covered; `rm -rf ~/ws`, `rm -rf $HOME` and
    # `rm -rf /*` were not -- the same accident one character apart
    # (observer, 2026-09-08).
    r"\brm\s+(-[a-zA-Z]*\s+)*(~|\$HOME|\$\{HOME\})(/|\s|$)":
        "recursive delete under the home directory",
    r"\brm\s+(-[a-zA-Z]*\s+)*/\*": "recursive delete of everything under the filesystem root",
    r"\bfind\s+/\s[^|]*-delete\b": "deletes everything it finds from the filesystem root",
    r"\bfind\s+/\s[^|]*-exec\s+rm\b": "deletes everything it finds from the filesystem root",
    r"\bchmod\s+(-[a-zA-Z]*\s+)*(-R\s+)?[0-7]{3,4}\s+/(\s|$)":
        "changes permissions on the whole filesystem",
    r"\bchown\s+(-[a-zA-Z]*\s+)*(-R\s+)?[^\s]+\s+/(\s|$)":
        "changes ownership of the whole filesystem",
    r"\bgit\s+clean\b[^|]*-[a-zA-Z]*[xd]": "deletes untracked and ignored files, which git cannot undo",
    r"\bgit\s+reset\s+--hard\b": "discards committed work irrecoverably; use git_revert",
    r"\bgit\s+checkout\b[^|]*\s--\s": "discards uncommitted work; use git_discard",
    r"\b(curl|wget)\b[^|]*\|\s*(python|python3|perl|ruby|node)\b":
        "pipes a download straight into an interpreter",
    r"\bdiskutil\s+(erase|reformat)": "erases a disk",
    r"\bkill\s+-9\s+-1\b": "kills every process the user owns",
    r"\bmkfs(\.|\s)": "formats a filesystem",
    r"\bdd\s+[^|]*\bof=/dev/": "writes directly to a block device",
    r">\s*/dev/(sd|nvme|disk)": "writes directly to a block device",
    # Anchored, so the word inside a quoted string is not a refusal
    # (`echo 'contains sudo'` used to be refused -- observer, 2026-09-08).
    r"(^|[;&|]\s*)sudo\s": "asks for elevated privileges; run it yourself if you mean it",
    r"\b(curl|wget)\b[^|]*\|\s*(ba|z|k|)sh\b": "pipes a download straight into a shell",
    r"\bgit\s+push\b.*(--force|-f)\b": "force-pushes, which can destroy someone else's history",
    r"\bgit\s+push\b": "pushes to a remote; publishing is the creator's call",
    r"\bshutdown\b|\breboot\b|\bhalt\b": "shuts the machine down",
    r":\(\)\s*\{.*\|.*&\s*\}\s*;": "is a fork bomb",
}

# What a command may print back. Enough to be useful, bounded so one
# runaway command cannot fill the context.
_OUTPUT_CAP = 8_000


def _cap(text: str) -> str:
    """Keep the HEAD and say so. It used to keep the tail in silence, so
    a truncated listing looked complete to the model -- and every other
    tool here marks its cut (observer, 2026-09-08)."""
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + (
        f"\n...[cut at {_OUTPUT_CAP} of {len(text)} chars; narrow the command, "
        "or pipe it through head/grep/wc]"
    )


def _head(command: str) -> str:
    """The program name, for the side effect. `shlex.split` raises on an
    unbalanced quote, which escaped `run()` as a ValueError instead of a
    ToolResult (observer, 2026-09-08)."""
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    return parts[0] if parts else ""


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
        output = _cap(completed.stdout or "")
        # stderr matters on success too: a command can exit 0 and warn,
        # and dropping that made the warning invisible (observer,
        # 2026-09-08).
        stderr = _cap(completed.stderr or "")
        if not ok:
            # The reason a command failed is usually on stderr, and a
            # result with an empty body teaches the model nothing.
            output = f"{output}\n{stderr}".strip() or f"exited {completed.returncode} with no output"
        elif stderr:
            output = f"{output}\n[stderr]\n{stderr}".strip()
        return ToolResult(
            ok=ok, output=output,
            error=None if ok else f"exit_code={completed.returncode}",
            side_effects=(f"run_shell:{_head(command)}",),
            metadata={
                "command": command, "exit_code": completed.returncode,
                "duration_s": time.monotonic() - started,
            },
        )


__all__ = ["DEFAULT_SHELL_REFUSALS", "RunShellTool", "refusal_for"]

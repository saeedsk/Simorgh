"""`run_script`: run a Python program with the project's interpreter,
the repo importable, and the network reachable.

The gap this fills, from the 2026-09-09 post-mortem: `run_python_sandboxed`
is deliberately isolated (temp cwd, empty env, no repo) and Guardian's
denylist refuses hand-written network code inside it -- so the way to
use a library that fetches data was `run_shell`, the broadest tool Sim
has, with a `python -c` string. That works and is a bad habit: the
command is unstructured, the code is not visible to the checks that
read `code`, and the blast radius is a whole shell.

This is the narrow version. The payload arrives as `code`, which means
`DenylistRule` and `StaticAnalysisRule` both read it -- so
`requests.get(...)` written here is refused exactly as it is in the
sandbox, while `import homeharvest` and calling a library that does its
own networking is fine. That distinction is the point: use a reviewed
library, do not hand-roll a socket.

It still runs real code with real access, so it is `irreversible` and
Guardian gates every call.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from simorgh.contracts.protocols import ToolContext, ToolResult

from . import writewatch
from .config import Config

try:  # pragma: no cover -- POSIX only, same guard as tools.py
    import resource
except ImportError:  # pragma: no cover
    resource = None


class RunScriptTool:
    name = "run_script"
    description = (
        "Run a Python script with this project's interpreter, the repo importable and the network "
        "available -- for using an installed library. Irreversible: Guardian gates every call."
    )
    read_only = False
    reversibility = "irreversible"
    args_schema = {"type": "object", "required": ["code"], "properties": {"code": {"type": "string"}}}

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        code = args.get("code")
        if not isinstance(code, str) or not code.strip():
            return ToolResult(ok=False, error="refused: no code given")
        directory = self._config.repo_root / self._config.script_dir
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{ctx.action_id}.py"
            path.write_text(code)
            self._prune(directory)
        except OSError as exc:
            return ToolResult(ok=False, error=f"could not stage the script: {exc!r}")

        timeout = min(ctx.constraints.get("timeout_s", self._config.script_timeout_s),
                      self._config.script_timeout_s)
        start = time.monotonic()
        # What the script writes is found the same way run_shell's is
        # (writewatch.py) -- a script that saves a file through pandas
        # is writing just as surely as a heredoc is, and the
        # verification checks need to know either way.
        before = writewatch.snapshot(self._config.repo_root)
        # Not an empty environment: a script's whole reason to exist here
        # is to use an installed library, and a library that reaches the
        # network needs PATH/HOME/proxy settings to do it. Still a
        # curated list, not `os.environ` wholesale -- a subprocess should
        # not inherit every credential in the session by default.
        env = {name: os.environ[name] for name in self._config.script_env_passthrough if name in os.environ}
        env["PYTHONPATH"] = str(self._config.repo_root)
        preexec = (
            _rlimits(self._config.script_cpu_seconds, self._config.script_memory_mb * 1024 * 1024)
            if resource else None
        )
        try:
            completed = subprocess.run(
                [sys.executable, str(path)], capture_output=True, text=True,
                cwd=str(self._config.repo_root), env=env, timeout=timeout,
                preexec_fn=preexec, stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            return ToolResult(
                ok=False, output=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                error="timeout", metadata={"duration_s": time.monotonic() - start},
            )
        except OSError as exc:
            return ToolResult(ok=False, error=f"could not run the script: {exc!r}")
        cap = self._config.script_output_max_chars
        ok = completed.returncode == 0
        after = writewatch.snapshot(self._config.repo_root)
        written = writewatch.written_between(before, after)
        return ToolResult(
            ok=ok, output=completed.stdout[-cap:],
            error=None if ok else f"exit_code={completed.returncode}",
            side_effects=writewatch.side_effects_for(written, before, after),
            metadata={"stderr": completed.stderr[-cap:], "exit_code": completed.returncode,
                      "duration_s": time.monotonic() - start, "written_paths": written},
        )

    def _prune(self, directory: Path) -> None:
        scripts = sorted(directory.glob("*.py"), key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in scripts[self._config.script_keep_files:]:
            try:
                stale.unlink()
            except OSError:
                pass


def _rlimits(cpu_seconds: int, memory_bytes: int):
    def _set() -> None:
        for res, value in (
            (getattr(resource, "RLIMIT_CPU", None), cpu_seconds),
            (getattr(resource, "RLIMIT_AS", None), memory_bytes),
            (getattr(resource, "RLIMIT_CORE", None), 0),
        ):
            if res is None:
                continue
            try:
                resource.setrlimit(res, (value, value))
            except (ValueError, OSError):
                pass
    return _set

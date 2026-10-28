"""The workbench: `run_analysis`, a program over Sim's own data (stage 19 items 1-2).

`run_python_sandboxed` runs `python -I` in an empty temp directory with an
empty environment. That is right for standalone code and useless for a
household job: the program can see no tool result, call no tool and keep
nothing, so the model counted "the top senders of the month" by reading
the 67 lines of a 200-row listing it could see (2026-10-28).

A workbench run is the same kind of child -- a fresh `python -I`, the
sandbox's rlimits, an environment holding only what is named below -- with
three things the sandbox lacks:

- **A job directory**, `<workbench_dir>/<job>/` (default
  `results/work/<job>/`), where `<job>` is the session or task id the
  proposal carried. It persists across calls in one job: `work.db` written
  by one call is there for the next. Inputs are copied in read-only as
  `inputs/<id>.json` from the full-rows store `results/<id>.json`, and every
  result this job produced is copied in too. Directories nothing has
  touched for `workbench_keep_days` are swept.
- **The `sim` module** (`workbench_sim.py`, copied in as `.sim/sim.py`):
  `rows`, `db`, `call`, `save`, `result`.
- **A tool bridge.** `sim.call(tool, **args)` writes one JSON line on a
  pipe; the parent hands it to the bridge Execution's `Service` binds at
  start (`bind_bridge`), which proposes it to Guardian as its own action
  (`action.proposed`, `proposed_by="execution"`, `parent_action_id` = this
  run) and waits for the result through `Service._on_approved`, the path a
  model's call takes. Read-only tools only, at most `workbench_max_calls`
  per run. Without a bound bridge `sim.call` answers that the bridge is
  unavailable, and nothing runs.

**The confinement is Python's, and it is not a security boundary.** The
child installs an audit hook (`_RUNNER`) before the program runs: reads
only under the workdir and the interpreter's own install, writes only
under the workdir (never `inputs/`), no subprocess, no socket, no ctypes,
no sqlite extension or ATTACH. A determined program can get past an audit
hook; what bounds it is Guardian reading the `code` argument (as it does
for `run_python_sandboxed`) and the rlimits. It is still strictly more
confined than the sandbox, which can read and write anything the user can.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import signal
import stat
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable

try:
    import resource
except ImportError:  # POSIX-only
    resource = None  # type: ignore[assignment]

from simorgh.contracts.protocols import ToolContext, ToolResult

from .config import Config

NAME = "run_analysis"
#: Never callable through the bridge, whatever they declare: a program
#: inside a program, or a tool about the offer rather than the world.
BRIDGE_NEVER = frozenset({NAME, "run_python_sandboxed", "run_js_sandboxed", "run_script", "run_tests",
                          "tool_more"})
#: The bridge `Service` binds: `(tool, args, *, parent=ToolContext) -> ToolResult`
#: whose metadata carries `action_id`, `ref` (the nested call's results
#: id, "" when it returned no rows) and `rows` (every stored row).
Bridge = Callable[..., Awaitable[ToolResult]]

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_JOB_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_REPLY_OUTPUT_CHARS = 65536
_LINE_LIMIT = 1 << 20
#: How long past its own budget `_on_approved` gives a run: the kill, the
#: drain and the result.
_MARGIN_S = 30.0


def job_id(task_id: str | None, action_id: str) -> str:
    """The job a call belongs to: its task or session id, else the call itself."""
    raw = str(task_id or "") or f"action-{action_id}"
    cleaned = _JOB_UNSAFE.sub("_", raw).strip("._") or f"action-{action_id}"
    return cleaned[:96]


def results_ref_id(ref: str) -> str:
    """`results/<id>.json`, `<id>.json` or `<id>` -> `<id>`; "" when it is none of those."""
    text = str(ref or "").strip()
    if text.startswith("results/"):
        text = text[len("results/"):]
    if text.endswith(".json"):
        text = text[: -len(".json")]
    return text if _ID.match(text) and ".." not in text else ""


def bridge_refusal(name: str, tool) -> str:
    """Why `sim.call(name)` may not run, or "" when it may."""
    if tool is None:
        return f"refused: unknown tool {name!r}"
    if name in BRIDGE_NEVER:
        return f"refused: {name} cannot be called from {NAME} (a program or a meta tool)"
    if not getattr(tool, "read_only", False) or getattr(tool, "reversibility", "irreversible") == "irreversible":
        return (f"refused: {name} is not read-only; {NAME} may call read-only tools only -- "
                "propose it as its own step")
    return ""


def job_refs_path(config: Config, job: str) -> Path:
    """The job's index of result ids, beside (not inside) its workdir, so
    the program cannot add another job's results to it."""
    return config.repo_root / config.workbench_dir / f"{job}.refs"


def record_job_ref(config: Config, job: str, action_id: str) -> None:
    """Note that `results/<action_id>.json` belongs to `job` (from `_store_rows`)."""
    path = job_refs_path(config, job)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(action_id + "\n")


def job_refs(config: Config, job: str) -> list[str]:
    """The job's result ids, oldest first, whose files still exist."""
    path = job_refs_path(config, job)
    try:
        lines = path.read_text(encoding="utf-8").split()
    except OSError:
        return []
    results = config.repo_root / config.results_dir
    seen: list[str] = []
    for ident in lines:
        if _ID.match(ident) and ident not in seen and (results / f"{ident}.json").is_file():
            seen.append(ident)
    return seen


def ref_note(action_id: str, count: int) -> str:
    """The line every structured result ends with (stage 19 item 3)."""
    return f"ref: {action_id} ({count} rows) -- use {NAME} inputs=[{action_id}] to compute over all of it"


# The child's entry point, written to `.sim/run.py`. The audit hook goes
# in before the program is compiled; `sim` is importable and also handed
# to the program as a global.
_RUNNER = r'''
import os, sys
_SIM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SIM_DIR)
import csv, json, sqlite3, io, re, math, statistics, collections, datetime, itertools  # warm, before the hook
import sim

_real = os.path.realpath
_WORK = _real(os.environ["SIM_WORKDIR"])
_INPUTS = os.path.join(_WORK, "inputs")
_READ = [_WORK] + sorted({_real(p) for p in (sys.prefix, sys.base_prefix, sys.exec_prefix,
                                              sys.base_exec_prefix) if p})
_READ_FILES = {"/dev/null", "/dev/urandom", "/dev/random", "/etc/localtime"}
_READ_TREES = ["/usr/share/zoneinfo", "/usr/lib/locale"]
_BRIDGE = {int(x) for x in os.environ.get("SIM_BRIDGE", "").split(",") if x}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_DENY = ("subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty",
         "os.kill", "os.killpg", "pty.", "socket.", "ctypes.", "sqlite3.enable_load_extension",
         "sqlite3.load_extension", "webbrowser.", "urllib.", "http.", "ftplib.", "smtplib.", "poplib.",
         "imaplib.", "nntplib.", "telnetlib.", "shutil.unpack_archive", "os.chroot", "os.setuid", "os.setgid")
_DENY_IMPORT = {"_posixsubprocess", "ctypes", "_ctypes", "multiprocessing", "_multiprocessing"}
_PATH_WRITE = {"os.mkdir": (0,), "os.rmdir": (0,), "os.remove": (0,), "os.rename": (0, 1), "os.chmod": (0,),
               "os.chown": (0,), "os.link": (0, 1), "os.symlink": (1,), "os.truncate": (0,), "os.utime": (0,),
               "os.chflags": (0,), "os.lchflags": (0,), "os.setxattr": (0,), "os.removexattr": (0,),
               "shutil.rmtree": (0,), "shutil.move": (0, 1), "shutil.copyfile": (1,), "shutil.copytree": (1,)}
_PATH_READ = {"os.listdir": (0,), "os.scandir": (0,), "glob.glob": (0,), "os.listxattr": (0,),
              "os.getxattr": (0,), "shutil.copyfile": (0,), "shutil.copytree": (0,)}


def _under(path, roots):
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


def _resolve(path):
    if isinstance(path, int) or path is None:
        return None
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    path = os.fspath(path)
    return _real(path if os.path.isabs(path) else os.path.join(os.getcwd(), path))


def _may_read(path):
    real = _resolve(path)
    return (real is None or _under(real, _READ) or real in _READ_FILES or _under(real, _READ_TREES))


def _may_write(path):
    real = _resolve(path)
    if real is None:
        return True
    return _under(real, [_WORK]) and not _under(real, [_INPUTS])


def _refuse(event, why):
    raise PermissionError(f"run_analysis: {event} refused -- {why}")


def _deny_attach(action, *_args):
    return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_ATTACH else sqlite3.SQLITE_OK


class _Guarded(sqlite3.Connection):
    """Every connection: ATTACH (which opens a file outside Python's
    `open`) is denied. `sqlite3.connect/handle` fires before a connection
    is initialised, so the authorizer is set here, after it is."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_authorizer(_deny_attach)


_connect = sqlite3.connect


def _guarded_connect(*args, **kwargs):
    kwargs["factory"] = _Guarded
    return _connect(*args, **kwargs)


sqlite3.connect = _guarded_connect


def _hook(event, args):
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        if isinstance(path, int):
            return
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS)
        if writing and not _may_write(path):
            _refuse(event, f"writes go in the workdir only ({path!r})")
        if not writing and not _may_read(path):
            _refuse(event, f"only the workdir and this job's inputs are readable ({path!r})")
        return
    if event == "import":
        if args and str(args[0]).split(".")[0] in _DENY_IMPORT:
            _refuse(event, f"{args[0]} is not available in the workbench")
        return
    if event == "sqlite3.connect":
        db = str(args[0]) if args else ""
        if db.startswith("file:"):
            db = db[5:].split("?", 1)[0]
        if db not in ("", ":memory:") and not _may_write(db):
            _refuse(event, f"a database goes in the workdir ({db!r})")
        return
    if event == "sqlite3.connect/handle":
        if args and not isinstance(args[0], _Guarded):
            _refuse(event, "connect with sqlite3.connect or sim.db()")
        return
    if event in _PATH_WRITE:
        for i in _PATH_WRITE[event]:
            if i < len(args) and not _may_write(args[i]):
                _refuse(event, f"changes go in the workdir only ({args[i]!r})")
    if event in _PATH_READ:
        for i in _PATH_READ[event]:
            if i < len(args) and not _may_read(args[i]):
                _refuse(event, f"only the workdir and this job's inputs are readable ({args[i]!r})")
        return
    if event.startswith(_DENY):
        _refuse(event, "the workbench has no subprocess, network or native code; use sim.call for a tool")


sys.addaudithook(_hook)
with open(os.path.join(_SIM_DIR, "program.py"), encoding="utf-8") as _f:
    _code = compile(_f.read(), "program.py", "exec")
try:
    exec(_code, {"__name__": "__main__", "__builtins__": __builtins__, "sim": sim})
finally:
    sim._close()
'''


def _apply_rlimits(cpu_seconds: int, memory_bytes: int):
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


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _copy_readonly(source: Path, target: Path) -> None:
    if target.exists():
        with contextlib.suppress(OSError):
            target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    shutil.copyfile(source, target)
    target.chmod(stat.S_IRUSR | stat.S_IRGRP)


def _write_readonly(target: Path, text: str) -> None:
    if target.exists():
        with contextlib.suppress(OSError):
            target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    target.write_text(text, encoding="utf-8")
    target.chmod(stat.S_IRUSR | stat.S_IRGRP)


class RunAnalysisTool:
    """`run_analysis{code, inputs?, timeout_s?}`: a program over this job's
    full data, with `sim.rows/db/call/save/result`. See the module docstring."""

    name = NAME
    read_only = True  # for its own effects; what it calls is gated one by one
    reversibility = "reversible"  # it runs a program, as `run_python_sandboxed` does
    description = (
        "Run a Python program over the FULL data of this job, never a listing you read: count, rank, "
        "group, join, dedupe, compare. `import sim`: sim.rows(ref) gives every row of a result "
        "(name it in `inputs`, or 'last'); sim.call(tool, **args) calls a read-only tool and returns "
        "{ok, output, rows, ref} -- loop it to paginate or fetch per item; sim.db() is a SQLite "
        "database kept across calls in this job; sim.save(name, rows_or_text) writes a .csv/.json/.md; "
        "sim.result(rows) hands rows back. Print the answer. Stdlib only, no network except sim.call.")
    args_schema = {
        "type": "object", "required": ["code"],
        "properties": {
            "code": {"type": "string", "description": "the Python program; print what the answer needs"},
            "inputs": {"type": "array", "items": {"type": "string"},
                       "description": "result refs to copy in: an action id, results/<id>.json, or 'last'"},
            "timeout_s": {"type": "number", "description": "wall-clock seconds, capped by config"},
        },
    }

    def __init__(self, config: Config, *, bridge: Bridge | None = None) -> None:
        self._config = config
        self._bridge = bridge

    @property
    def timeout_s(self) -> float:
        # `service.timeout_for` reads this: the run's own budget plus the
        # kill and drain, so `_on_approved` never cuts a run from outside.
        return float(self._config.workbench_timeout_s) + _MARGIN_S

    def bind_bridge(self, bridge: Bridge | None) -> None:
        """Execution's `Service` binds its gated dispatcher here at start."""
        self._bridge = bridge

    # -- the job directory -------------------------------------------------

    def _root(self) -> Path:
        return self._config.repo_root / self._config.workbench_dir

    def sweep(self, *, now: float | None = None) -> list[str]:
        """Remove job directories (and their indexes) untouched for `workbench_keep_days`."""
        root = self._root()
        if not root.is_dir():
            return []
        cutoff = (now if now is not None else time.time()) - float(self._config.workbench_keep_days) * 86400.0
        swept: list[str] = []
        for entry in root.iterdir():
            try:
                stale = entry.stat().st_mtime < cutoff
            except OSError:
                continue
            if not stale:
                continue
            if entry.is_dir():
                for path in entry.rglob("*"):
                    with contextlib.suppress(OSError):
                        path.chmod(stat.S_IRWXU)
                shutil.rmtree(entry, ignore_errors=True)
            else:
                with contextlib.suppress(OSError):
                    entry.unlink()
            swept.append(entry.name)
        return swept

    def _workdir(self, job: str) -> Path:
        workdir = self._root() / job
        (workdir / "inputs").mkdir(parents=True, exist_ok=True)
        (workdir / ".sim").mkdir(exist_ok=True)
        os.utime(workdir)
        return workdir

    def _copy_inputs(self, refs: list, job: str, workdir: Path) -> tuple[list[str], str, str]:
        """Copy the named refs and the job's own results into `inputs/`.
        Returns `(ids copied, the newest id, a refusal)`."""
        results = self._config.repo_root / self._config.results_dir
        own = job_refs(self._config, job)
        named: list[str] = []
        for ref in refs:
            if str(ref).strip() == "last":
                if not own:
                    return [], "", "refused: inputs=['last'] but this job has no stored result yet"
                ident = own[-1]
            else:
                ident = results_ref_id(str(ref))
                if not ident:
                    return [], "", f"refused: {ref!r} is not a result ref (an action id or results/<id>.json)"
            if not (results / f"{ident}.json").is_file():
                return [], "", f"refused: no stored result {ident!r} (results/{ident}.json does not exist)"
            if ident not in named:
                named.append(ident)
        for ident in own + named:
            _copy_readonly(results / f"{ident}.json", workdir / "inputs" / f"{ident}.json")
        last = named[-1] if named else (own[-1] if own else "")
        return named, last, ""

    # -- the run ------------------------------------------------------------

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        if not getattr(self._config, "workbench", True):
            return ToolResult(ok=False, error="the workbench is off ([execution] workbench = false)",
                              error_kind="unconfigured")
        code = args.get("code")
        if not isinstance(code, str) or not code.strip():
            return ToolResult.refused("refused: run_analysis needs `code`, a Python program")
        inputs = args.get("inputs") or []
        if isinstance(inputs, str):
            inputs = [part.strip() for part in inputs.split(",") if part.strip()]
        if not isinstance(inputs, list):
            return ToolResult.refused("refused: `inputs` is a list of result refs")
        limit = float(self._config.workbench_timeout_s)
        try:
            asked = float(args.get("timeout_s") or limit)
        except (TypeError, ValueError):
            asked = limit
        timeout = max(1.0, min(asked, limit, float(ctx.constraints.get("timeout_s") or limit)))

        job = job_id(ctx.task_id, ctx.action_id)
        self.sweep()
        workdir = self._workdir(job)
        named, last, refusal = self._copy_inputs(inputs, job, workdir)
        if refusal:
            return ToolResult.refused(refusal)
        here = Path(__file__).resolve().parent
        shutil.copyfile(here / "workbench_sim.py", workdir / ".sim" / "sim.py")
        (workdir / ".sim" / "run.py").write_text(_RUNNER, encoding="utf-8")
        (workdir / ".sim" / "program.py").write_text(code, encoding="utf-8")
        with contextlib.suppress(FileNotFoundError):
            (workdir / ".sim" / "result.json").unlink()
        before = self._snapshot(workdir)

        calls: list[dict] = []
        started = time.monotonic()
        outcome = await self._spawn(workdir, job, last, timeout, ctx, calls)
        returncode, stdout, stderr, timed_out = outcome
        duration = time.monotonic() - started

        rows = self._result_rows(workdir)
        files = self._changed(workdir, before)
        rel = f"{self._config.workbench_dir}/{job}"
        output = stdout
        notes = []
        if files:
            notes.append("files: " + ", ".join(f"{rel}/{name}" for name in files))
        if calls:
            refused = sum(1 for c in calls if not c.get("ok"))
            notes.append(f"tool calls: {len(calls)}" + (f" ({refused} not ok)" if refused else ""))
        if notes:
            output = (output.rstrip("\n") + "\n\n" if output.strip() else "") + "\n".join(notes)
        metadata = {"stderr": stderr, "exit_code": returncode, "duration_s": duration, "job": job,
                    "workdir": rel, "inputs": named, "files": files, "calls": calls}
        if rows is not None:
            metadata["rows"] = rows
        if timed_out:
            return ToolResult(ok=False, output=output, error=f"timeout after {timeout:.0f}s",
                              error_kind="transient", metadata=metadata)
        ok = returncode == 0
        return ToolResult(ok=ok, output=output, error=None if ok else f"exit_code={returncode}",
                          error_kind="" if ok else "failed", metadata=metadata)

    async def _spawn(self, workdir: Path, job: str, last: str, timeout: float, ctx: ToolContext,
                     calls: list[dict]) -> tuple[int, str, str, bool]:
        child_in, parent_out = os.pipe()   # replies: parent -> child
        parent_in, child_out = os.pipe()   # requests: child -> parent
        env = {"SIM_WORKDIR": str(workdir), "SIM_WORKDIR_REF": f"{self._config.workbench_dir}/{job}",
               "SIM_LAST": last, "SIM_BRIDGE": f"{child_in},{child_out}"}
        preexec = (_apply_rlimits(self._config.sandbox_cpu_seconds, self._config.sandbox_memory_mb * 1024 * 1024)
                   if resource else None)
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-I", str(workdir / ".sim" / "run.py"),
                cwd=str(workdir), env=env, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                pass_fds=(child_in, child_out), start_new_session=True, preexec_fn=preexec,
            )
        finally:
            os.close(child_in)
            os.close(child_out)
        chunks = {"out": bytearray(), "err": bytearray()}
        readers = [asyncio.ensure_future(self._drain(proc.stdout, chunks["out"])),
                   asyncio.ensure_future(self._drain(proc.stderr, chunks["err"]))]
        server = asyncio.ensure_future(self._serve(parent_in, parent_out, ctx, calls))
        timed_out = False
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            await self._kill(proc)
        except asyncio.CancelledError:
            await self._kill(proc)
            raise
        finally:
            server.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await server
            for fd in (parent_in, parent_out):
                with contextlib.suppress(OSError):
                    os.close(fd)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(asyncio.gather(*readers, return_exceptions=True), timeout=5.0)
        text = lambda b: b.decode("utf-8", "replace")  # noqa: E731
        return (proc.returncode if proc.returncode is not None else -1, text(chunks["out"]),
                text(chunks["err"]), timed_out)

    @staticmethod
    async def _drain(stream, into: bytearray) -> None:
        if stream is None:
            return
        with contextlib.suppress(Exception):
            while True:
                chunk = await stream.read(65536)
                if not chunk:
                    return
                into.extend(chunk)

    @staticmethod
    async def _kill(proc) -> None:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if proc.returncode is not None:
                return
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.killpg(proc.pid, sig)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=1.5)

    async def _serve(self, read_fd: int, write_fd: int, ctx: ToolContext, calls: list[dict]) -> None:
        """Answer the child's `sim.call` lines, one at a time, until it closes the pipe."""
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=_LINE_LIMIT)
        transport, _ = await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), os.fdopen(os.dup(read_fd), "rb", buffering=0))
        try:
            while True:
                try:
                    line = await reader.readline()
                except ValueError:  # a line over the limit
                    reply = {"ok": False, "error": "refused: a sim.call request over 1 MB"}
                    await asyncio.to_thread(_write_all, write_fd, (json.dumps(reply) + "\n").encode())
                    continue
                if not line:
                    return
                reply = await self._answer(line, ctx, calls)
                await asyncio.to_thread(_write_all, write_fd,
                                        (json.dumps(reply, default=str) + "\n").encode("utf-8"))
        finally:
            transport.close()

    async def _answer(self, line: bytes, ctx: ToolContext, calls: list[dict]) -> dict:
        empty = {"ok": False, "output": "", "rows": [], "ref": ""}
        try:
            request = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {**empty, "error": "refused: a sim.call request that is not JSON"}
        tool = str(request.get("tool") or "")
        call_args = request.get("args") if isinstance(request.get("args"), dict) else {}
        if self._bridge is None:
            return {**empty, "error": "the tool bridge is unavailable here (no dispatcher bound); "
                                      "sim.call cannot reach a tool"}
        cap = int(self._config.workbench_max_calls)
        if len(calls) >= cap:
            calls.append({"tool": tool, "ok": False, "refused": "cap"})
            return {**empty, "error": f"refused: this run already made {cap} tool calls "
                                      "(workbench_max_calls); save what you have and run again"}
        try:
            result = await self._bridge(tool, call_args, parent=ctx)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- the program gets the reason, the run goes on
            result = ToolResult(ok=False, error=f"the bridge failed: {exc!r}")
        meta = result.metadata or {}
        rows = meta.get("rows") if isinstance(meta.get("rows"), list) else []
        ref = str(meta.get("ref") or "")
        if ref and rows:
            # The nested result is this job's too: copied in, so `sim.rows(ref)`
            # reads it in this run and the next.
            workdir = self._root() / job_id(ctx.task_id, ctx.action_id)
            with contextlib.suppress(OSError):
                _write_readonly(workdir / "inputs" / f"{ref}.json", json.dumps(rows, default=str))
        calls.append({"tool": tool, "action_id": str(meta.get("action_id") or ""), "ok": bool(result.ok),
                      "ref": ref})
        return {"ok": bool(result.ok), "output": str(result.output or "")[:_REPLY_OUTPUT_CHARS],
                "rows": rows, "ref": ref, "error": str(result.error or "")}

    @staticmethod
    def _snapshot(workdir: Path) -> dict[str, float]:
        seen: dict[str, float] = {}
        for path in workdir.iterdir():
            if path.is_file() and not path.name.startswith("."):
                with contextlib.suppress(OSError):
                    seen[path.name] = path.stat().st_mtime_ns
        return seen

    def _changed(self, workdir: Path, before: dict[str, float]) -> list[str]:
        after = self._snapshot(workdir)
        return sorted(name for name, mtime in after.items() if before.get(name) != mtime)

    @staticmethod
    def _result_rows(workdir: Path) -> list | None:
        path = workdir / ".sim" / "result.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, list) else None


def workbench_tools(config: Config) -> list:
    """`run_analysis` when `[execution] workbench` is on (the default).

    Registered beside the meta tools, out of `builtin_tools`, like
    `tool_more` and `memory_core_edit`: the narration verbs and the
    policy tables in other packages that walk `builtin_tools` have no row
    for it until Orchestration offers it (stage 19 item 7)."""
    return [RunAnalysisTool(config)] if getattr(config, "workbench", True) else []


__all__ = ["BRIDGE_NEVER", "NAME", "RunAnalysisTool", "bridge_refusal", "job_id", "job_refs",
           "record_job_ref", "ref_note", "results_ref_id", "workbench_tools"]

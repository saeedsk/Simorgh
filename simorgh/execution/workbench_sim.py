"""`sim`: the helper module a `run_analysis` program imports (stage 19 item 1).

This file is not imported by Sim. `workbench.py` copies it into each run's
workdir as `.sim/sim.py`, and the child process (`python -I`, cwd = the
workdir) imports it from there. It is stdlib-only and must stay so: the
child sees no package of Sim's, no environment and no repository.

    import sim
    rows = sim.rows("last")                    # an input, or a file this job saved
    con = sim.db()                             # work.db, kept across calls in this job
    page = sim.call("mail_search", query="from:x", limit=200, offset=0)
    path = sim.save("top_senders.csv", table)  # .csv / .json / .md in the workdir
    sim.result(table)                          # the rows this run hands back

`sim.call` sends one JSON line to the parent on a pipe and reads one line
back. The parent proposes the call to Guardian like any other action and
answers `{ok, output, rows, ref, error}`. Without a parent bridge the
answer says so, and nothing runs.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
from pathlib import Path

WORKDIR = Path(os.environ.get("SIM_WORKDIR") or os.getcwd())
#: The workdir as Sim's own tools name it (`results/work/<job>`).
WORKDIR_REF = os.environ.get("SIM_WORKDIR_REF") or str(WORKDIR)
INPUTS = WORKDIR / "inputs"
_LAST = os.environ.get("SIM_LAST", "")
_RESULT = WORKDIR / ".sim" / "result.json"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$")

_bridge_in = None
_bridge_out = None
_db: sqlite3.Connection | None = None


def _open_bridge() -> None:
    global _bridge_in, _bridge_out
    spec = os.environ.get("SIM_BRIDGE", "")
    if not spec or _bridge_out is not None:
        return
    read_fd, write_fd = (int(part) for part in spec.split(","))
    _bridge_in = os.fdopen(read_fd, "rb")
    _bridge_out = os.fdopen(write_fd, "wb", buffering=0)


def _ref_id(ref: str) -> str:
    """`results/<id>.json`, `inputs/<id>.json`, `<id>.json` or `<id>` -> `<id>`."""
    text = str(ref or "").strip()
    if text.startswith("results/"):
        text = text[len("results/"):]
    if text.startswith("inputs/"):
        text = text[len("inputs/"):]
    if text.endswith(".json"):
        text = text[: -len(".json")]
    return text


def _available() -> list[str]:
    names = sorted(p.stem for p in INPUTS.glob("*.json")) if INPUTS.is_dir() else []
    saved = sorted(p.name for p in WORKDIR.iterdir()
                   if p.is_file() and p.suffix in (".csv", ".json", ".md") and not p.name.startswith("."))
    return names + saved


def _path_for(ref: str) -> Path:
    text = str(ref or "last").strip()
    if text == "last":
        if not _LAST:
            raise LookupError("no result in this job yet: pass inputs=[<id>] to run_analysis")
        text = _LAST
    ident = _ref_id(text)
    if _SAFE_NAME.match(ident) and (INPUTS / f"{ident}.json").is_file():
        return INPUTS / f"{ident}.json"
    name = Path(text).name
    if _SAFE_NAME.match(name) and (WORKDIR / name).is_file():
        return WORKDIR / name
    raise LookupError(f"no rows for {ref!r} in this job; it has: {', '.join(_available()) or 'nothing yet'}. "
                      "Name a result in run_analysis inputs=[...] to copy it in.")


def rows(ref: str = "last") -> list[dict]:
    """Every row of an input (`inputs/<id>.json`) or of a file this job saved."""
    path = _path_for(ref)
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        data = data["rows"]
    if not isinstance(data, list):
        raise ValueError(f"{ref!r} holds {type(data).__name__}, not rows")
    return [row if isinstance(row, dict) else {"value": row} for row in data]


def db() -> sqlite3.Connection:
    """`work.db` in the workdir. It persists between calls in this job;
    the run commits it when the program ends."""
    global _db
    if _db is None:
        _db = sqlite3.connect(str(WORKDIR / "work.db"))
    return _db


def call(tool: str, **args) -> dict:
    """Call one of Sim's read-only tools. Returns `{ok, output, rows, ref, error}`.

    Each call is its own action that Guardian decides. A refusal, a cap or
    a missing bridge comes back as `ok: False` with the reason in `error`;
    it is never raised, so check `ok`."""
    _open_bridge()
    if _bridge_out is None or _bridge_in is None:
        return {"ok": False, "output": "", "rows": [], "ref": "",
                "error": "the tool bridge is unavailable in this run; sim.call cannot reach a tool"}
    request = json.dumps({"op": "call", "tool": str(tool), "args": args}, default=str) + "\n"
    try:
        _bridge_out.write(request.encode("utf-8"))
        line = _bridge_in.readline()
    except OSError as exc:
        return {"ok": False, "output": "", "rows": [], "ref": "", "error": f"the tool bridge closed: {exc}"}
    if not line:
        return {"ok": False, "output": "", "rows": [], "ref": "", "error": "the tool bridge closed"}
    reply = json.loads(line.decode("utf-8"))
    reply.setdefault("rows", [])
    reply.setdefault("ref", "")
    reply.setdefault("output", "")
    reply.setdefault("error", "")
    return reply


def _table_md(data: list) -> str:
    keys: list = []
    for row in data:
        for key in (row if isinstance(row, dict) else {}):
            if key not in keys:
                keys.append(key)
    if not keys:
        return "\n".join(str(row) for row in data) + "\n"
    lines = ["| " + " | ".join(map(str, keys)) + " |", "|" + "---|" * len(keys)]
    for row in data:
        lines.append("| " + " | ".join(str(row.get(k, "")).replace("|", "\\|") for k in keys) + " |")
    return "\n".join(lines) + "\n"


def _csv_text(data) -> str:
    out = io.StringIO()
    if isinstance(data, list) and data and all(isinstance(r, dict) for r in data):
        keys: list = []
        for row in data:
            for key in row:
                if key not in keys:
                    keys.append(key)
        writer = csv.DictWriter(out, fieldnames=keys)
        writer.writeheader()
        writer.writerows(data)
    elif isinstance(data, list):
        writer = csv.writer(out)
        for row in data:
            writer.writerow(row if isinstance(row, (list, tuple)) else [row])
    else:
        out.write(str(data))
    return out.getvalue()


def save(name: str, rows_or_text) -> str:
    """Write a `.csv`, `.json` or `.md` file in the workdir; returns its ref
    (`results/work/<job>/<name>`), which the model can read or name later."""
    base = Path(str(name or "")).name
    stem, dot, ext = base.rpartition(".")
    if not dot or ext not in ("csv", "json", "md"):
        stem = base
        ext = "md" if isinstance(rows_or_text, str) else (
            "csv" if isinstance(rows_or_text, list) else "json")
    base = f"{stem}.{ext}"
    if not _SAFE_NAME.match(base) or base in ("work.db",):
        raise ValueError(f"save: {name!r} is not a plain file name (letters, digits, _ . -)")
    if ext == "json":
        text = json.dumps(rows_or_text, default=str, indent=1)
    elif ext == "csv":
        text = _csv_text(rows_or_text)
    else:
        text = rows_or_text if isinstance(rows_or_text, str) else _table_md(list(rows_or_text))
    (WORKDIR / base).write_text(text, encoding="utf-8")
    return f"{WORKDIR_REF}/{base}"


def result(data) -> None:
    """The rows this run hands back: stored in full like any tool's rows,
    with a ref the next `run_analysis` can take as an input."""
    if isinstance(data, dict):
        data = [data]
    data = list(data)
    _RESULT.write_text(json.dumps(data, default=str), encoding="utf-8")


def _close() -> None:
    """Called by the runner when the program ends: commit work.db."""
    global _db
    if _db is not None:
        try:
            _db.commit()
            _db.close()
        except sqlite3.Error:
            pass
        _db = None


__all__ = ["call", "db", "result", "rows", "save", "WORKDIR", "WORKDIR_REF", "INPUTS"]

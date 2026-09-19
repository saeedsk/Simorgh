"""Typed config is read as typed (2026-09-18 evaluation, B15).

Every package has a Config dataclass with the defaults. 127 sites read it
as `getattr(config, "key", fallback)` instead, and 11 of those fallbacks
contradicted the dataclass default -- so a key meant one thing when the
real Config arrived and another when a partial one did. Ten were aligned
on 2026-09-19; `shell` keeps a deliberately safer fallback (off).

Two rules, pinned:
- no fallback contradicts its dataclass default, except the allow-list;
- the number of `getattr(config, ...)` reads only goes down. Replace one
  with a plain attribute read when you touch its module, then lower
  `MAX_GETATTR_READS` here in the same commit.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
MAX_GETATTR_READS = 127

#: (file, key) -> why the fallback may differ from the default.
ALLOWED = {
    ("simorgh/execution/tools.py", "shell"): "a partial config means no shell: the safer reading",
}

_READ = re.compile(r"getattr\(\s*(self\._config|self\.config|config|cfg|self\._cfg|ctx\.config|self\._ctx\.config)"
                   r"\s*,\s*[\"'](\w+)[\"']\s*,\s*([^)]+?)\)")


def _defaults() -> dict[tuple[str, str], object]:
    out: dict[tuple[str, str], object] = {}
    for path in (ROOT / "simorgh").glob("*/config.py"):
        module = path.parent.name
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef) and "Config" in node.name:
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.value is not None:
                        try:
                            out[(module, item.target.id)] = ast.literal_eval(item.value)
                        except ValueError:
                            pass
    return out


def _reads():
    for path in (ROOT / "simorgh").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(errors="replace")
        for m in _READ.finditer(text):
            yield rel, path.relative_to(ROOT).parts[1], m.group(2), m.group(3).strip(), text[:m.start()].count("\n") + 1


def test_no_fallback_contradicts_its_default():
    defaults = _defaults()
    bad = []
    for rel, module, key, fallback, line in _reads():
        try:
            value = ast.literal_eval(fallback)
        except (ValueError, SyntaxError):
            continue
        if (module, key) in defaults and defaults[(module, key)] != value and (rel, key) not in ALLOWED:
            bad.append(f"{rel}:{line} {key}: fallback {value!r} vs default {defaults[(module, key)]!r}")
    assert not bad, "fallbacks that contradict the dataclass default:\n" + "\n".join(bad)


def test_getattr_reads_only_go_down():
    count = sum(1 for _ in _reads())
    assert count <= MAX_GETATTR_READS, (
        f"{count} getattr(config, ...) reads, more than {MAX_GETATTR_READS}: read the typed attribute instead")

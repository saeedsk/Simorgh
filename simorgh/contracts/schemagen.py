"""Generate the checked-in JSON Schema files from the registry.

    python -m simorgh.contracts.schemagen          # (re)write schema/*.json
    python -m simorgh.contracts.schemagen --check  # exit 1 if out of sync

The files are a *verified projection* of the declarations in
`messages/` (tests/simorgh/contracts/test_schemagen.py fails if they
drift), and they are what other tooling -- or a non-Python subsystem one
day -- can consume without importing this package.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import messages as _messages  # noqa: F401 -- populate the registry
from .registry import all_specs

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"
_DRAFT = "https://json-schema.org/draft/2020-12/schema"


def schema_for(type_name: str, spec) -> dict:
    return {
        "$schema": _DRAFT,
        "$id": f"https://simorgh.local/schema/{type_name}.v{spec.version}.json",
        "title": type_name,
        "description": spec.doc or f"Payload of `{type_name}` (catalog v1).",
        **spec.schema,
    }


def render_all() -> dict[str, str]:
    """{filename: text} for every catalog type, deterministic."""
    out = {}
    for type_name, spec in sorted(all_specs().items()):
        text = json.dumps(schema_for(type_name, spec), indent=2, sort_keys=True) + "\n"
        out[f"{type_name}.v{spec.version}.json"] = text
    return out


def write(directory: Path = SCHEMA_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    rendered = render_all()
    for stale in directory.glob("*.json"):
        if stale.name not in rendered:
            stale.unlink()
    for name, text in rendered.items():
        path = directory / name
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            written.append(path)
    return written


def check(directory: Path = SCHEMA_DIR) -> list[str]:
    """Names of files that are missing, stale, or unexpected."""
    rendered = render_all()
    problems = []
    existing = {p.name for p in directory.glob("*.json")} if directory.exists() else set()
    for name, text in rendered.items():
        path = directory / name
        if not path.exists():
            problems.append(f"missing: {name}")
        elif path.read_text(encoding="utf-8") != text:
            problems.append(f"stale: {name}")
    for name in sorted(existing - set(rendered)):
        problems.append(f"unexpected: {name}")
    return problems


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--check" in argv:
        problems = check()
        for p in problems:
            print(p)
        print(f"{len(problems)} problem(s)" if problems else f"{len(render_all())} schemas in sync")
        return 1 if problems else 0
    written = write()
    print(f"wrote {len(written)} file(s); {len(render_all())} schemas total in {SCHEMA_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Move a ledger between JSONL and SQLite, seqs preserved (stage 9 item 5).

    python tools/ledger_migrate.py to-sqlite [~/.simorgh/ledger]
    python tools/ledger_migrate.py to-jsonl  [~/.simorgh/ledger] [--out DIR]
    python tools/ledger_migrate.py check     [~/.simorgh/ledger]

`to-sqlite` writes `ledger.sqlite3` inside the data dir and leaves the
JSONL files in place; `to-jsonl` writes the JSONL layout (into `--out`,
default the data dir itself); `check` says whether the two agree.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simorgh.ledger.migrate import SQLITE_NAME, compare, jsonl_to_sqlite, sqlite_to_jsonl  # noqa: E402


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("to-sqlite", "to-jsonl", "check"))
    ap.add_argument("data_dir", nargs="?", default="~/.simorgh/ledger")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    root = Path(args.data_dir).expanduser()
    db = root / SQLITE_NAME
    if args.command == "to-sqlite":
        report = jsonl_to_sqlite(root, db)
    elif args.command == "to-jsonl":
        report = sqlite_to_jsonl(db, Path(args.out).expanduser() if args.out else root)
    else:
        problems = compare(root, db)
        print("agree" if not problems else "\n".join(problems))
        return 0 if not problems else 1
    print(json.dumps(report.as_dict(), indent=1))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

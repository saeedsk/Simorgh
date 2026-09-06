"""`simorgh migrate-v1`: thin over `simorgh.ledger.migrate_v1` (which owns
the actual v1 record shape and routing table -- docs/blueprint/
06-migration-from-v1.md section 5). This module's only job is to open a
Ledger, stream `read_v1_records` through `append`, and report counts;
idempotency is the Ledger's own (`idempotency_key="v1:<id>"`), so running
this twice against the same file appends nothing the second time.
"""

from __future__ import annotations

from pathlib import Path

from simorgh.ledger.client import LedgerClient
from simorgh.ledger.migrate_v1 import read_v1_records

DEFAULT_V1_MEMORY_PATH = Path("~/.simorgh/memory.jsonl").expanduser()


class MigrationReport:
    def __init__(self) -> None:
        self.read = 0
        self.appended = 0
        self.skipped_duplicate = 0
        self.by_stream: dict[str, int] = {}

    def note(self, stream: str, *, appended: bool) -> None:
        self.by_stream[stream] = self.by_stream.get(stream, 0) + 1
        if appended:
            self.appended += 1
        else:
            self.skipped_duplicate += 1

    def summary(self) -> str:
        lines = [f"read {self.read} v1 record(s): {self.appended} appended, "
                f"{self.skipped_duplicate} already present"]
        for stream, count in sorted(self.by_stream.items()):
            lines.append(f"  {stream}: {count}")
        return "\n".join(lines)


async def migrate(ledger: LedgerClient, path: Path = DEFAULT_V1_MEMORY_PATH) -> MigrationReport:
    report = MigrationReport()
    if not path.is_file():
        return report
    for event in read_v1_records(path):
        report.read += 1
        dedupes_before = ledger.counters.get("dedupes", 0)
        await ledger.append(event.stream, event)
        appended = ledger.counters.get("dedupes", 0) == dedupes_before
        report.note(event.stream, appended=appended)
    return report


__all__ = ["DEFAULT_V1_MEMORY_PATH", "MigrationReport", "migrate"]

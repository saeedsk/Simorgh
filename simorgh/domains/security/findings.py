"""The findings store: what is true, what was true, and what came back.

A check reports what it currently sees. This turns a stream of those
sightings into a history, which is where the useful sentences live:
"open for three weeks", "you fixed this and it is back", "you accepted
this and the acceptance has expired".

Two rules that are easy to get wrong and expensive to get wrong:

- **A finding the checks stop reporting is `fixed`, not deleted.** The
  record of having had the problem is most of what makes the next
  occurrence meaningful.
- **An acceptance expires.** "I know, it is fine" without an end date
  is how a finding becomes a permanent blind spot, which is the same as
  never having found it.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .api import ACCEPTANCE_DAYS, Finding, Status

_SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    fingerprint TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    asset TEXT NOT NULL,
    title TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    remediation TEXT NOT NULL DEFAULT '',
    discriminator TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open',
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    fixed_at REAL,
    accepted_at REAL,
    accepted_reason TEXT NOT NULL DEFAULT '',
    accepted_until REAL,
    times_seen INTEGER NOT NULL DEFAULT 1,
    times_regressed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS findings_status ON findings(status);
CREATE INDEX IF NOT EXISTS findings_severity ON findings(severity);
"""


class FindingStore:
    def __init__(self, path: Path | str, *, clock=time.time) -> None:
        self.path = Path(path)
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "FindingStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- writing -------------------------------------------------------------

    def record(self, findings, *, categories=None) -> dict:
        """Take a complete set of current sightings and reconcile.

        `categories` bounds what may be closed: a run of only the TLS
        checks must not mark every secrets finding fixed just because it
        did not look for any. Omitting it means "this was a full sweep".
        """
        now = self._clock()
        seen: set[str] = set()
        opened, regressed, updated = 0, 0, 0

        for finding in findings:
            fingerprint = finding.fingerprint
            seen.add(fingerprint)
            row = self._conn.execute(
                "SELECT * FROM findings WHERE fingerprint = ?", (fingerprint,)).fetchone()
            if row is None:
                with self._conn:
                    self._conn.execute(
                        "INSERT INTO findings(fingerprint, category, severity, asset, title, "
                        "evidence, remediation, discriminator, detail, status, first_seen, "
                        "last_seen, times_seen) VALUES (?,?,?,?,?,?,?,?,?,'open',?,?,1)",
                        (fingerprint, finding.category, finding.severity, finding.asset,
                         finding.title, finding.evidence, finding.remediation,
                         finding.discriminator, json.dumps(finding.detail), now, now))
                opened += 1
                continue

            status = row["status"]
            if status in ("fixed",):
                new_status = "regressed"
                regressed += 1
            elif status == "accepted" and row["accepted_until"] and row["accepted_until"] < now:
                # The acceptance ran out. Back to open rather than
                # quietly staying accepted forever.
                new_status = "open"
            else:
                new_status = status
                updated += 1
            with self._conn:
                self._conn.execute(
                    "UPDATE findings SET severity=?, title=?, evidence=?, remediation=?, "
                    "detail=?, status=?, last_seen=?, times_seen=times_seen+1, "
                    "times_regressed=times_regressed+? WHERE fingerprint=?",
                    (finding.severity, finding.title, finding.evidence, finding.remediation,
                     json.dumps(finding.detail), new_status, now,
                     1 if new_status == "regressed" else 0, fingerprint))

        closed = 0
        clause = "status IN ('open', 'regressed')"
        params: list = []
        if categories is not None:
            placeholders = ",".join("?" for _ in categories) or "''"
            clause += f" AND category IN ({placeholders})"
            params.extend(categories)
        for row in list(self._conn.execute(f"SELECT fingerprint FROM findings WHERE {clause}", params)):
            if row["fingerprint"] in seen:
                continue
            with self._conn:
                self._conn.execute(
                    "UPDATE findings SET status='fixed', fixed_at=? WHERE fingerprint=?",
                    (now, row["fingerprint"]))
            closed += 1

        return {"opened": opened, "regressed": regressed, "still_open": updated, "fixed": closed}

    def accept(self, fingerprint: str, reason: str, *, days: float = ACCEPTANCE_DAYS) -> bool:
        now = self._clock()
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE findings SET status='accepted', accepted_at=?, accepted_reason=?, "
                "accepted_until=? WHERE fingerprint=? AND status IN ('open','regressed')",
                (now, reason, now + days * 86400, fingerprint))
        return cursor.rowcount > 0

    # -- reading -------------------------------------------------------------

    def get(self, fingerprint: str):
        row = self._conn.execute(
            "SELECT * FROM findings WHERE fingerprint = ?", (fingerprint,)).fetchone()
        if row is None:
            # A prefix is what a person will actually type from a
            # rendered list.
            row = self._conn.execute(
                "SELECT * FROM findings WHERE fingerprint LIKE ? LIMIT 2",
                (fingerprint + "%",)).fetchone()
        return dict(row) if row else None

    def list(self, *, status: str = "", severity: str = "", asset: str = "",
             since: float = 0.0, limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM findings WHERE 1=1"
        params: list = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if severity:
            sql += " AND severity = ?"
            params.append(severity)
        if asset:
            sql += " AND asset LIKE ?"
            params.append(f"%{asset}%")
        if since:
            sql += " AND last_seen >= ?"
            params.append(since)
        sql += " ORDER BY last_seen DESC LIMIT ?"
        params.append(limit)
        return [dict(row) for row in self._conn.execute(sql, params)]

    def open_findings(self) -> list[Finding]:
        """What currently counts against the score. Expired acceptances
        are included: an acceptance that has run out is an open finding
        again, whatever the row still says."""
        now = self._clock()
        rows = self._conn.execute(
            "SELECT * FROM findings WHERE status IN ('open','regressed') "
            "OR (status='accepted' AND accepted_until IS NOT NULL AND accepted_until < ?)",
            (now,)).fetchall()
        return [_to_finding(row) for row in rows]

    def counts(self) -> dict:
        out = {row["status"]: int(row["n"]) for row in self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM findings GROUP BY status")}
        out["by_severity"] = {row["severity"]: int(row["n"]) for row in self._conn.execute(
            "SELECT severity, COUNT(*) AS n FROM findings "
            "WHERE status IN ('open','regressed') GROUP BY severity")}
        return out

    def expiring_acceptances(self, *, within_days: float = 14.0) -> list[dict]:
        now = self._clock()
        return [dict(row) for row in self._conn.execute(
            "SELECT * FROM findings WHERE status='accepted' AND accepted_until IS NOT NULL "
            "AND accepted_until < ?", (now + within_days * 86400,))]


def _to_finding(row) -> Finding:
    try:
        detail = json.loads(row["detail"] or "{}")
    except ValueError:
        detail = {}
    return Finding(category=row["category"], severity=row["severity"], asset=row["asset"],
                   title=row["title"], evidence=row["evidence"], remediation=row["remediation"],
                   discriminator=row["discriminator"], detail=detail)


__all__ = ["FindingStore"]

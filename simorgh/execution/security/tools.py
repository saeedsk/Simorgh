"""`sec_self`, `sec_posture`, `sec_findings`, `sec_show`, `sec_accept`.

All read-only or reversible, all local, none of them touching a network
Sim does not own. `sec_scan exposure`, `sec_fix` and the CVE lookups are
later steps of the design and are deliberately absent rather than
stubbed -- a tool that exists and does nothing is worse than one that
does not exist, because the model spends a step finding out.

Reading another subsystem's configuration is done by reading
`simorgh.toml`, not by importing anything: a subsystem may not import
another's internals, and a security audit reading the config file is
the right shape anyway -- it sees what is actually written down rather
than what some object happened to be constructed with.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from simorgh.contracts.protocols import ToolContext, ToolResult

from .api import Finding, SEVERITIES, score, top_reasons
from .findings import FindingStore
from .selfcheck import (
    check_api_exposure,
    check_auto_approve,
    check_env_secrets,
    check_file_modes,
    check_ledger_size,
    check_listening_ports,
    check_secrets_in,
)

#: Everything `sec_self` can produce. Passed to `record()` so a self
#: check never marks a TLS or CVE finding fixed just because it did not
#: look for one.
SELF_CATEGORIES = ("api_exposure", "auto_approve", "file_permissions", "secret_in_workspace",
                   "ledger_growth", "listening_port", "env_secrets")


def _load_toml(path: Path) -> dict:
    try:
        import tomllib

        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except (OSError, ValueError, ImportError):
        return {}


class _SecurityTool:
    def __init__(self, config, *, store=None, secrets=None, env=None, clock=time.time,
                 lsof_runner=None) -> None:
        self._config = config
        self._store_override = store
        self._secrets = secrets
        self._env = env if env is not None else os.environ
        self._clock = clock
        self._lsof_runner = lsof_runner

    def _repo_root(self) -> Path:
        return Path(getattr(self._config, "repo_root", "."))

    def _store_path(self) -> Path:
        raw = getattr(self._config, "security_findings_path", "workspace/security/findings.db")
        path = Path(raw).expanduser()
        return path if path.is_absolute() else self._repo_root() / path

    def _open(self) -> FindingStore:
        if self._store_override is not None:
            return self._store_override
        return FindingStore(self._store_path(), clock=self._clock)

    def _close(self, store: FindingStore) -> None:
        if self._store_override is None:
            store.close()

    def _config_file(self) -> dict:
        raw = getattr(self._config, "security_config_path", "")
        if raw:
            return _load_toml(Path(raw).expanduser())
        for candidate in (self._repo_root() / "simorgh.toml",
                          Path.home() / ".simorgh" / "simorgh.toml"):
            if candidate.exists():
                return _load_toml(candidate)
        return {}

    def _data_dir(self) -> Path:
        toml = self._config_file()
        raw = str((toml.get("runtime") or {}).get("data_dir") or "~/.simorgh")
        return Path(raw).expanduser()


class SecSelfTool(_SecurityTool):
    name = "sec_self"
    description = (
        "Check Sim's own security posture: whether its API is exposed, whether irreversible "
        "actions run unattended, whether any credential has been written into its working "
        "files, and what this machine is listening on. Entirely local -- no network."
    )
    read_only = False          # it writes findings; it changes nothing about the system
    reversibility = "reversible"
    args_schema = {"type": "object", "properties": {"scan_secrets": {"type": "boolean"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        import asyncio

        findings = await asyncio.to_thread(self._collect, bool(args.get("scan_secrets", True)))
        store = self._open()
        try:
            outcome = store.record(findings, categories=SELF_CATEGORIES)
            open_now = store.open_findings()
        finally:
            self._close(store)

        current = score(open_now, getattr(self._config, "security_posture_weights", None))
        lines = [f"posture {current}/100 from {len(open_now)} open finding(s)"]
        by_severity: dict[str, list[Finding]] = {}
        for finding in findings:
            by_severity.setdefault(finding.severity, []).append(finding)
        for severity in reversed(SEVERITIES):
            for finding in by_severity.get(severity, []):
                lines.append("  " + finding.render().replace("\n", "\n  "))
                if finding.remediation:
                    lines.append(f"      -> {finding.remediation}")
        if not findings:
            lines.append("  nothing to report -- everything checked came back clean")
        changed = [f"{n} {label}" for label, n in
                   (("new", outcome["opened"]), ("regressed", outcome["regressed"]),
                    ("now fixed", outcome["fixed"])) if n]
        if changed:
            lines.append("since the last check: " + ", ".join(changed))
        return ToolResult(
            ok=True, output="\n".join(lines),
            side_effects=(f"{len(findings)} security finding(s) recorded",),
            metadata={"score": current, "open": len(open_now), **outcome,
                      "rows": [{"fingerprint": f.fingerprint, "category": f.category,
                                "severity": f.severity, "asset": f.asset, "title": f.title}
                               for f in findings]})

    def _collect(self, scan_secrets: bool) -> list[Finding]:
        toml = self._config_file()
        interface = toml.get("interface") or {}
        guardian = toml.get("guardian") or {}
        data_dir = self._data_dir()

        has_token = bool((self._env.get("SIM_API_TOKEN") or "").strip())
        if not has_token and self._secrets is not None:
            try:
                has_token = bool(self._secrets.get("SIM_API_TOKEN"))
            except Exception:  # noqa: BLE001
                has_token = False

        env_override = ""
        auto_approve = bool(guardian.get("auto_approve", False))
        raw_env = (self._env.get("SIMORGH_GUARDIAN_AUTO_APPROVE") or "").strip()
        if raw_env:
            auto_approve = raw_env not in ("0", "false", "no", "")
            env_override = "SIMORGH_GUARDIAN_AUTO_APPROVE"

        findings: list[Finding] = []
        findings += check_api_exposure(
            host=str(interface.get("http_host", "127.0.0.1")),
            port=int(interface.get("http_port", 8765) or 8765),
            has_token=has_token)
        findings += check_auto_approve(
            auto_approve=auto_approve,
            always_human=tuple(guardian.get("always_human") or ()),
            env_override=env_override)
        findings += check_file_modes([
            data_dir / "vault.age", data_dir / "vault.key", data_dir / "secrets.toml",
            (toml.get("secrets") or {}).get("file", "").replace("${data_dir}", str(data_dir)),
        ])
        findings += check_ledger_size(data_dir / "ledger")
        findings += check_env_secrets(self._env)
        findings += check_listening_ports(runner=self._lsof_runner)
        if scan_secrets:
            roots = [self._repo_root() / part
                     for part in getattr(self._config, "security_secrets_paths",
                                         ("workspace", "results"))]
            findings += check_secrets_in(roots)
        # One entry per problem, whatever any individual check did. The
        # store would dedupe on write anyway; without this the *printed*
        # report repeats itself, and a report that says the same thing
        # twice reads as a broken report.
        unique: dict[str, Finding] = {}
        for finding in findings:
            unique.setdefault(finding.fingerprint, finding)
        return list(unique.values())


class SecPostureTool(_SecurityTool):
    name = "sec_posture"
    description = (
        "The current security score out of 100, what is dragging it down, and what changed. "
        "Reads what the last check found; run sec_self to refresh it."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "properties": {}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        store = self._open()
        try:
            open_now = store.open_findings()
            counts = store.counts()
            expiring = store.expiring_acceptances()
        finally:
            self._close(store)

        # `counts()` always carries a `by_severity` key, so a plain
        # truthiness test on it never fired -- and a store that had
        # never been written reported 100/100, which is a clean bill of
        # health for a check that has not run. That is precisely the
        # "succeeds while saying nothing true" failure.
        recorded = sum(n for status, n in counts.items() if status != "by_severity")
        if not recorded:
            return ToolResult(
                ok=True,
                output="nothing has been checked yet -- run SEC_SELF to look at Sim's own posture.",
                metadata={"score": None, "open": 0})

        weights = getattr(self._config, "security_posture_weights", None)
        current = score(open_now, weights)
        lines = [f"posture {current}/100"]
        reasons = top_reasons(open_now)
        if reasons:
            lines.append("worst first:")
            lines.extend(f"  - {reason}" for reason in reasons)
        else:
            lines.append("no open findings")
        summary = ", ".join(f"{n} {status}" for status, n in sorted(counts.items())
                            if status != "by_severity")
        if summary:
            lines.append(summary)
        for row in expiring:
            lines.append(f"  acceptance expiring: {row['title']} ({row['accepted_reason']})")
        return ToolResult(ok=True, output="\n".join(lines),
                          metadata={"score": current, "open": len(open_now), **{
                              k: v for k, v in counts.items() if k != "by_severity"},
                              "by_severity": counts.get("by_severity", {})})


class SecFindingsTool(_SecurityTool):
    name = "sec_findings"
    description = "List security findings, filtered by severity, status or asset."
    read_only = True
    reversibility = "read_only"
    args_schema = {
        "type": "object",
        "properties": {
            "severity": {"type": "string", "enum": list(SEVERITIES)},
            "status": {"type": "string", "enum": ["open", "fixed", "accepted", "regressed"]},
            "asset": {"type": "string"}, "limit": {"type": "integer"},
        },
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        store = self._open()
        try:
            rows = store.list(status=str(args.get("status") or ""),
                              severity=str(args.get("severity") or ""),
                              asset=str(args.get("asset") or ""),
                              limit=max(1, min(int(args.get("limit") or 50), 200)))
        finally:
            self._close(store)
        if not rows:
            return ToolResult(ok=True, output="no findings match", metadata={"rows": []})
        lines = [f"  {row['fingerprint']}  [{row['severity']}/{row['status']}]  {row['title']}"
                 f"  ({row['asset']})" for row in rows]
        return ToolResult(
            ok=True,
            output=f"{len(rows)} finding(s). SEC_SHOW with an id for the evidence:\n"
                   + "\n".join(lines),
            metadata={"rows": [{k: v for k, v in row.items() if k != "detail"} for row in rows]})


class SecShowTool(_SecurityTool):
    name = "sec_show"
    description = "The full evidence and remediation steps for one finding, by its id."
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "required": ["finding"],
                   "properties": {"finding": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        fingerprint = str(args.get("finding") or "").strip()
        if not fingerprint:
            return ToolResult(ok=False, error="refused: no finding id given")
        store = self._open()
        try:
            row = store.get(fingerprint)
        finally:
            self._close(store)
        if row is None:
            return ToolResult(ok=False, error=f"no finding {fingerprint!r} (see SEC_FINDINGS)")

        first = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["first_seen"]))
        last = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["last_seen"]))
        lines = [
            f"{row['fingerprint']}  [{row['severity']}/{row['status']}]",
            row["title"],
            f"asset: {row['asset']}",
            f"first seen {first}, last seen {last}, seen {row['times_seen']} time(s)",
        ]
        if row["times_regressed"]:
            lines.append(f"came back {row['times_regressed']} time(s) after being fixed")
        if row["evidence"]:
            lines.append(f"\nevidence:\n  {row['evidence']}")
        if row["remediation"]:
            lines.append(f"\nwhat to do:\n  {row['remediation']}")
        if row["status"] == "accepted":
            until = time.strftime("%Y-%m-%d", time.localtime(row["accepted_until"] or 0))
            lines.append(f"\naccepted until {until}: {row['accepted_reason']}")
        return ToolResult(ok=True, output="\n".join(lines),
                          metadata={k: v for k, v in row.items() if k != "detail"})


class SecAcceptTool(_SecurityTool):
    name = "sec_accept"
    description = (
        "Record that a finding is a known, accepted risk, with the reason. It stops counting "
        "against the score until the acceptance expires."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {
        "type": "object", "required": ["finding", "reason"],
        "properties": {"finding": {"type": "string"}, "reason": {"type": "string"},
                       "days": {"type": "number"}},
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        fingerprint = str(args.get("finding") or "").strip()
        reason = " ".join(str(args.get("reason") or "").split())
        if not fingerprint:
            return ToolResult(ok=False, error="refused: no finding id given")
        if not reason:
            # An acceptance with no reason is indistinguishable from
            # forgetting about it, and it is the reason that lets the
            # next person judge whether it still holds.
            return ToolResult(ok=False,
                              error="refused: an accepted risk needs a reason -- it is what makes "
                                    "the acceptance reviewable later")
        days = float(args.get("days") or 90.0)
        store = self._open()
        try:
            row = store.get(fingerprint)
            if row is None:
                return ToolResult(ok=False, error=f"no finding {fingerprint!r} (see SEC_FINDINGS)")
            accepted = store.accept(row["fingerprint"], reason, days=days)
        finally:
            self._close(store)
        if not accepted:
            return ToolResult(ok=False,
                              error=f"{row['fingerprint']} is {row['status']}, not open -- "
                                    "only an open finding can be accepted")
        return ToolResult(
            ok=True,
            output=f"accepted for {days:.0f} days: {row['title']}\nreason: {reason}\n"
                   f"It will reappear when the acceptance expires -- an accepted risk with no end "
                   f"date is a blind spot.",
            side_effects=(f"finding {row['fingerprint']} accepted",),
            metadata={"fingerprint": row["fingerprint"], "days": days})


def security_tools(config, **kwargs) -> list:
    return [SecSelfTool(config, **kwargs), SecPostureTool(config, **kwargs),
            SecFindingsTool(config, **kwargs), SecShowTool(config, **kwargs),
            SecAcceptTool(config, **kwargs)]


__all__ = ["SELF_CATEGORIES", "SecAcceptTool", "SecFindingsTool", "SecPostureTool", "SecSelfTool",
           "SecShowTool", "security_tools"]

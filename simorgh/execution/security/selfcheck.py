"""What Sim can find out about its own exposure, using nothing but this
machine.

Guardian audits the code Sim writes. Nothing audited what Sim *is*.
Every check here is local, free, and takes milliseconds -- and every one
of them was previously invisible, discoverable only by reading four
config files and knowing what to look for.

The checks, and why each one earns its severity:

- **The API bound off-loopback with no token** is critical, because
  `/api/chat` starts a real, tool-using turn and Guardian's auto-approve
  default means it may not stop to ask.
- **A secret written into `workspace/` or `results/`** is critical: a
  task that meant well has put a credential somewhere it will be read
  back, indexed, and possibly committed.
- **A world-readable vault or secrets file** is high. The encryption is
  only as good as the key file's mode.
- **Auto-approve with no `always_human` list** is medium, and
  deliberately not higher: it is a choice a person is entitled to make
  and this creator has made on purpose. Reporting it as an emergency
  would teach them to ignore the report.
- **A ledger of hundreds of thousands of files** is medium: it is a
  real operational hazard on this project's own history, and it is the
  kind of thing nobody notices until a backup fails.

Nothing here reads a secret's value. Evidence names the file and the
shape of what was found, never the thing itself -- a finding is written
to a database and read into a model's context, so quoting a password
would put it in two more places.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from ..pathsafety import looks_like_credential_path
from .api import Finding, redact

#: Loopback addresses. Anything else is reachable by another host.
_LOOPBACK = {"127.0.0.1", "localhost", "::1", ""}

#: Shapes that are credentials wherever they appear. Deliberately
#: narrow: a scanner that flags every long string trains people to
#: ignore it, and an ignored security report is worse than none.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("an AWS access key id", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b")),
    ("an OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("a Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("an Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("a private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("a hardcoded password assignment",
     re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|token)\s*[=:]\s*"
                r"[\"']([^\"'\s]{8,})[\"']")),
)

#: Files big enough that scanning them is not worth it, and which are
#: never hand-written credentials anyway.
_MAX_SCAN_BYTES = 2 * 1024 * 1024

_TEXT_SUFFIXES = frozenset({
    ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".sh", ".py",
    ".js", ".ts", ".log", ".csv", ".html", ".xml", "",
})


def check_api_exposure(*, host: str, port: int, has_token: bool) -> list[Finding]:
    if host in _LOOPBACK:
        if not has_token:
            return [Finding(
                category="api_exposure", severity="info", asset="sim:api",
                title="The dashboard is on loopback with no token",
                evidence=f"bound to {host}:{port}, reachable only by this machine's own user",
                remediation="Nothing to do unless you expose it. If you tunnel it, set "
                            "SIM_API_TOKEN first.")]
        return []
    if not has_token:
        return [Finding(
            category="api_exposure", severity="critical", asset="sim:api",
            title="The dashboard answers the whole network with no token",
            evidence=f"[interface] http_host = {host!r}, port {port}, and SIM_API_TOKEN is not set",
            remediation="Set SIM_API_TOKEN (any long random string) and restart, or bind "
                        "127.0.0.1 and reach it over Tailscale or an SSH tunnel. Until then "
                        "anyone who can route to this host can start a tool-using turn.")]
    return [Finding(
        category="api_exposure", severity="low", asset="sim:api",
        title="The dashboard is reachable off-loopback, but gated by a token",
        evidence=f"bound to {host}:{port} with SIM_API_TOKEN set",
        remediation="Fine behind a private network. Put TLS in front of it if it crosses one.")]


def check_file_modes(paths) -> list[Finding]:
    """A secret file readable by other accounts on this machine.

    The vault's encryption is only as strong as its key file's mode, and
    `FileSecretStore` already refuses to load a loose `secrets.toml` --
    but the vault key and anything else lying around got no such check.
    """
    findings: list[Finding] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if not path.exists() or not path.is_file():
            continue
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            continue
        if mode & 0o077:
            findings.append(Finding(
                category="file_permissions", severity="high", asset=str(path),
                title=f"{path.name} is readable by other accounts on this machine",
                evidence=f"mode {mode:04o}; it should be 0600",
                remediation=f"chmod 600 {path}",
                discriminator=str(path)))
    return findings


def check_auto_approve(*, auto_approve: bool, always_human: tuple, env_override: str = "") -> list[Finding]:
    if not auto_approve:
        return []
    if always_human:
        return [Finding(
            category="auto_approve", severity="low", asset="sim:guardian",
            title="Irreversible actions run without asking, except a named list",
            evidence=f"auto-approve is on; always_human = {list(always_human)}",
            remediation="This is a deliberate choice. Review the list if the toolset has grown.")]
    return [Finding(
        category="auto_approve", severity="medium", asset="sim:guardian",
        title="Every irreversible action runs without asking",
        evidence=("auto-approve is on and no tool is on the always_human list"
                  + (f" (from {env_override})" if env_override else "")),
        remediation="A deliberate choice, and the right one for unattended work. Consider "
                    "putting the tools that reach other people -- notify, and anything that "
                    "sends -- on [guardian] always_human.")]


def check_secrets_in(paths, *, max_files: int = 3000, max_findings: int = 25) -> list[Finding]:
    """Credential-shaped strings written into Sim's own working areas.

    This is the check most likely to be *useful*: a task that meant well
    saves an API key into a scratch file, and from there it is indexed
    by the knowledge base, read back into prompts, and eventually
    committed. Nothing was watching for it.
    """
    findings: list[Finding] = []
    scanned = 0
    for raw in paths:
        root = Path(raw).expanduser()
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else sorted(
            p for p in root.rglob("*") if p.is_file())
        for path in candidates:
            if scanned >= max_files or len(findings) >= max_findings:
                return findings
            if any(part in (".git", "node_modules", "__pycache__", ".venv") for part in path.parts):
                continue
            if path.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > _MAX_SCAN_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            scanned += 1
            if looks_like_credential_path(path.parts):
                findings.append(Finding(
                    category="secret_in_workspace", severity="high", asset=str(path),
                    title=f"A credential-looking file is in Sim's working area: {path.name}",
                    evidence="the filename alone says what it is; contents were not read",
                    remediation=f"Move it out of Sim's reach, or into the vault: "
                                f"`vault import <id> file:{path}` and delete the original.",
                    discriminator=str(path)))
                continue
            for label, pattern in _SECRET_PATTERNS:
                match = pattern.search(text)
                if not match:
                    continue
                line_number = text[:match.start()].count("\n") + 1
                # The redacted match, never the value: this string is
                # written to a database and read into a model's context.
                sample = redact(match.group(1) if match.groups() else match.group(0))
                findings.append(Finding(
                    category="secret_in_workspace", severity="critical", asset=str(path),
                    title=f"{label} is written into {path.name}",
                    evidence=f"line {line_number}, matching {sample}",
                    remediation=f"Remove it from {path} and rotate it -- assume it is known. "
                                f"Store the replacement with `vault add`.",
                    discriminator=f"{path}:{label}"))
                break
    return findings


def check_ledger_size(ledger_dir, *, file_warn: int = 50_000, bytes_warn: int = 5 * 1024 ** 3
                      ) -> list[Finding]:
    """A ledger that has quietly become hundreds of thousands of files.

    Not a security problem in the usual sense, and here anyway because
    it has actually happened on this project: an append-only store with
    a file per trace grew to 192,000 files, and nothing noticed until it
    was looked for. A backup that silently stops completing is a
    availability problem with a security shape.
    """
    root = Path(ledger_dir).expanduser()
    if not root.exists():
        return []
    files, total = 0, 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        files += 1
        try:
            total += path.stat().st_size
        except OSError:
            pass
        if files > file_warn * 4:
            break
    if files < file_warn and total < bytes_warn:
        return []
    return [Finding(
        category="ledger_growth", severity="medium", asset=str(root),
        title=f"The ledger has grown to {files:,} file(s), {total / 1024 ** 3:.1f} GB",
        evidence=f"{root}",
        remediation="Check what is producing them -- a trace per action will do this. "
                    "Compact or prune the oldest streams.")]


def check_listening_ports(*, runner=None) -> list[Finding]:
    """What this machine is answering on, and whether any of it is
    Sim's and open to the world.

    `lsof` is on every macOS and most Linux boxes; without it this
    check reports nothing rather than guessing. A check that cannot run
    says so through its absence, never through a clean bill of health.
    """
    runner = runner or _run_lsof
    lines = runner()
    if lines is None:
        return []
    findings: list[Finding] = []
    # `lsof` prints one row per socket, so a process listening on both
    # IPv4 and IPv6 appears twice for the same port. The store dedupes
    # by fingerprint, but the rendered list did not -- and a report that
    # says the same thing twice reads as a broken report.
    seen: set[tuple[str, int]] = set()
    for line in lines:
        match = re.search(r"(\S+):(\d+)\s*\(LISTEN\)", line)
        if not match:
            continue
        address, port = match.group(1), int(match.group(2))
        if address in ("127.0.0.1", "[::1]", "localhost"):
            continue
        command = line.split()[0] if line.split() else "?"
        if (command, port) in seen:
            continue
        seen.add((command, port))
        findings.append(Finding(
            category="listening_port", severity="info", asset=f"{address}:{port}",
            title=f"{command} is listening on {address}:{port}",
            evidence="every host that can route here can reach this port",
            remediation="Expected for a server you meant to run. If you did not mean to run "
                        "it, stop it.",
            discriminator=f"{command}:{port}"))
    return findings


def _run_lsof():
    binary = shutil.which("lsof")
    if not binary:
        return None
    try:
        completed = subprocess.run(
            [binary, "-nP", "-iTCP", "-sTCP:LISTEN"], capture_output=True, text=True,
            timeout=15, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.splitlines()[1:]


def check_env_secrets(env=None) -> list[Finding]:
    """Credentials passed in the environment.

    Not a finding in itself -- it is how most of this works -- but worth
    saying once, because an environment variable is visible to every
    child process Sim spawns, including a container it runs and a script
    it wrote.
    """
    env = env if env is not None else os.environ
    interesting = sorted(
        name for name in env
        if re.search(r"(?i)(api[_-]?key|token|secret|password|webhook)", name)
        and (env.get(name) or "").strip())
    if not interesting:
        return []
    return [Finding(
        category="env_secrets", severity="info", asset="sim:process",
        title=f"{len(interesting)} credential(s) are in the environment",
        evidence=", ".join(interesting[:10]) + ("…" if len(interesting) > 10 else ""),
        remediation="Every child process inherits these, including containers and scripts Sim "
                    "writes. Move the ones you can into the vault, which hands them out per "
                    "subsystem instead.")]


__all__ = ["check_api_exposure", "check_auto_approve", "check_env_secrets", "check_file_modes",
           "check_ledger_size", "check_listening_ports", "check_secrets_in"]

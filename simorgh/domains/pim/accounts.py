"""Turning `[execution] pim_accounts` into live connectors.

The credential never travels in config. An account row names a
`cred_id`; the value is fetched from the scoped secret store, which
resolves `vault:<id>:password` through the encrypted vault
(kernel/vault.py) and falls back to the environment. So the TOML a
person keeps in git holds a hostname and a username and nothing worth
stealing.
"""

from __future__ import annotations

from .api import Account
from .connectors.caldav import CalDavConnector
from .connectors.imap import ImapConnector


def parse_accounts(rows) -> list[Account]:
    out: list[Account] = []
    for row in rows or ():
        if isinstance(row, Account):
            out.append(row)
            continue
        data = dict(row)
        name = str(data.get("name") or "").strip()
        kind = str(data.get("kind") or "").strip().lower()
        if not name or kind not in ("imap", "caldav"):
            continue
        out.append(Account(
            name=name, kind=kind, url=str(data.get("url") or ""),
            username=str(data.get("username") or ""),
            cred_id=str(data.get("cred_id") or f"{kind}:{name}"),
            privacy=str(data.get("privacy") or "personal"),
            calendars=tuple(data.get("calendars") or ()),
            folders=tuple(data.get("folders") or ()),
        ))
    return out


def secret_for(account: Account, secrets=None, env=None) -> str:
    """The account's password, from the vault or the environment.

    Order matters: the vault first, because that is where a rotated
    credential lands, and the env fallback exists so somebody can try
    this out before setting the vault up at all.
    """
    import os

    env = env if env is not None else os.environ
    names = [
        f"vault:{account.cred_id}:password",
        f"vault:{account.cred_id}:value",
        account.cred_id,
    ]
    if secrets is not None:
        for name in names:
            try:
                value = secrets.get(name)
            except Exception:  # noqa: BLE001 -- a scoped store refusing is not an error here
                value = None
            if value:
                return str(value)
    fallback = f"PIM_{account.name.upper().replace('-', '_')}_PASSWORD"
    return str(env.get(fallback) or "")


def build_connector(account: Account, *, secrets=None, env=None, timeout_s: float = 20.0):
    """Never raises: a broken account row becomes a connector whose
    `probe()` explains itself. That is the first rule in
    `contracts/connector.py`, and it is what keeps one bad line in
    `simorgh.toml` from stopping Sim booting."""
    password = secret_for(account, secrets=secrets, env=env)
    if account.kind == "imap":
        host, _, port = account.url.partition(":")
        return ImapConnector(
            name=account.name, host=host or account.url, username=account.username,
            password=password, port=int(port) if port.isdigit() else 993,
            folders=account.folders, timeout_s=timeout_s)
    return CalDavConnector(
        name=account.name, url=account.url, username=account.username, password=password,
        calendars=account.calendars, timeout_s=timeout_s)


def build_all(rows, *, secrets=None, env=None, timeout_s: float = 20.0) -> dict:
    return {account.name: build_connector(account, secrets=secrets, env=env, timeout_s=timeout_s)
            for account in parse_accounts(rows)}


__all__ = ["build_all", "build_connector", "parse_accounts", "secret_for"]

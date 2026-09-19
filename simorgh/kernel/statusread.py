"""`simorgh status` without booting anything (B17, stage 1 item 9).

The old subcommand built a second `Kernel` against the live data dir:
it could never see the running instance (a fresh Kernel answers about
itself), ignored its own `--timeout`, and appended `config:effective`
and `system.state` events to the live ledger every time someone asked.

This asks in two places, in order, and writes nowhere:

1. the running instance's HTTP API (`GET /api/status`), at the host and
   port the Interface binds (`[interface] http_host/http_port`), with the
   `SIM_API_TOKEN` secret when one is set -- without it a token-gated
   server answers only the public liveness keys;
2. if nothing answers, the ledger files under the data dir, opened
   read-only: the last `system.state` event on the `system` stream and
   the last `metrics:history` sample. The Ledger client is never
   started (a `JsonlBackend.start()` rewrites `index.json`; sqlite's
   creates its schema), so the files are read directly.

Every result says which of the two it came from (`source`).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

from .config import LoadedConfig

SYSTEM_STREAM = "system"
STATE_EVENT_TYPE = "system.state"
HISTORY_STREAM = "metrics:history"  # same name as metrics.HISTORY_STREAM; not imported to keep this light
_WILDCARD_HOSTS = ("0.0.0.0", "::", "")


class LiveUnavailable(Exception):
    """Nothing usable answered at `/api/status`. The message says why."""


def status_url(config: LoadedConfig) -> str:
    """Where the running instance's `/api/status` is, read the way the
    Interface reads it (`interface.config.Config.from_mapping`)."""
    from simorgh.interface.config import Config as InterfaceConfig

    iface = InterfaceConfig.from_mapping(config.section("interface"))
    host = iface.http_host.strip()
    if host in _WILDCARD_HOSTS:
        host = "127.0.0.1"  # bound to every address; loopback is one of them
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{iface.http_port}/api/status"


def api_token(config: LoadedConfig) -> str:
    """`SIM_API_TOKEN` from the same secret chain the Kernel hands the
    Interface (env, then `${data_dir}/secrets.toml`). A broken secrets
    file is not a reason to fail a status read: no token, and the
    server answers the public keys."""
    from .secrets import build_secret_store

    try:
        return (build_secret_store(config, config.runtime.data_dir).get("SIM_API_TOKEN") or "").strip()
    except Exception:  # noqa: BLE001 -- see docstring
        return ""


def fetch_live(url: str, *, token: str = "", timeout: float = 2.0) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- local API
            body = response.read(2_000_000)
    except urllib.error.HTTPError as exc:
        raise LiveUnavailable(f"{url} answered HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise LiveUnavailable(f"nothing answered at {url} within {timeout:g}s ({reason})") from None
    try:
        payload = json.loads(body)
    except ValueError:
        raise LiveUnavailable(f"{url} answered with something that is not JSON") from None
    if not isinstance(payload, dict) or "state" not in payload:
        raise LiveUnavailable(f"{url} answered, but not with a Simorgh status")
    return payload


# --------------------------------------------------------------- the ledger
def _ledger_section(config: LoadedConfig) -> tuple[str, Path]:
    from simorgh.ledger.config import Config as LedgerConfig

    section = dict(config.section("ledger"))
    section.setdefault("data_dir", str(config.runtime.data_dir / "ledger"))
    cfg = LedgerConfig.from_mapping(section)
    return cfg.backend, cfg.data_path


def _last_matching_line(path: Path, want_type: str | None) -> dict | None:
    """The last well-formed event in a JSONL stream file (of `want_type`
    if given), read backwards in blocks so a large stream costs only its
    tail. Opened read-only; nothing is truncated or repaired."""
    try:
        handle = open(path, "rb")  # noqa: SIM115 -- closed below
    except FileNotFoundError:
        return None
    with handle:
        handle.seek(0, os.SEEK_END)
        pos = handle.tell()
        tail = b""
        block = 64 * 1024
        while True:
            lines = tail.split(b"\n")
            # The first piece may be a partial line unless we reached the start.
            complete = lines if pos == 0 else lines[1:]
            for raw in reversed(complete):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue  # a torn trailing write or a corrupt line; the one before still counts
                if isinstance(event, dict) and (want_type is None or event.get("type") == want_type):
                    return event
            if pos == 0:
                return None
            tail = lines[0]
            step = min(block, pos)
            pos -= step
            handle.seek(pos)
            tail = handle.read(step) + tail


def _last_sqlite_event(db: Path, stream: str, want_type: str | None) -> dict | None:
    if not db.exists():
        return None
    # `mode=ro` alone is not read-only on disk: opening a WAL database
    # creates `-wal` and `-shm` beside it (found by this module's test).
    # With no `-wal` file the last writer closed cleanly and the file is
    # the whole truth, so `immutable=1` reads it touching nothing. A
    # leftover `-wal` (a crash, or a writer we could not reach) holds
    # committed events not yet in the main file: then `mode=ro`, which
    # reuses the files that are already there.
    wal = db.with_name(db.name + "-wal")
    flags = "mode=ro" if wal.exists() else "mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(f"{db.as_uri()}?{flags}", uri=True)
    except sqlite3.Error:
        return None
    try:
        sql = "SELECT type, ts, payload, seq FROM events WHERE stream = ?"
        args: list = [stream]
        if want_type is not None:
            sql += " AND type = ?"
            args.append(want_type)
        row = conn.execute(sql + " ORDER BY seq DESC LIMIT 1", args).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if row is None:
        return None
    try:
        payload = json.loads(row[2])
    except ValueError:
        payload = {}
    return {"stream": stream, "type": row[0], "ts": row[1], "payload": payload, "seq": row[3]}


def last_event(config: LoadedConfig, stream: str, want_type: str | None = None) -> dict | None:
    backend, root = _ledger_section(config)
    if backend == "jsonl":
        from simorgh.ledger.streams import escape

        return _last_matching_line(root / "streams" / f"{escape(stream)}.jsonl", want_type)
    if backend == "sqlite":
        return _last_sqlite_event(root / "ledger.sqlite3", stream, want_type)
    raise LookupError(f"the {backend!r} ledger backend cannot be read without starting it")


def _iso(ts: float | None) -> str:
    if ts is None:
        return "unknown"
    return _dt.datetime.fromtimestamp(float(ts)).astimezone().isoformat(timespec="seconds")


def from_ledger(config: LoadedConfig, *, why_not_live: str = "") -> dict:
    """The last recorded state, shaped like `StatusServer.snapshot()` as
    far as the ledger records it: `state` and `autonomous_paused` from
    the last `system.state`, `mode` from the config, `metrics` from the
    last `metrics:history` sample. `run_id`, `uptime_seconds` and
    `subsystems` are not recorded anywhere and are left out rather than
    invented."""
    state_event = last_event(config, SYSTEM_STREAM, STATE_EVENT_TYPE)
    if state_event is None:
        backend, root = _ledger_section(config)
        return {"source": "ledger", "state": "unknown", "mode": config.runtime.mode,
                "detail": f"no system.state recorded in the {backend} ledger at {root}",
                **({"live_error": why_not_live} if why_not_live else {})}
    payload = state_event.get("payload") or {}
    as_of = state_event.get("ts")
    snapshot: dict = {
        "source": "ledger",
        "as_of": _iso(as_of),
        "mode": config.runtime.mode,
        "state": payload.get("state", "unknown"),
        "autonomous_paused": bool(payload.get("autonomous_paused", False)),
    }
    for key in ("previous", "reason", "requested_by", "scope"):
        if payload.get(key) is not None:
            snapshot[key] = payload[key]
    history = None
    try:
        # Metrics history is a telemetry sample since stage 1 item 3; the
        # ledger stream holds what was recorded before.
        from simorgh.telemetry import FILENAME as TELEMETRY_FILENAME
        from simorgh.telemetry.store import last_sample

        sample = last_sample(config.runtime.data_dir / TELEMETRY_FILENAME, "metrics.history")
        if sample is not None:
            history = {"ts": sample["ts"], "payload": sample["value"]}
    except Exception:  # noqa: BLE001 -- the metrics are extra; the state is the answer
        history = None
    if history is None:
        try:
            history = last_event(config, HISTORY_STREAM)
        except Exception:  # noqa: BLE001
            history = None
    if history is not None and isinstance((history.get("payload") or {}).get("metrics"), dict):
        snapshot["metrics"] = history["payload"]["metrics"]
        snapshot["metrics_as_of"] = _iso(history.get("ts"))
    if snapshot["state"] not in ("stopped", "failed") and why_not_live:
        snapshot["note"] = (f"the last recorded state is {snapshot['state']!r} but {why_not_live}; "
                            "the process may have ended without recording its stop")
    elif why_not_live:
        snapshot["live_error"] = why_not_live
    return snapshot


def read_status(config: LoadedConfig, *, timeout: float = 2.0) -> tuple[dict, str]:
    """(snapshot, one human line saying where it came from). Never boots,
    never appends: the live instance first, the ledger files second."""
    url = status_url(config)
    try:
        live = fetch_live(url, token=api_token(config), timeout=timeout)
    except LiveUnavailable as exc:
        snapshot = from_ledger(config, why_not_live=str(exc))
        as_of = snapshot.get("as_of")
        line = (f"status: from the ledger, as of {as_of} ({exc})" if as_of
                else f"status: from the ledger, nothing recorded ({exc})")
        return snapshot, line
    return {"source": "live", **live}, f"status: live, from {url}"


__all__ = ["LiveUnavailable", "api_token", "fetch_live", "from_ledger", "last_event", "read_status", "status_url"]

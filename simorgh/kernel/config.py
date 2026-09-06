"""`simorgh.toml` loading and merging (docs/blueprint/subsystems/03-kernel.md
section 3.5). Search order: `--config` CLI flag > `$SIMORGH_CONFIG` >
`./simorgh.toml` > `${data_dir}/simorgh.toml` > defaults (a missing file
is not an error -- the guaranteed floor boots with zero configuration).
Every `[section] key` is overridable by `SIMORGH_<SECTION>_<KEY>`
(uppercased, dots -> underscores), checked *after* the file so an
operator's environment always wins -- the same precedence every other
subsystem's own `Config.from_mapping` already uses (see
`simorgh.bus.config`, `simorgh.ledger.config`).
"""

from __future__ import annotations

import hashlib
import os
import tomllib
from pathlib import Path
from typing import Any, Mapping

from .api import RuntimeConfig


class ConfigError(ValueError):
    """The config file or an environment override names an invalid key
    or value -- raised at load time, never silently defaulted."""


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc


def find_config_path(explicit: str | None = None, *, data_dir: Path | None = None) -> Path | None:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("SIMORGH_CONFIG")
    if env:
        return Path(env).expanduser()
    cwd_candidate = Path("simorgh.toml")
    if cwd_candidate.is_file():
        return cwd_candidate
    if data_dir is not None:
        candidate = data_dir / "simorgh.toml"
        if candidate.is_file():
            return candidate
    return None


def _env_override_key(section: str, key: str) -> str:
    return f"SIMORGH_{section.upper()}_{key.upper().replace('.', '_')}"


def _apply_env_overrides(section: str, values: dict[str, Any], fields: Mapping[str, type]) -> dict[str, Any]:
    out = dict(values)
    for key, kind in fields.items():
        env_key = _env_override_key(section, key)
        raw = os.environ.get(env_key)
        if raw is None:
            continue
        if kind is bool:
            out[key] = raw.strip().lower() in ("1", "true", "yes", "on")
        elif kind is int:
            out[key] = int(raw)
        elif kind is float:
            out[key] = float(raw)
        elif kind in (tuple, list):
            out[key] = tuple(p.strip() for p in raw.split(",") if p.strip())
        else:
            out[key] = raw
    return out


_RUNTIME_FIELD_TYPES: dict[str, type] = {
    "mode": str, "data_dir": str, "deployment": str, "subsystems": tuple, "disabled": tuple,
    "idle_threshold_s": float, "idle_tick_cooldown_s": float, "sleep_every_s": float,
    "metrics_every_s": float, "health_every_s": float, "supervisor_max_restarts_per_10m": int,
    "stop_grace_s": float, "allow_backend_fallback": bool, "log_level": str, "log_to_ledger": bool,
}
_VALID_MODES = ("single", "local-multi", "aws")


def load_runtime_config(raw: Mapping[str, Any] | None = None) -> RuntimeConfig:
    """`raw` is the parsed `[runtime]` table (or None). Never trusts a
    partially-valid file: an unknown `mode` is a hard `ConfigError`, not
    a silent fallback to `single` (section 8: 'exit 2 with the offending
    key; never start with defaults silently')."""
    section = dict(raw or {})
    section = _apply_env_overrides("runtime", section, _RUNTIME_FIELD_TYPES)
    mode = str(section.get("mode", RuntimeConfig.mode))
    if mode not in _VALID_MODES:
        raise ConfigError(f"[runtime] mode must be one of {_VALID_MODES}, not {mode!r}")
    data_dir = Path(str(section.get("data_dir", "~/.simorgh"))).expanduser()
    subsystems = section.get("subsystems", RuntimeConfig.subsystems)
    if isinstance(subsystems, str):
        subsystems = (subsystems,)
    disabled = section.get("disabled", RuntimeConfig.disabled)
    if isinstance(disabled, str):
        disabled = (disabled,)
    backoff = section.get("supervisor_backoff_s", RuntimeConfig.supervisor_backoff_s)
    return RuntimeConfig(
        mode=mode,
        data_dir=data_dir,
        deployment=str(section.get("deployment", RuntimeConfig.deployment)),
        subsystems=tuple(subsystems),
        disabled=tuple(disabled),
        idle_threshold_s=float(section.get("idle_threshold_s", RuntimeConfig.idle_threshold_s)),
        idle_tick_cooldown_s=float(section.get("idle_tick_cooldown_s", RuntimeConfig.idle_tick_cooldown_s)),
        sleep_every_s=float(section.get("sleep_every_s", RuntimeConfig.sleep_every_s)),
        metrics_every_s=float(section.get("metrics_every_s", RuntimeConfig.metrics_every_s)),
        health_every_s=float(section.get("health_every_s", RuntimeConfig.health_every_s)),
        supervisor_backoff_s=tuple(float(x) for x in backoff),
        supervisor_max_restarts_per_10m=int(section.get(
            "supervisor_max_restarts_per_10m", RuntimeConfig.supervisor_max_restarts_per_10m)),
        stop_grace_s=float(section.get("stop_grace_s", RuntimeConfig.stop_grace_s)),
        allow_backend_fallback=bool(section.get("allow_backend_fallback", RuntimeConfig.allow_backend_fallback)),
        log_level=str(section.get("log_level", RuntimeConfig.log_level)),
        log_to_ledger=bool(section.get("log_to_ledger", RuntimeConfig.log_to_ledger)),
        schedule_max_duration_s=float((raw or {}).get("schedules", {}).get(
            "max_duration_s", RuntimeConfig.schedule_max_duration_s) if isinstance(raw, Mapping) else RuntimeConfig.schedule_max_duration_s),
        schedule_persist=bool((raw or {}).get("schedules", {}).get(
            "persist", RuntimeConfig.schedule_persist) if isinstance(raw, Mapping) else RuntimeConfig.schedule_persist),
    )


class LoadedConfig:
    """The whole parsed file plus the derived `RuntimeConfig`, a stable
    hash (logged to `system` on boot -- section 4), and per-subsystem
    section lookup (`section("cognition")` -> `{}` if absent, never
    `KeyError` -- an unconfigured subsystem is not a config error)."""

    def __init__(self, raw: dict[str, Any], path: Path | None) -> None:
        self.raw = raw
        self.path = path
        self.runtime = load_runtime_config(raw.get("runtime"))

    def section(self, name: str) -> dict[str, Any]:
        value = self.raw.get(name, {})
        return dict(value) if isinstance(value, Mapping) else {}

    @property
    def hash(self) -> str:
        import json

        return hashlib.sha256(json.dumps(self.raw, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def load_config(explicit_path: str | None = None) -> LoadedConfig:
    # First pass with a provisional data_dir (defaults) just to resolve
    # where the file might be; the real data_dir comes from the file/env
    # once parsed, but the search order in section 3.5 only needs the
    # *default* data_dir to find `${data_dir}/simorgh.toml`.
    default_data_dir = Path(os.environ.get("SIMORGH_RUNTIME_DATA_DIR", "~/.simorgh")).expanduser()
    path = find_config_path(explicit_path, data_dir=default_data_dir)
    raw = _read_toml(path) if path is not None else {}
    return LoadedConfig(raw, path)


__all__ = ["ConfigError", "LoadedConfig", "find_config_path", "load_config", "load_runtime_config"]

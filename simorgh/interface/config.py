"""`simorgh.toml [interface]` (spec section 3.5) -- the Phase 5 `api.*`
keys are intentionally absent: the HTTP/WebSocket surface is not built
this session (see the spec's own §12/header note)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    # None means `<data_dir>/interface/cli_history` -- the per-run data
    # dir, not a hardcoded home path, so an isolated/test run never writes
    # into the creator's real `~/.simorgh` (this session's leak class).
    # Set explicitly to share a history file across runs/versions.
    history_path: Path | None = None
    history_length: int = 1000
    color: str = "auto"  # auto | on | off
    # Banner glyphs. auto: box-drawing/geometric unicode when stdout is
    # UTF-8, never non-Latin script (fonts commonly lack it -- live-caught
    # as "weird characters"); full: also the Persian name; off: pure ASCII.
    unicode: str = "auto"  # auto | full | off
    # Live narration of the pending turn (07-post-cutover-review.md §3.9):
    # one dim line per task.started/step/completed of *this* session while
    # the reply is pending, plus a "still thinking" heartbeat so silence
    # never lasts longer than `narrate_heartbeat_s`.
    narrate: bool = True
    narrate_heartbeat_s: float = 10.0
    prompt_timeout_s: float = 120.0
    vitals_idle_reprint_s: float = 3.0
    vitals_interval_s: float = 15.0
    notice_queue_max: int = 200
    shell_timeout_s: float = 120.0
    # Must stay >= orchestration's own `Config.think_timeout_s` (120s
    # default) plus real margin for assemble+verify, not just the model
    # call itself -- this is the REPL's own *outer* wait on top of that
    # inner one. Was 8.0: even after wiring think_timeout_s through
    # (Worker never had it before), an 8s outer wait would still cut off
    # a legitimately-slow real answer and print the same "looks broken"
    # symptom via the TimeoutError branch instead of the empty-floor one
    # -- both were the same root cause wearing different code paths.
    chat_reply_timeout_s: float = 130.0
    http_host: str = "127.0.0.1"
    http_port: int = 8765
    http_status_timeout_s: float = 3.0
    http_chat_timeout_s: float = 130.0
    # Observe-tier additions (02-system-architecture.md section 6.2):
    # bounds for the `/api/history` and `/api/logs` read-only queries.
    history_stream: str = "metrics:history"
    history_default_minutes: float = 10.0
    history_max_points: int = 500
    logs_default_limit: int = 100
    logs_max_limit: int = 500

    def resolved_history_path(self) -> Path | None:
        return self.history_path.expanduser() if self.history_path is not None else None

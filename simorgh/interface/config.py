"""`simorgh.toml [interface]` (spec section 3.5) -- the Phase 5 `api.*`
keys are intentionally absent: the HTTP/WebSocket surface is not built
this session (see the spec's own §12/header note)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    history_path: Path = Path("~/.simorgh/cli_history")
    history_length: int = 1000
    color: str = "auto"  # auto | on | off
    prompt_timeout_s: float = 120.0
    vitals_idle_reprint_s: float = 3.0
    vitals_interval_s: float = 15.0
    notice_queue_max: int = 200
    shell_timeout_s: float = 120.0
    chat_reply_timeout_s: float = 8.0
    http_host: str = "127.0.0.1"
    http_port: int = 8765
    http_status_timeout_s: float = 3.0
    # Observe-tier additions (02-system-architecture.md section 6.2):
    # bounds for the `/api/history` and `/api/logs` read-only queries.
    history_stream: str = "metrics:history"
    history_default_minutes: float = 10.0
    history_max_points: int = 500
    logs_default_limit: int = 100
    logs_max_limit: int = 500

    def resolved_history_path(self) -> Path:
        return self.history_path.expanduser()

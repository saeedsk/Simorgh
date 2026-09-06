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

    def resolved_history_path(self) -> Path:
        return self.history_path.expanduser()

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
    # Narrate *every* task, not only the ones this REPL started.
    # The creator, 2026-09-07: "these thing were happening behind the
    # scene and I was not aware of them, i want full visibility". Off
    # restores the previous behaviour, where autonomous work ran
    # silently and only a watched task ever printed anything.
    narrate_autonomous: bool = True
    # Read through typos before a typed line is answered (cognition/
    # tidy.py): a line that looks garbled gets one short model call and
    # the screen shows what it was read as. The creator, 2026-09-12.
    tidy_input: bool = True
    # Print a line per step for autonomous work too, not just the
    # start and the outcome. "verbose as hell", their words.
    narrate_steps: bool = True
    narrate_heartbeat_s: float = 10.0
    # How long the REPL thread holds its splash waiting for the Kernel
    # to reach `running`, so boot progress is not overprinted. Bounded:
    # a boot that never completes still gets a usable prompt.
    boot_wait_s: float = 20.0
    # The prompt_toolkit prompt (sticky footer, completion menu,
    # multi-line editing). Falls back to the readline REPL when the
    # dependency is missing or stdout is not a terminal, so turning
    # this off is only for preferring the plain prompt on purpose.
    rich_prompt: bool = True
    # Redraw-in-place status footer (the creator's own explicit call,
    # 2026-09-06, after being shown the tradeoff against `render.py`'s
    # scrolling-only rule -- see `live_status.py`'s module docstring for
    # the full design). auto: on for a real interactive terminal, off
    # for anything redirected/piped/headless (tests included, since
    # `io.StringIO.isatty()` is always False).
    live_status: str = "auto"  # auto | on | off
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
    # And a chat turn is up to `max_steps=6` model calls, not one: a
    # question that makes Sim read a file first is two thinks. At 130s
    # the second think alone could exhaust it and the REPL printed
    # "no response" over an answer that was still coming.
    chat_reply_timeout_s: float = 420.0
    http_host: str = "127.0.0.1"
    http_port: int = 8765
    http_status_timeout_s: float = 3.0
    http_chat_timeout_s: float = 130.0
    # platform-connectors-design.md section 4: the body cap for POST
    # routes a subsystem registers (a webhook payload, a voice
    # transcript). `/api/chat` keeps its own, much smaller cap -- a chat
    # message is not a file upload.
    api_max_body_bytes: int = 1_000_000
    # Observe-tier additions (02-system-architecture.md section 6.2):
    # bounds for the `/api/history` and `/api/logs` read-only queries.
    history_stream: str = "metrics:history"
    history_default_minutes: float = 10.0
    history_max_points: int = 500
    logs_default_limit: int = 100
    logs_max_limit: int = 500
    # The glass dashboard's collector (interface/dashfeeds.py): markets,
    # headlines, weather, charts, Wikipedia, jokes for `/dash`. Off, the
    # page shows Sim and empty panels that say so. The place is for the
    # weather; the watchlist is the creator's 15 tech names by default
    # and the majors are the five that get the big charts.
    dash_feeds: bool = True
    dash_place: str = "San Jose, CA"
    dash_latitude: float = 37.34
    dash_longitude: float = -121.89
    dash_watchlist: tuple[str, ...] = ()
    dash_majors: tuple[str, ...] = ()
    # The dashboard's camera strip wants every Reolink camera live. On,
    # the HTTP API asks Execution for the relays (`cam_stream all dash`,
    # through Guardian) shortly after boot and again whenever none is
    # live -- so a restart does not leave the TV grey until the page
    # notices. Off, only the page asks, or a person does.
    dash_cameras_live: bool = True

    def resolved_history_path(self) -> Path | None:
        return self.history_path.expanduser() if self.history_path is not None else None

    @classmethod
    def from_mapping(cls, data: dict | None) -> "Config":
        data = data or {}
        default = cls()
        history_path = data.get("history_path", default.history_path)
        return cls(
            history_path=Path(history_path) if history_path is not None else None,
            history_length=int(data.get("history_length", default.history_length)),
            color=str(data.get("color", default.color)),
            unicode=str(data.get("unicode", default.unicode)),
            narrate=bool(data.get("narrate", default.narrate)),
            narrate_autonomous=bool(data.get("narrate_autonomous", default.narrate_autonomous)),
            narrate_steps=bool(data.get("narrate_steps", default.narrate_steps)),
            narrate_heartbeat_s=float(data.get("narrate_heartbeat_s", default.narrate_heartbeat_s)),
            boot_wait_s=float(data.get("boot_wait_s", default.boot_wait_s)),
            rich_prompt=bool(data.get("rich_prompt", default.rich_prompt)),
            live_status=str(data.get("live_status", default.live_status)),
            prompt_timeout_s=float(data.get("prompt_timeout_s", default.prompt_timeout_s)),
            vitals_idle_reprint_s=float(data.get("vitals_idle_reprint_s", default.vitals_idle_reprint_s)),
            vitals_interval_s=float(data.get("vitals_interval_s", default.vitals_interval_s)),
            notice_queue_max=int(data.get("notice_queue_max", default.notice_queue_max)),
            shell_timeout_s=float(data.get("shell_timeout_s", default.shell_timeout_s)),
            chat_reply_timeout_s=float(data.get("chat_reply_timeout_s", default.chat_reply_timeout_s)),
            http_host=str(data.get("http_host", default.http_host)),
            http_port=int(data.get("http_port", default.http_port)),
            http_status_timeout_s=float(data.get("http_status_timeout_s", default.http_status_timeout_s)),
            http_chat_timeout_s=float(data.get("http_chat_timeout_s", default.http_chat_timeout_s)),
            api_max_body_bytes=int(data.get("api_max_body_bytes", default.api_max_body_bytes)),
            history_stream=str(data.get("history_stream", default.history_stream)),
            history_default_minutes=float(data.get("history_default_minutes", default.history_default_minutes)),
            history_max_points=int(data.get("history_max_points", default.history_max_points)),
            logs_default_limit=int(data.get("logs_default_limit", default.logs_default_limit)),
            logs_max_limit=int(data.get("logs_max_limit", default.logs_max_limit)),
            dash_feeds=bool(data.get("dash_feeds", default.dash_feeds)),
            dash_place=str(data.get("dash_place", default.dash_place)),
            dash_latitude=float(data.get("dash_latitude", default.dash_latitude)),
            dash_longitude=float(data.get("dash_longitude", default.dash_longitude)),
            dash_watchlist=tuple(str(s).strip().upper() for s in (data.get("dash_watchlist") or ()) if str(s).strip()),
            dash_majors=tuple(str(s).strip().upper() for s in (data.get("dash_majors") or ()) if str(s).strip()),
            dash_cameras_live=bool(data.get("dash_cameras_live", default.dash_cameras_live)),
        )

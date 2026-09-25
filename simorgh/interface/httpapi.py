"""A minimal, stdlib-only HTTP server for Interface's live dashboard.

Pulled forward from roadmap Phase 5's "HTTP/WebSocket API in Interface"
item, scoped to three concerns: let the creator *see* the running
system (subsystem status, bus/worker/cognition/memory/process metrics,
metrics history, logs), *talk* to it from the same page (asked for
directly after the REPL's own `chat_reply_timeout_s`/`think_timeout_s`
wiring bug made a real answer look like a hang), and browse what's
already durable without a new capability. Not the general-purpose
multi-session API Phase 5 describes (02-system-architecture.md section
6.1); one chat box, one turn in flight at a time, no session history --
that's still future work.

Extended for the observe tier (02-system-architecture.md section 6.2,
captured right after the creator saw the first version run live):
`/api/history` (metrics over time, read from the Kernel's own
`metrics:history` Ledger stream -- see `simorgh/kernel/metrics.py`'s
`MetricsHistoryWriter`), `/api/logs` (a tail of any Ledger stream --
"structured logs are Ledger events," section 7), and `/api/streams`
(which streams currently exist, for a stream picker). All three are
read-only queries against the same `Ledger` protocol every subsystem
already gets from its own `Context` -- no new capability, just a new
surface over data that was already durable and already queryable.
`ledger` is optional (`None` in the handful of existing tests/callers
that only care about `/`, `/api/status`, or `/api/chat`); the three new
routes degrade to an honest `{"error": ...}` body rather than a 500
when it is absent, same "unreachable kernel is data for the page"
posture `/api/status` already has.

GET and POST only, `Connection: close` on every response -- this is a
local, single-viewer page, not a production HTTP service, so there is
no benefit to the complexity of keep-alive or concurrent-request
pipelining. No third-party dependency (04-build-plan-and-roadmap.md
section 5's "no new third-party dependency in the core"): a hand-rolled
HTTP/1.1 request line + header parse over `asyncio.start_server` is
enough for a handful of routes.
"""

from __future__ import annotations

import asyncio
import os
import re
import hmac
import ipaddress
import contextlib
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlencode, urlsplit

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.messages.ui import DASH_KEYS
from simorgh.contracts.streamnames import is_valid_stream, stream_name_rule

_STATIC_DIR = Path(__file__).resolve().parent / "static"

_REASONS = {
    200: "OK", 206: "Partial Content", 302: "Found", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
    416: "Range Not Satisfiable",
    405: "Method Not Allowed", 409: "Conflict", 413: "Payload Too Large",
    429: "Too Many Requests", 500: "Internal Server Error",
}

_MAX_BODY_BYTES = 16 * 1024  # a chat message, not a file upload

#: Routes that answer without a token even when one is configured.
#: `/` is the page that *carries* the token to the browser, so gating it
#: would make the dashboard unreachable; `/api/status` is the liveness
#: check a monitor or a shell script polls, and it reveals only what the
#: boot banner already prints. Everything else is gated
#: (platform-connectors-design.md section 4).
#: Routes served without the token: the pages themselves (which then
#: fetch their data with the token the page was opened with), status,
#: wallpapers, the logo. NOT the cameras: `/api/dash/streams` (every
#: camera with a ready URL), `/cameras/snap/` (the newest still) and
#: `/tv/hls/` (live video) were open until 2026-09-19, so anyone on the
#: LAN could watch the house on a `0.0.0.0` bind (2026-09-18 evaluation,
#: S15/V2). The dash and TV pages already append `?token=` to those URLs.
_OPEN_ROUTES: frozenset[str] = frozenset({"/", "/api/status", "/tv", "/dash", "/api/wallpapers", "/api/dash/data",
                                          "/api/dash/state", "/api/dash/keys", "/remote", "/logo.png", "/favicon.ico", "/api/dash/banner",
                                          # The barcode's own URL. It carries no secret: the code is in the
                                          # fragment, which never reaches this server.
                                          "/pair"})
#: The `/pair` page. Small enough to live here rather than in `static/`,
#: and deliberately self-contained: a phone that has just scanned a
#: barcode may not be able to fetch anything else yet.
_PAIR_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pair with Sim</title>
<style>
 body{font:16px/1.5 -apple-system,system-ui,sans-serif;margin:0;padding:2rem 1.25rem;
      background:#111;color:#eee;text-align:center}
 h1{font-size:1.3rem;margin:0 0 1.5rem}
 code{display:block;font-size:2rem;letter-spacing:.06em;margin:1.5rem 0;padding:1rem;
      background:#1e1e1e;border-radius:.6rem;word-break:break-all;-webkit-user-select:all;user-select:all}
 p{color:#aaa;max-width:32rem;margin:1rem auto}
 .none{color:#e88}
</style></head><body>
<h1>Pair with Sim</h1>
<div id="out"><p>Reading the code&hellip;</p></div>
<p>Type this into the Sim app, or scan the barcode again with it.</p>
<p>It works once, and only for about two minutes.</p>
<script>
 // The code is in the fragment, so the server never saw it and neither
 // did any proxy or log on the way here. This page is the only thing that
 // can read it.
 var code = decodeURIComponent((location.hash || '').replace(/^#/, '')).trim();
 document.getElementById('out').innerHTML = code
   ? '<code>' + code.replace(/[&<>"]/g, function (c) {
       return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }) + '</code>'
   : '<p class="none">No code in this link. On Sim, type <b>pair my phone</b> for a new barcode.</p>';
</script>
</body></html>
"""

#: The tools a paired device may ask for through `POST /api/action`.
#:
#: An ALLOWLIST, not "whatever Guardian permits", and the distinction is
#: the whole safety of that route. Guardian gates EFFECTS: it weighs a
#: proposal on its merits and this house auto-approves the irreversible
#: ones. This gates SURFACE: what a network request is allowed to propose
#: in the first place. `_run_for_page` was safe only because the server
#: itself chose every tool name it passed; the moment a client names the
#: tool, a stolen phone token could ask for `run_shell` and Guardian would
#: weigh it as a legitimate request, because from its side it is one.
#:
#: So: the house's remote control -- lights, scenes, cameras, media, the
#: TV, tasks, voice settings -- and nothing that writes code, runs a
#: shell, installs a package or spends money. A tool not here is refused
#: BY NAME, so the failure is legible rather than a mystery 403.
ACTION_TOOLS: frozenset[str] = frozenset({
    # the house
    "home_find", "home_state", "home_describe", "home_call", "home_undo",
    "energy_status", "energy_report",
    # what it can see
    "cam_list", "cam_state", "cam_snapshot", "cam_stream", "cam_light", "cam_ir", "cam_siren",
    "cam_ptz", "cam_recordings", "cam_watch", "camera_describe",
    "ring_list", "ring_snapshot", "ring_events", "ring_light", "ring_siren", "ring_watch", "ring_live",
    # what it can play
    "media_now", "media_control", "media_play", "music_now", "music_control", "music_play",
    "cast_devices", "cast_show", "cast_play", "cast_stop", "cast_volume",
    "tv_app", "tv_key", "tv_charts", "dash_view", "dash_key",
    # its own work, and its own voice
    "list_tasks", "cancel_task", "voice_setting", "remind", "overheard", "memory_search",
})

#: What `/api/dash/data` withholds from a request without the token.
_HOUSE_KEYS: tuple[str, ...] = ("cameras", "streams", "ring_cameras", "events")

#: Prefix routes served without the token. Wallpapers only.
_OPEN_PREFIXES: tuple[str, ...] = ("/wallpapers/",)

#: The response to an unauthenticated request. A JSON body, because
#: every other error on this server is JSON and a dashboard that got
#: HTML here would render it into the chat log.
_UNAUTHORIZED = json.dumps({
    "error": {"code": "unauthorized",
              "detail": "this API requires `Authorization: Bearer <token>`; "
                        "the token is the SIM_API_TOKEN secret"}}).encode("utf-8")


#: A handler answers `(status, body, content_type)`. It receives the
#: parsed query, the (already length-capped) request body, and the
#: request headers -- everything a route can legitimately need, and
#: nothing that would let it read the socket a second time.
RouteHandler = Callable[[dict, bytes, dict], Awaitable[tuple[int, bytes, str]]]


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    handler: RouteHandler
    auth: bool = True
    #: Overrides the server-wide body cap for this one route. `/api/chat`
    #: keeps the original 16 KiB: a chat message is not a file upload,
    #: and the wider cap exists for routes a subsystem registers later.
    max_body: int | None = None
    #: `(calls, window_s)` -- a per-route sliding window, so one client
    #: cannot turn a cheap-looking endpoint into a way to occupy the
    #: single in-flight turn or spin the Ledger.
    rate: tuple[int, float] | None = None



def _dash_state_problems(payload: dict) -> str:
    """Why a dashboard state change cannot be applied, or "". Types the
    schema (ui.dash.state.v1) will not take are refused here, before
    anything changes."""
    import math

    for key in ("rotate_s", "live_max", "live_step_s", "scale"):
        if key in payload:
            value = payload[key]
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                return f"{key} must be a number"
            try:
                number = float(value)
            except (TypeError, ValueError):
                return f"{key} must be a number"
            if math.isnan(number) or math.isinf(number):
                return f"{key} must be a finite number"
            if key != "scale" and not float(number).is_integer():
                return f"{key} must be a whole number of seconds" if key == "rotate_s" else f"{key} must be a whole number"
    for key in ("view", "timeframe", "symbol", "video_quality"):
        if key in payload and not isinstance(payload[key], str):
            return f"{key} must be text"
    if "video_quality" in payload and str(payload["video_quality"]).strip().lower() not in ("light", "full"):
        return "video_quality must be light or full"
    return ""

class HttpApi:
    def __init__(
        self, bus, *, ledger=None, host: str = "127.0.0.1", port: int = 8765,
        clock=None, status_timeout_s: float = 3.0, chat_timeout_s: float = 130.0,
        history_stream: str = "metrics:history", history_default_minutes: float = 10.0, telemetry=None,
        history_max_points: int = 500, logs_default_limit: int = 100, logs_max_limit: int = 500,
        token: str = "", max_body_bytes: int = 1_000_000, logger=None, feeds=None,
        cameras_live: bool = False, cameras_live_delay_s: float = 20.0, cameras_live_every_s: float = 120.0,
        devices=None, prompts=None, answer_prompt=None,
    ) -> None:
        self._bus = bus
        self._ledger = ledger
        self._token = (token or "").strip()
        #: The paired devices (`interface/devices.py`), or None for a server
        #: that has none -- in which case only the legacy shared token works,
        #: which is every deployment that predates stage 12 item 2.
        self._devices = devices
        #: The open `ui.prompt`s and how to answer one (stage 12 item 3).
        #: Callables rather than the Service itself: this file knows what a
        #: question looks like and nothing about who is holding them.
        self._prompts = prompts
        self._answer_prompt = answer_prompt
        self._max_body_bytes = max(1, int(max_body_bytes))
        self._logger = logger
        self._routes: dict[tuple[str, str], Route] = {}
        self._rate_hits: dict[str, deque] = {}
        self._host = host
        self._port = port
        self._clock = clock
        self._timeout = status_timeout_s
        self._chat_timeout = chat_timeout_s
        self._history_stream = history_stream
        # Metrics history lives in the telemetry store when there is one
        # (stage 1 item 3); the ledger stream is the fallback for data
        # recorded before, and for a Kernel with telemetry off.
        self._telemetry = telemetry
        self._history_default_minutes = history_default_minutes
        self._history_max_points = max(1, history_max_points)
        self._logs_default_limit = logs_default_limit
        self._logs_max_limit = max(1, logs_max_limit)
        self._server: asyncio.base_events.Server | None = None
        self._page_cache: dict[str, tuple[float, str]] = {}
        # Sim on the TV (interface/static/tv.html): a replica of the
        # terminal, and what to frame in it (`tv.state`, published by the
        # cast tools in execution/media/cast.py).
        # Read on every request, not once at boot. The creator changed
        # the dashboard, re-cast it, and still saw the old page -- twice,
        # because the fix was in a string this process had read at
        # startup and would hold until it restarted (2026-09-22). A
        # `stat` per page load is nothing; a page nobody can refresh
        # without a restart is a day of "it didn't work".
        self._tv_state: dict = {"mode": "none", "url": "", "title": "", "since": 0.0}
        self._tv_sub = None
        self._tv_speech: deque = deque(maxlen=40)   # (seq, ref, seconds, at): Sim's voice for the page
        self._tv_speech_sub = None
        # The glass dashboard's collector (interface/dashfeeds.py), or
        # None when `[interface] dash_feeds = false`: `/api/dash/data`
        # then answers an empty snapshot that says the feeds are off.
        self._feeds = feeds
        # Relays for the strip without waiting for the page: shortly after
        # boot, then whenever the collector sees none live. Stops asking
        # once the tool says the NVR is not set up (until the next boot).
        self._cameras_live = bool(cameras_live)
        self._cameras_live_delay_s = cameras_live_delay_s
        self._cameras_live_every_s = cameras_live_every_s
        self._cameras_live_task: asyncio.Task | None = None
        self._cameras_live_gave_up = False
        self._cameras_live_last: dict = {"at": 0.0, "text": ""}
        # Where the dashboard should look (`ui.dash.state`): set by the
        # `dash_view` tool or the phone remote, polled by the page.
        self._dash_state: dict = {"view": "", "timeframe": "", "symbol": "", "rotate_s": 0, "scale": 0,
                                  "live_max": 3, "live_step_s": 6.0, "video_quality": "light", "video_sound": True, "since": 0.0}
        self._dash_sub = None
        # Remote-control keys for the dashboard page (`POST /api/dash/key`,
        # `ui.dash.key`), newest last; the page polls them by sequence.
        self._dash_keys: deque = deque(maxlen=32)
        self._dash_key_seq = 0
        self._dash_key_sub = None
        self._remote_page = (_STATIC_DIR / "remote.html").read_text(encoding="utf-8")
        # Sim's logo (the creator's, 2026-09-12; keyed and shrunk from
        # images/logo/Sim-Logo.png), for the pages' top bar and the tab icon.
        self._logo = (_STATIC_DIR / "sim-logo.png").read_bytes()
        # The newest camera still per camera (execution/home/cameras.py
        # writes `workspace/cameras/<name>-<stamp>.jpg`; ring.py the same
        # under workspace/cameras/ring/), for the dashboard's tiles.
        self._snapshot_root = (Path.cwd() / "workspace" / "cameras").resolve()
        # Live camera video for the TV page (execution/home/cameras.py
        # writes HLS under workspace/cameras/hls/<channel>/). Served on
        # the LAN without the token: the Cast receiver fetches segments
        # with no header and no query of its own.
        self._hls_root = (Path.cwd() / "workspace" / "cameras" / "hls").resolve()
        self._media_root = (Path.cwd() / "workspace" / "tv" / "media").resolve()
        # High-res wallpapers the dashboard rotates through the panels
        # (the creator dropped them in images/wallpapers, 2026-09-12).
        self._wallpaper_root = (Path.cwd() / "images" / "wallpapers").resolve()
        self._prefixes: list[tuple[str, str, RouteHandler]] = []
        self._pending_chats: dict[str, asyncio.Future] = {}
        self._turn_sub = None
        self._register_builtin_routes()

    # -- routing -----------------------------------------------------------------------------

    def register_route(self, method: str, path: str, handler: RouteHandler, *, auth: bool = True,
                       max_body: int | None = None, rate: tuple[int, float] | None = None) -> None:
        """Add a route. `home`, `voice` and the domain subsystems add
        their inbound webhooks through this rather than by editing this
        file (platform-connectors-design.md section 4).

        `auth=True` (the default, and the only safe default) means the
        route is refused without the bearer token whenever a token is
        configured. A route may opt out, but `_OPEN_ROUTES` is the
        reviewed list of the ones that legitimately do.
        """
        method = method.upper()
        if (method, path) in self._routes:
            raise ValueError(f"route already registered: {method} {path}")
        self._routes[(method, path)] = Route(
            method=method, path=path, handler=handler,
            # The open list covers reads only: `POST /api/dash/state`
            # shares its path with an open GET and stays behind the token.
            auth=auth and not (path in _OPEN_ROUTES and method == "GET"), max_body=max_body, rate=rate)

    def _register_builtin_routes(self) -> None:
        async def _page(_query, _body, _headers):
            return 200, self._static_page("dashboard.html").encode("utf-8"), "text/html; charset=utf-8"

        def _json_route(fn):
            async def _handler(query, _body, _headers):
                return 200, await fn(query), "application/json"

            return _handler

        async def _status(_query, _body, headers):
            # Open, but not a way around the gate. This route stays
            # unauthenticated so a viewer can see the system is alive --
            # its comment says it reveals "only what the boot banner
            # already prints". It did not: on a token-gated server an
            # unauthenticated caller got process memory, this host's
            # load averages, every bus counter and queue depth, and the
            # worker table INCLUDING the running task's id -- the same
            # observe-tier numbers `/api/history` answers with a 401
            # (observer, 2026-09-10). Liveness stays open; the metrics
            # need the token. With no token configured nothing changes,
            # because then there is no gate to get around.
            full = self._token and not self._authorized(headers)
            return 200, await self._status_json(public_only=bool(full)), "application/json"

        async def _tv(_query, _body, _headers):
            return 200, self._static_page("tv.html").encode("utf-8"), "text/html; charset=utf-8"

        async def _tv_state(_query, _body, _headers):
            now = self._now()
            speech = [{"seq": seq, "url": f"/api/tv/speech?ref={ref}", "seconds": seconds}
                      for seq, ref, seconds, at in self._tv_speech if now - at < 30.0]
            return 200, json.dumps({"now": now, **self._tv_state, "speech": speech}).encode("utf-8"), "application/json"

        async def _tv_speech(query, _body, _headers):
            ref = self._q1(query, "ref", "") or ""
            known = any(ref == r for _s, r, _sec, _at in self._tv_speech)
            if not ref or not known or self._ledger is None:
                return 404, b"no such speech", "text/plain; charset=utf-8"
            try:
                data = await self._ledger.get_blob(ref)
            except Exception:  # noqa: BLE001
                return 404, b"no such speech", "text/plain; charset=utf-8"
            return 200, data, "audio/wav"

        self.register_route("GET", "/", _page, auth=False)
        self.register_route("GET", "/api/status", _status, auth=False)
        self.register_route("GET", "/tv", _tv, auth=False)

        async def _dash(_query, _body, _headers):
            return 200, self._static_page("dash.html").encode("utf-8"), "text/html; charset=utf-8"

        async def _wallpapers(_query, _body, _headers):
            names = []
            root = self._wallpaper_root
            if root.is_dir():
                names = sorted(f.name for f in root.iterdir()
                               if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".avif") and not f.name.startswith("."))
            return 200, json.dumps({"wallpapers": names}).encode("utf-8"), "application/json"

        async def _dash_data(query, _body, headers):
            if self._feeds is None:
                body = {"now": self._now(), "off": True, "feeds": {}, "markets": None, "news": {}}
            else:
                body = self._feeds.snapshot()
                if not self._authorized(headers, query):
                    # The route stays open for the news and markets tiles; the
                    # house does not. It listed every camera, relay stream URL,
                    # Ring camera and Ring event without the token, on a
                    # 0.0.0.0 bind too (found writing interface's CONTRACT.md,
                    # 2026-09-19; the 2026-09-18 S15 fix gated only streams,
                    # stills and HLS). The dash page sends its token.
                    for key in _HOUSE_KEYS:
                        body.pop(key, None)
            return 200, json.dumps(body, default=str).encode("utf-8"), "application/json"

        async def _dash_state_get(_query, _body, _headers):
            # `build` is when dash.html itself last changed. The page
            # compares it with its own and reloads: a Cast receiver in a
            # living room is the last screen anybody thinks to refresh,
            # and a fix that only reaches the TV when somebody re-casts
            # it is a fix the household never sees (2026-09-22).
            return 200, json.dumps({"now": self._now(), "build": self._page_build(),
                                    **self._dash_state}).encode("utf-8"), "application/json"

        async def _dash_state_post(query, body, headers):
            # The phone remote (`/remote?token=`): gated like every other
            # side effect (the token, in the header or the query).
            try:
                asked = json.loads(body.decode("utf-8") or "{}")
            except ValueError:
                return 400, b'{"error": "body must be JSON"}', "application/json"
            if not isinstance(asked, dict):
                return 400, b'{"error": "body must be a JSON object"}', "application/json"
            payload = {k: asked[k] for k in ("view", "timeframe", "symbol", "rotate_s", "scale", "live_max", "live_step_s", "video_quality", "video_sound") if k in asked}
            bad = _dash_state_problems(payload)
            if bad:
                return 400, json.dumps({"error": bad}).encode("utf-8"), "application/json"
            self._apply_dash_state(payload)
            # What was APPLIED goes on the bus, in the schema's own types --
            # the raw body once failed validation after the state had
            # already changed, and the remote was told 500 (observer, 2026-09-13).
            applied = {k: self._dash_state[k] for k in ("view", "timeframe", "symbol", "rotate_s", "scale", "live_max", "live_step_s", "video_quality", "video_sound")
                       if k in payload and k in self._dash_state}
            await self._bus.publish(Message.new(topics.DASH_STATE, source="interface", payload=applied))
            return 200, json.dumps({"now": self._now(), **self._dash_state}).encode("utf-8"), "application/json"

        async def _remote(_query, _body, _headers):
            return 200, self._remote_page.encode("utf-8"), "text/html; charset=utf-8"

        async def _logo(_query, _body, _headers):
            return 200, self._logo, "image/png"

        async def _banner(query, _body, _headers):
            # What the terminal prints at startup -- the splash, the
            # wordmark, the quick commands -- for the dashboard's Sim box
            # (the creator, 2026-09-12: "show the startup like the banner,
            # help commands"). ANSI as the CLI writes it; the page turns
            # the SGR codes into spans.
            from .render import banner

            mode = self._q1(query, "unicode", "auto") or "auto"
            text = banner(enabled=True, unicode=mode if mode in ("auto", "full", "off") else "auto")
            return 200, json.dumps({"text": text}).encode("utf-8"), "application/json"

        self.register_route("GET", "/dash", _dash, auth=False)
        self.register_route("GET", "/api/wallpapers", _wallpapers, auth=False)
        self.register_route("GET", "/api/dash/data", _dash_data, auth=False)
        async def _dash_key_post(_query, body, _headers):
            # The phone remote's D-pad: gated like every other side effect.
            try:
                asked = json.loads(body.decode("utf-8") or "{}")
            except ValueError:
                return 400, b'{"error": "body must be JSON"}', "application/json"
            key = str(asked.get("key") or "").strip().lower() if isinstance(asked, dict) else ""
            if key not in DASH_KEYS:
                return 400, json.dumps({"error": f"key is one of {', '.join(DASH_KEYS)}"}).encode("utf-8"), "application/json"
            return 200, json.dumps({"ok": True, "seq": self._push_dash_key(key)}).encode("utf-8"), "application/json"

        async def _dash_keys_get(query, _body, _headers):
            # `after` is the last sequence the page has seen; without one (a
            # page that just loaded) nothing old is replayed, only `seq`.
            try:
                after = int(self._q1(query, "after", "-1") or -1)
            except ValueError:
                after = -1
            keys = [k for k in self._dash_keys if after >= 0 and k["seq"] > after]
            return 200, json.dumps({"seq": self._dash_key_seq, "keys": keys}).encode("utf-8"), "application/json"

        self.register_route("GET", "/api/dash/state", _dash_state_get, auth=False)
        self.register_route("GET", "/api/dash/keys", _dash_keys_get, auth=False)
        self.register_route("POST", "/api/dash/key", _dash_key_post, max_body=512, rate=(300, 60.0))
        async def _pair(_query, body, _headers):
            """POST /api/pair -- spend a pairing code, get this device's own token.

            THE ONLY UNAUTHENTICATED WRITE ROUTE IN THIS SERVER, and it is
            only safe because of what it cannot do: it can SPEND a code and
            it cannot create one. Codes are minted by `pair` in the terminal
            or a spoken turn, never over HTTP, so somebody who reaches this
            with no code in hand has nothing to call. It is rate-limited on
            top, and the book itself kills a code after ten attempts.

            The token comes back ONCE. Nothing stores it, here or anywhere;
            only its hash is kept (`devices.py`).
            """
            if self._devices is None:
                return 404, b'{"error":{"code":"no_pairing","detail":"this Sim has no device book"}}', "application/json"
            try:
                parsed = json.loads(body or b"{}")
                code = str(parsed.get("code") or "").strip()
            except (json.JSONDecodeError, AttributeError):
                return 400, b'{"error":{"code":"invalid_json"}}', "application/json"
            got = self._devices.redeem(code)
            if isinstance(got, str):
                # The reason is deliberately specific -- an expired code and
                # a wrong code are different problems for the person holding
                # the phone, and neither tells an attacker what a clock
                # would not.
                return 403, json.dumps({"error": {"code": "pairing_refused", "detail": got}}).encode("utf-8"), \
                    "application/json"
            device, token = got
            if self._logger is not None:
                # On the record: a pairing nobody saw is the one worth
                # noticing.
                with contextlib.suppress(Exception):
                    self._logger.info("interface.device_paired", device=device.id, name=device.name,
                                      capabilities=list(device.capabilities))
            return 200, json.dumps({
                "token": token, "device_id": device.id, "name": device.name,
                "capabilities": list(device.capabilities),
            }).encode("utf-8"), "application/json"

        self.register_route("POST", "/api/pair", _pair, auth=False, max_body=512, rate=(20, 60.0))

        async def _pair_page(_query, _body, _headers):
            """GET /pair -- what the barcode's URL leads to.

            The code rides in the FRAGMENT, which a browser never sends, so
            this page cannot be given it and reads it from `location.hash`
            itself. Which is the point: the server never sees the code
            except when it is spent at `POST /api/pair`.

            It exists because the barcode's URL LOOKS like a link and people
            tap links. Before this it was a 404 (the creator, 2026-09-25),
            which reads as "Sim is broken" rather than "this is for the
            app". Now it shows the code big enough to type into the app's
            own field -- so pairing works from a phone with no camera, or
            one that refused the camera.
            """
            return 200, _PAIR_PAGE.encode("utf-8"), "text/html; charset=utf-8"

        self.register_route("GET", "/pair", _pair_page, auth=False, rate=(60, 60.0))

        async def _prompts_get(_query, _body, headers):
            """GET /api/prompts -- what Sim is waiting to be told.

            `read` is enough to SEE a question; answering needs `approve`.
            Seeing one matters even without the grant: it is how somebody
            at home knows Sim is stuck rather than slow.
            """
            if self._prompts is None:
                return 200, b'{"prompts":[]}', "application/json"
            return 200, json.dumps({"prompts": self._prompts()}).encode("utf-8"), "application/json"

        self.register_route("GET", "/api/prompts", _prompts_get, rate=(120, 60.0))

        async def _console(query, _body, _headers):
            """GET /api/console -- the lines Sim actually printed.

            Not the ledger and not the activity feed: the CONSOLE, glyphs
            and all, exactly as it reads on the creator's screen. It is
            already captured (`contracts/console.py` writes
            `interface/console.log` for `console_tail`, the only way Sim
            can answer a question about its own output), so a client can
            mirror the terminal rather than approximate it.

            `?contains=` filters, which is what makes a long tail usable
            on a phone.
            """
            from simorgh.contracts import console as console_log

            try:
                limit = int(self._q1(query, "limit", "200") or 200)
            except ValueError:
                limit = 200
            limit = max(1, min(limit, 2000))
            contains = self._q1(query, "contains", "") or ""
            try:
                lines = console_log.tail(limit=limit, contains=contains)
            except Exception as exc:  # noqa: BLE001 -- a bad read is data for the page
                return 200, json.dumps({"lines": [], "error": {"code": "console_unavailable",
                                                                "detail": str(exc)}}).encode("utf-8"), \
                    "application/json"
            return 200, json.dumps({"lines": lines}).encode("utf-8"), "application/json"

        self.register_route("GET", "/api/console", _console, rate=(120, 60.0))

        async def _prompt_answer(query, body, headers):
            """POST /api/prompts/<id> -- answer one. Needs `approve`.

            This is why the phone exists. `ui.prompt` and
            `ui.prompt.answered` have been on the Bus since Guardian could
            escalate, and until now only the REPL published the answer -- so
            every irreversible action waited for somebody at that terminal
            and Sim's autonomy ended at the desk.
            """
            if self._answer_prompt is None:
                return 404, b'{"error":{"code":"no_prompts"}}', "application/json"
            who = self.caller(headers, query)
            if not self.may(who, "approve"):
                # Named, so the failure is legible: a device paired without
                # the grant should be told which word it is missing rather
                # than left guessing at a 403.
                return 403, json.dumps({"error": {
                    "code": "capability_required", "capability": "approve",
                    "detail": "this device may not answer Guardian's questions -- "
                              "pair it again `with approve`",
                }}).encode("utf-8"), "application/json"
            prompt_id = str(query.get("rest") or "").strip("/") if isinstance(query, dict) else ""
            try:
                parsed = json.loads(body or b"{}")
                answer = str(parsed.get("answer") or "").strip()
            except (json.JSONDecodeError, AttributeError):
                return 400, b'{"error":{"code":"invalid_json"}}', "application/json"
            if not prompt_id or not answer:
                return 400, json.dumps({"error": {
                    "code": "invalid_request",
                    "detail": "POST /api/prompts/<prompt_id> with {\"answer\": \"...\"}"}}).encode("utf-8"), \
                    "application/json"
            why = await self._answer_prompt(prompt_id, answer)
            if why:
                return 409, json.dumps({"error": {"code": "not_answerable", "detail": why}}).encode("utf-8"), \
                    "application/json"
            if self._logger is not None:
                with contextlib.suppress(Exception):
                    self._logger.info("interface.prompt_answered_remotely", prompt=prompt_id, answer=answer,
                                      device=getattr(who, "name", "legacy"))
            return 200, json.dumps({"ok": True, "prompt_id": prompt_id, "answer": answer}).encode("utf-8"), \
                "application/json"

        self._prefixes.append(("POST", "/api/prompts/", _prompt_answer))

        async def _action(query, body, headers):
            """POST /api/action -- ask Sim to do one thing.

            Through `_run_for_page`, which proposes a tool "the way the
            terminal does: a proposal Guardian sees, the result read back".
            So a phone gains no privilege the voice channel has not already
            got, and Guardian is untouched.

            Two gates, and the second is the one that is easy to miss:
            the `control` capability, and `ACTION_TOOLS`. Guardian decides
            whether an effect may happen; this decides what may be ASKED.
            """
            if self._run_for_page is None:
                return 404, b'{"error":{"code":"no_tools"}}', "application/json"
            who = self.caller(headers, query)
            if not self.may(who, "control"):
                return 403, json.dumps({"error": {
                    "code": "capability_required", "capability": "control",
                    "detail": "this device may not control the house -- pair it again `with control`",
                }}).encode("utf-8"), "application/json"
            try:
                parsed = json.loads(body or b"{}")
                tool = str(parsed.get("tool") or "").strip()
                args = parsed.get("args") or {}
            except (json.JSONDecodeError, AttributeError):
                return 400, b'{"error":{"code":"invalid_json"}}', "application/json"
            if not isinstance(args, dict):
                return 400, b'{"error":{"code":"invalid_args","detail":"args must be an object"}}', "application/json"
            if tool not in ACTION_TOOLS:
                # By name, so somebody reading the failure knows whether
                # they mistyped or asked for something this door does not
                # open.
                return 403, json.dumps({"error": {
                    "code": "not_over_the_wire",
                    "detail": f"{tool!r} is not a tool a device may ask for",
                }}).encode("utf-8"), "application/json"
            status, payload, kind = await self._run_for_page(tool, args, 60.0)
            if self._logger is not None:
                with contextlib.suppress(Exception):
                    self._logger.info("interface.device_action", tool=tool,
                                      device=getattr(who, "name", "legacy"), status=status)
            return status, payload, kind

        self.register_route("POST", "/api/action", _action, max_body=8192, rate=(120, 60.0))
        self.register_route("POST", "/api/dash/state", _dash_state_post, max_body=4096, rate=(120, 60.0))
        self.register_route("GET", "/remote", _remote, auth=False)
        self.register_route("GET", "/logo.png", _logo, auth=False)
        self.register_route("GET", "/favicon.ico", _logo, auth=False)
        self.register_route("GET", "/api/dash/banner", _banner, auth=False)

        async def _run_for_page(tool: str, args: dict, timeout: float) -> tuple[int, bytes, str]:
            # The page asks for a tool the way the terminal does: a proposal
            # Guardian sees, the result read back (interface/dispatch.py).
            import uuid

            from .dispatch import _run_tool

            # The page's own calls -- a camera rotation's signalling, the
            # strip kept live -- are plumbing, not something Sim did. Their
            # results stay out of the activity feed the TV's Sim box reads
            # (the creator, 2026-09-14: two cam_stream lines on the TV).
            action_id = uuid.uuid4().hex[:12]
            if not isinstance(self._page_actions, set):
                self._page_actions = set()
            self._page_actions.add(action_id)
            outcome = await _run_tool(bus=self._bus, ledger=self._ledger, tool=tool, raw=json.dumps(args),
                                      session_id="dash", timeout=timeout, action_id=action_id)
            text = outcome.text or ""
            # The terminal's runner appends "  (1234 ms)" to a result that
            # took a while. Ring's signalling always does, so the JSON the
            # page needed never parsed and came back wrapped as {"text":
            # ...} -- the Ring tiles showed no live view (2026-09-13).
            text = re.sub(r"\s*\(\d+ ms\)\s*$", "", text)
            body: dict
            try:
                parsed = json.loads(text)
                body = parsed if isinstance(parsed, dict) else {"text": text}
            except ValueError:
                body = {"text": text}
            failed = text.startswith(("refused", "error", "Guardian denied")) or "did not finish" in text
            body.setdefault("ok", not failed)
            return (200 if not failed else 502), json.dumps(body).encode("utf-8"), "application/json"

        async def _cameras_live(_query, _body, _headers):
            # The strip wants every Reolink camera live: relays for the
            # dashboard, the TV's page untouched (cam_stream mode dash).
            status, body, kind = await _run_for_page("cam_stream", {"camera": "all", "mode": "dash"}, 90.0)
            self._cameras_live_last = {"at": self._now(), "text": json.loads(body).get("text", "")}
            return status, body, kind

        self._run_for_page = _run_for_page

        async def _cameras_main(_query, body, _headers):
            # One camera opened full screen on the dashboard: its full-resolution relay (`start`), and back to the
            # light sub streams when the page closes it (`stop`) -- the TV decodes only a couple of videos at once.
            try:
                asked = json.loads(body.decode("utf-8") or "{}")
            except ValueError:
                return 400, b'{"error": "body must be JSON"}', "application/json"
            if not isinstance(asked, dict) or not str(asked.get("camera") or "").strip():
                return 400, b'{"error": "camera is needed"}', "application/json"
            action = str(asked.get("action") or "start").strip().lower()
            if action not in ("start", "stop"):
                return 400, b'{"error": "action is start or stop"}', "application/json"
            camera = str(asked["camera"]).strip()[:80]
            args = {"camera": camera, "mode": "dash" if action == "start" else "stop", "quality": "main"}
            return await _run_for_page("cam_stream", args, 30.0)

        async def _youtube_to_tv(_query, body, _headers):
            # The dashboard's video, handed to the TV itself: cast_play full screen gives a YouTube page to the TV's
            # own YouTube app when paired (the creator, 2026-09-14: the embedded player does not play on the TV).
            try:
                asked = json.loads(body.decode("utf-8") or "{}")
            except ValueError:
                return 400, b'{"error": "body must be JSON"}', "application/json"
            video = str(asked.get("video") or "").strip() if isinstance(asked, dict) else ""
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
                return 400, b'{"error": "video is a YouTube video id"}', "application/json"
            args = {"url": f"https://www.youtube.com/watch?v={video}", "mode": "full"}
            title = str(asked.get("title") or "").strip()[:120]
            if title:
                args["title"] = title
            return await _run_for_page("cast_play", args, 60.0)

        self.register_route("POST", "/api/dash/cameras/main", _cameras_main, max_body=1024, rate=(30, 60.0))
        self.register_route("POST", "/api/dash/youtube", _youtube_to_tv, max_body=1024, rate=(20, 60.0))

        async def _streams(_query, _body, _headers):
            # The strip's own poll: what is live, and the stills -- small
            # enough to ask every ten seconds, unlike the whole snapshot.
            if self._feeds is None:
                body = {"now": self._now(), "off": True, "streams": [], "cameras": [], "ring_cameras": []}
            else:
                body = {"now": self._now(), "streams": self._feeds.streams(), "cameras": self._feeds.cameras(),
                        "ring_cameras": self._feeds.ring_cameras(), "asked": self._cameras_live_last}
            # The page is up, so any Ring session it opened is still
            # being watched. This poll already happens every ten
            # seconds for the strip's own sake, so liveness costs no
            # extra request and still comes from the browser rather
            # than from an assumption -- and the per-camera keep-alive
            # that used to be a gated action every twenty seconds is
            # gone (`domains/home/ring.py::KEEPALIVE_EVERY_S`).
            from simorgh.contracts.home import live

            live.watching(time.monotonic())
            return 200, json.dumps(body, default=str).encode("utf-8"), "application/json"

        self.register_route("GET", "/api/dash/streams", _streams, auth=True)

        async def _ring_live(_query, body, _headers):
            try:
                asked = json.loads(body.decode("utf-8") or "{}")
            except ValueError:
                return 400, b'{"error": "body must be JSON"}', "application/json"
            if not isinstance(asked, dict) or not asked.get("camera"):
                return 400, b'{"error": "camera is needed"}', "application/json"
            args = {k: asked[k] for k in ("camera", "action", "sdp", "session") if k in asked}
            return await _run_for_page("ring_live", args, 30.0)

        self.register_route("POST", "/api/dash/cameras/live", _cameras_live, max_body=1024, rate=(4, 60.0))
        self.register_route("POST", "/api/dash/ring/live", _ring_live, max_body=65536, rate=(120, 60.0))
        self.register_route("GET", "/api/tv/state", _tv_state)
        self.register_route("GET", "/api/tv/speech", _tv_speech)

        async def _hook(query, body, headers, *, name: str = ""):
            # An inbound webhook: whoever asked something to call this
            # (`cam_watch`) listens for `ui.hook.received` with its name.
            if not name.strip():
                return 400, b"a hook needs a name: /api/hooks/<name>", "text/plain; charset=utf-8"
            await self._bus.publish(Message.new(topics.UI_HOOK_RECEIVED, source="interface", payload={
                "name": name, "body": body.decode("utf-8", errors="replace")[:_MAX_BODY_BYTES],
                "content_type": headers.get("content-type", ""), "remote": headers.get("x-remote", "")}))
            return 200, b"ok", "text/plain; charset=utf-8"

        async def _hls(query, _body, _headers, *, rest: str = ""):
            target = (self._hls_root / rest).resolve()
            if not rest or not str(target).startswith(str(self._hls_root) + os.sep) or not target.is_file():
                return 404, b"no such stream", "text/plain; charset=utf-8"
            kind = "application/vnd.apple.mpegurl" if target.suffix == ".m3u8" else "video/mp2t"
            return 200, target.read_bytes(), kind

        async def _media(_query, _body, headers, *, rest: str = ""):
            # A framed YouTube video as a file (media/tvmedia.py). The
            # TV's <video> asks in ranges; a whole 33 MB body in one go
            # plays too, but seeking and resuming need 206.
            name = rest.split("/", 1)[0].split("?", 1)[0]
            target = (self._media_root / name).resolve()
            if (not name or "/" in rest.rstrip("/") or not str(target).startswith(str(self._media_root) + os.sep)
                    or target.suffix.lower() != ".mp4" or not target.is_file()):
                return 404, b"no such video", "text/plain; charset=utf-8"
            size = target.stat().st_size
            start, end = 0, size - 1
            wanted = str(headers.get("range") or "").strip()
            partial = False
            if wanted.startswith("bytes="):
                first, _, last = wanted[6:].partition("-")
                try:
                    start = int(first) if first else max(0, size - int(last))
                    end = min(size - 1, int(last)) if (first and last) else size - 1
                    partial = True
                except ValueError:
                    start, end, partial = 0, size - 1, False
                if start >= size or start > end:
                    return 416, b"", "text/plain; charset=utf-8", (f"Content-Range: bytes */{size}",)
            with target.open("rb") as handle:
                handle.seek(start)
                body = handle.read(end - start + 1)
            extra = ("Accept-Ranges: bytes",)
            if partial:
                return 206, body, "video/mp4", extra + (f"Content-Range: bytes {start}-{end}/{size}",)
            return 200, body, "video/mp4", extra

        self._prefixes.append(("POST", "/api/hooks/", _hook))
        self._prefixes.append(("GET", "/tv/hls/", _hls))
        self._prefixes.append(("GET", "/tv/media/", _media))

        async def _wall(query, _body, _headers, *, rest: str = ""):
            import mimetypes
            from urllib.parse import unquote

            name = unquote(rest.split("/", 1)[0].split("?", 1)[0])
            target = (self._wallpaper_root / name).resolve()
            if (not name or "/" in rest.rstrip("/") or not str(target).startswith(str(self._wallpaper_root) + os.sep)
                    or not target.is_file() or target.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".avif")):
                return 404, b"no such wallpaper", "text/plain; charset=utf-8"
            kind = mimetypes.guess_type(str(target))[0] or "image/jpeg"
            return 200, target.read_bytes(), kind

        self._prefixes.append(("GET", "/wallpapers/", _wall))

        async def _snap(query, _body, _headers, *, rest: str = ""):
            # `/cameras/snap/<camera>` (Reolink stills) or
            # `/cameras/snap/ring/<camera>`: the newest JPEG whose name
            # starts with the camera's safe name. Open on the LAN like
            # the HLS segments: the Cast receiver sends no header.
            parts = [p for p in rest.split("?", 1)[0].split("/") if p]
            if not parts or any(p in (".", "..") for p in parts):
                return 404, b"no such camera", "text/plain; charset=utf-8"
            folder = self._snapshot_root
            if parts[0] == "ring" and len(parts) > 1:
                folder, parts = folder / "ring", parts[1:]
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", "/".join(parts)).strip("_")
            folder = folder.resolve()
            if not safe or not folder.is_dir() or not str(folder).startswith(str(self._snapshot_root)):
                return 404, b"no such camera", "text/plain; charset=utf-8"
            newest = None
            for f in folder.iterdir():
                if f.suffix.lower() in (".jpg", ".jpeg") and (f.name == f"{safe}.jpg" or f.name.startswith(f"{safe}-")):
                    if newest is None or f.stat().st_mtime > newest.stat().st_mtime:
                        newest = f
            if newest is None:
                return 404, b"no still yet", "text/plain; charset=utf-8"
            return 200, newest.read_bytes(), "image/jpeg"

        self._prefixes.append(("GET", "/cameras/snap/", _snap))
        self.register_route("GET", "/api/history", _json_route(self._history_json))
        self.register_route("GET", "/api/logs", _json_route(self._logs_json))
        self.register_route("GET", "/api/benchmarks", _json_route(self._benchmarks_json))
        self.register_route("GET", "/api/activity", _json_route(self._activity_json))

        async def _streams(_query, _body, _headers):
            return 200, await self._streams_json(), "application/json"

        self.register_route("GET", "/api/streams", _streams)
        # 30 chats a minute is far above any human at a keyboard and far
        # below what it takes to keep the single in-flight turn occupied.
        self.register_route("POST", "/api/chat", self._chat_route,
                            max_body=_MAX_BODY_BYTES, rate=(30, 60.0))

    def _authorized(self, headers: dict[str, str], query: dict | None = None) -> bool:
        """No token configured means no gate -- the local, single-viewer
        dashboard this server shipped as. With a token configured, only
        `Authorization: Bearer <token>` passes -- or, for a page that
        cannot set a header (the TV, handed a URL), `?token=<token>` --
        compared in constant time so the comparison itself cannot be
        used to guess the token a character at a time."""
        if not self._token:
            # No token configured: fine on this machine, where the only
            # caller is the person at the keyboard; on any other bind a
            # gated route is refused rather than served to the whole
            # LAN. Set SIM_API_TOKEN to serve them (2026-09-19).
            return self.loopback_bind
        return self.caller(headers, query) is not None

    def caller(self, headers: dict[str, str], query: dict | None = None):
        """Who is asking: a paired `Device`, the string `"legacy"` for the
        shared token, or None.

        Routes that only read need `_authorized`. A route that DOES
        something needs to know which capabilities the caller holds, and
        that is what this returns -- stage 12 items 3 and 3a check
        `approve` and `control` against it.

        The device book is tried FIRST, so revoking a phone takes effect
        even in a household that still has the shared token set. The legacy
        token keeps working because the TV page, the dashboard and every
        existing script hold it; it resolves as a caller with every
        capability, and a household that has paired its devices can unset
        it.
        """
        offered = self._offered_token(headers, query)
        if not offered:
            return None
        if self._devices is not None:
            device = self._devices.resolve(offered)
            if device is not None:
                return device
        if self._token and hmac.compare_digest(offered, self._token):
            return "legacy"
        return None

    def _offered_token(self, headers: dict[str, str], query: dict | None = None) -> str:
        """The token this request carries: a bearer header, or `?token=` for
        a page that cannot set one (the TV, handed a URL)."""
        supplied = headers.get("authorization", "")
        scheme, _, value = supplied.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
        return (self._q1(query or {}, "token", "") or "").strip()

    @staticmethod
    def may(who, capability: str) -> bool:
        """Whether `caller()`'s answer holds `capability`. The legacy shared
        token holds every one of them -- it always did, and narrowing it
        here would break the TV to no benefit; pairing devices is the way
        out of it."""
        if who == "legacy":
            return True
        return bool(who is not None and getattr(who, "may", None) and who.may(capability))

    @staticmethod
    def _local_viewer(writer: asyncio.StreamWriter, headers: dict[str, str]) -> bool:
        """This machine's own browser: a loopback peer that asked for a
        loopback host. The `Host` check keeps a web page that rebinds its
        own DNS name to 127.0.0.1 from being handed the token."""
        peer = writer.get_extra_info("peername")
        try:
            address = ipaddress.ip_address(peer[0])
        except (TypeError, IndexError, ValueError):
            return False
        mapped = getattr(address, "ipv4_mapped", None)
        if not (address.is_loopback or (mapped is not None and mapped.is_loopback)):
            return False
        host = headers.get("host", "").strip().lower()
        name = host[1:host.find("]")] if host.startswith("[") else host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        return name in ("127.0.0.1", "localhost", "::1")

    def _rate_limited(self, route: Route) -> bool:
        if route.rate is None:
            return False
        limit, window = route.rate
        now = time.monotonic()
        hits = self._rate_hits.setdefault(f"{route.method} {route.path}", deque())
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            return True
        hits.append(now)
        return False

    @property
    def loopback_bind(self) -> bool:
        """True when only this machine can reach the server."""
        return self._host.strip().lower() in ("127.0.0.1", "localhost", "::1")

    @property
    def requires_token(self) -> bool:
        """Whether this server is gated. `sec_self` (domain 4) reports
        it, and Interface warns at boot when this is False on a
        non-loopback bind."""
        return bool(self._token)

    def _now(self) -> float:
        return self._clock() if self._clock is not None else time.time()

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self.port}/"

    @property
    def port(self) -> int:
        if self._server is not None and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self._port

    async def start(self) -> None:
        self._turn_sub = await self._bus.subscribe(topics.TURN_COMPLETED, self._on_turn_completed)
        self._tv_sub = await self._bus.subscribe(topics.TV_STATE, self._on_tv_state)
        self._tv_speech_sub = await self._bus.subscribe(topics.TV_SPEECH, self._on_tv_speech)
        self._dash_sub = await self._bus.subscribe(topics.DASH_STATE, self._on_dash_state)
        self._dash_key_sub = await self._bus.subscribe(topics.UI_DASH_KEY, self._on_dash_key)
        if self._feeds is not None:
            await self._feeds.start()
        if self._cameras_live and self._feeds is not None:
            self._cameras_live_task = asyncio.create_task(self._keep_cameras_live(), name="dash-cameras-live")
        # Live activity feed (07-post-cutover-review.md §3.9): the same
        # events the REPL narrates, kept in a small in-memory ring so
        # `/api/activity` answers "what is Sim doing right now / just did"
        # from the bus as it happens -- no Ledger scan across hundreds of
        # `task:*` streams, no polling of counters that can't answer it.
        self._activity_subs = [
            await self._bus.subscribe(t, self._on_activity)
            for t in (topics.TASK_STARTED, topics.TASK_STEP, topics.TASK_COMPLETED, topics.TASK_FAILED,
                      topics.TASK_BLOCKED, topics.ACTION_RESULT, topics.ACTION_DENIED, topics.TURN_COMPLETED,
                      topics.PERCEPT_TEXT_RECEIVED)
        ]
        self._server = await asyncio.start_server(self._handle, self._host, self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._cameras_live_task is not None:
            self._cameras_live_task.cancel()
            try:
                await self._cameras_live_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._cameras_live_task = None
        if self._feeds is not None:
            await self._feeds.stop()
        if self._dash_sub is not None:
            await self._dash_sub.unsubscribe()
            self._dash_sub = None
        if self._dash_key_sub is not None:
            await self._dash_key_sub.unsubscribe()
            self._dash_key_sub = None
        if self._turn_sub is not None:
            await self._turn_sub.unsubscribe()
            self._turn_sub = None
        for sub in getattr(self, "_activity_subs", []):
            await sub.unsubscribe()
        self._activity_subs = []

    async def _on_turn_completed(self, message: Message) -> None:
        fut = self._pending_chats.get(message.payload.get("session_id", ""))
        if fut is not None and not fut.done():
            fut.set_result(message.payload)

    async def _keep_cameras_live(self) -> None:
        """Ask Execution for the strip's relays after boot, and again while
        none is live; give up for this boot once the answer is that the
        cameras are not set up (no NVR, no ffmpeg)."""
        await asyncio.sleep(self._cameras_live_delay_s)
        while not self._cameras_live_gave_up:
            try:
                live = any(s.get("live") for s in self._feeds.streams())
                if not live:
                    _status, body, _kind = await self._run_for_page("cam_stream", {"camera": "all", "mode": "dash"}, 90.0)
                    text = str(json.loads(body).get("text", ""))
                    self._cameras_live_last = {"at": self._now(), "text": text}
                    if "not set up" in text or "not installed" in text or "Guardian denied" in text:
                        self._cameras_live_gave_up = True
                        if self._logger is not None:
                            self._logger.info("dash_cameras_live_stopped", detail=text[:160])
            except Exception as exc:  # noqa: BLE001 -- the loop outlives one bad answer
                if self._logger is not None:
                    self._logger.info("dash_cameras_live_failed", error=f"{exc.__class__.__name__}: {exc}")
            await asyncio.sleep(self._cameras_live_every_s)

    _DASH_VIEWS = ("home", "cameras", "markets", "charts", "ambient")
    #: News, Discover, Terminal and Media were folded into Home (2026-09-14); the old names still land somewhere
    _VIEW_ALIASES = {"news": "home", "discover": "home", "terminal": "home", "deck": "home", "media": "home"}

    def _static_page(self, name: str) -> str:
        """A static page, re-read when the file on disk has changed."""
        path = _STATIC_DIR / name
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return self._page_cache.get(name, (0.0, ""))[1]
        cached = self._page_cache.get(name)
        if cached is None or cached[0] != stamp:
            try:
                cached = (stamp, path.read_text(encoding="utf-8"))
            except OSError:
                return cached[1] if cached else ""
            self._page_cache[name] = cached
        return cached[1]

    def _page_build(self) -> float:
        """When the dashboard's own source last changed, so a page that
        is ALREADY on the TV can notice and reload itself.

        Without it, a fix to `dash.html` reaches the television only
        when somebody re-casts it, and a Cast receiver in a living room
        is the last screen anybody thinks to refresh.
        """
        try:
            return round((_STATIC_DIR / "dash.html").stat().st_mtime, 3)
        except OSError:
            return 0.0

    def _apply_dash_state(self, payload: dict) -> None:
        view = str(payload.get("view") or "").strip().lower()
        aliases = {"deck": "home", "start": "home", "stocks": "markets", "market": "markets", "camera": "cameras",
                   "cams": "cameras", "clock": "ambient", "screensaver": "ambient", "tv": "media", "video": "media"}
        view = aliases.get(view, view)
        view = self._VIEW_ALIASES.get(view, view)
        if view and view in self._DASH_VIEWS:
            self._dash_state["view"] = view
        tf = str(payload.get("timeframe") or "").strip().upper()
        if tf in ("1D", "1W", "1M", "1Y"):
            self._dash_state["timeframe"] = tf
        if "symbol" in payload:
            self._dash_state["symbol"] = str(payload.get("symbol") or "").strip().upper()[:12]
        if "rotate_s" in payload:
            try:
                self._dash_state["rotate_s"] = max(0, min(3600, int(float(payload.get("rotate_s") or 0))))
            except (TypeError, ValueError, OverflowError):
                pass
        if "scale" in payload:
            # 0 = fit the viewport; else a fixed factor for a receiver that misreports its size.
            try:
                self._dash_state["scale"] = max(0.0, min(4.0, float(payload.get("scale") or 0)))
            except (TypeError, ValueError, OverflowError):
                pass
        if "camera" in payload:
            # Which camera is shown FULL SCREEN, by name -- "" for none.
            # A Ring camera cannot be relayed by ffmpeg (no RTSP), so
            # before this the only way to fill the screen with one was
            # to press `ok` on its tile with the remote.
            self._dash_state["camera"] = str(payload.get("camera") or "").strip()[:60]
        if "live_max" in payload:
            # How many camera feeds decode at once; the TV's browser also plays the ambient video.
            try:
                self._dash_state["live_max"] = max(0, min(16, int(float(payload.get("live_max") or 0))))
            except (TypeError, ValueError, OverflowError):
                pass
        if "live_step_s" in payload:
            # The live window slides one camera every this many seconds. Started at 1 s (the creator, 2026-09-13);
            # that is shorter than an HLS segment takes to fetch and decode, so no camera ever produced a frame to
            # show or to keep as its still when it rotated out -- every tile just went blank (2026-09-14). 6 s
            # gives a real stream time to catch up; `tv live 3 <seconds>` overrides it.
            try:
                self._dash_state["live_step_s"] = max(0.5, min(600.0, float(payload.get("live_step_s") or 6.0)))
            except (TypeError, ValueError, OverflowError):
                pass
        quality = str(payload.get("video_quality") or "").strip().lower()
        if quality in ("light", "full"):
            self._dash_state["video_quality"] = quality
        if "video_sound" in payload:
            # The embedded videos' sound, on by default (the creator, 2026-09-14).
            raw = payload.get("video_sound")
            self._dash_state["video_sound"] = raw if isinstance(raw, bool) else str(raw).strip().lower() in ("1", "true", "on", "yes")
        self._dash_state["since"] = self._now()

    async def _on_dash_state(self, message: Message) -> None:
        self._apply_dash_state(dict(message.payload or {}))

    def _push_dash_key(self, key: str) -> int:
        self._dash_key_seq += 1
        self._dash_keys.append({"seq": self._dash_key_seq, "key": key, "at": self._now()})
        return self._dash_key_seq

    async def _on_dash_key(self, message: Message) -> None:
        key = str((message.payload or {}).get("key") or "").strip().lower()
        if key in DASH_KEYS:
            self._push_dash_key(key)

    _ACTIVITY_MAX = 200
    #: This server's own tool calls still awaiting a result; per instance
    #: (see `_run_for_page`), never shared between servers.
    _page_actions: frozenset | set = frozenset()

    # Tools whose own result is internal plumbing, not something a person
    # reads: `ring_live`'s `output` is a raw WebRTC SDP blob (hundreds of
    # characters of `\r\n`-joined protocol lines), called on every camera
    # rotation of the dashboard's own live grid -- shown verbatim in the
    # dashboard's Sim-TUI box, it drowned out everything else there (the
    # creator, 2026-09-14, a photo of the Home tab: "what are these
    # messages on dash -> home tab -> sim tui?").
    _ACTIVITY_SILENT_TOOLS = frozenset({"ring_live"})

    async def _on_activity(self, message: Message) -> None:
        p = message.payload
        entry = {"ts": self._now(), "type": message.type, "task_id": p.get("task_id") or p.get("session_id", "")}
        if message.type == topics.TASK_STEP:
            if p.get("tool") in self._ACTIVITY_SILENT_TOOLS:
                return
            entry.update(step_no=p.get("step_no"), phase=p.get("phase"), summary=p.get("summary", ""),
                         tool=p.get("tool"), ok=p.get("ok"))
        elif message.type == topics.TASK_COMPLETED:
            entry.update(summary=(p.get("result_summary") or "")[:160])
        elif message.type in (topics.TASK_FAILED, topics.TASK_BLOCKED):
            entry.update(summary=p.get("reason", ""))
        elif message.type == topics.ACTION_RESULT:
            if p.get("action_id") in self._page_actions:
                self._page_actions.discard(p.get("action_id"))
                return
            if p.get("tool") in self._ACTIVITY_SILENT_TOOLS:
                return
            entry.update(action_id=p.get("action_id"), ok=p.get("ok"), duration_ms=p.get("duration_ms"),
                         summary=(p.get("error") or p.get("stdout_preview") or "")[:160])
        elif message.type == topics.ACTION_DENIED:
            if p.get("action_id") in self._page_actions:
                self._page_actions.discard(p.get("action_id"))
                return
            if p.get("tool") in self._ACTIVITY_SILENT_TOOLS:
                return
            entry.update(action_id=p.get("action_id"), ok=False, summary="denied: " + "; ".join(p.get("reasons", [])))
        elif message.type == topics.TURN_COMPLETED:
            entry.update(summary=(p.get("text") or "")[:160], floor=p.get("floor", False))
        elif message.type == topics.PERCEPT_TEXT_RECEIVED:
            entry.update(summary=(p.get("text") or "")[:160], channel=p.get("channel"))
        activity = getattr(self, "_activity", None)
        if activity is None:
            self._activity = activity = []
        activity.append(entry)
        if len(activity) > self._ACTIVITY_MAX:
            del activity[: len(activity) - self._ACTIVITY_MAX]

    async def _activity_json(self, query: dict) -> bytes:
        # The only unguarded `int()` on this server: `?limit=abc` raised
        # ValueError and answered HTTP 500 with the raw Python message
        # as the body, while `/api/logs` and `/api/history` both fall
        # back. And the clamp had no floor, so `?limit=0` sliced
        # `items[-0:]` -- the whole ring -- and `?limit=-2` sliced
        # `items[2:]`, returning everything EXCEPT the two oldest
        # (observer, 2026-09-10).
        try:
            requested = int(self._q1(query, "limit", "50") or 50)
        except ValueError:
            requested = 50
        limit = max(1, min(requested, self._ACTIVITY_MAX))
        items = list(getattr(self, "_activity", []))[-limit:]
        items.reverse()  # newest first
        pending = sorted(self._pending_chats)
        return json.dumps({"now": self._now(), "pending_turns": pending, "events": items}).encode("utf-8")

    # -- connection handling -----------------------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # The outer ceiling has to cover the slowest legitimate route
        # (chat, up to `chat_timeout_s`) plus real margin -- header
        # parsing itself is negligible in practice, so this isn't
        # trading away slow-loris protection, just not bounding a real
        # in-flight answer to a fixed 10s (the exact class of bug
        # `chat_reply_timeout_s`/`think_timeout_s` had elsewhere).
        try:
            await asyncio.wait_for(self._handle_one(reader, writer), timeout=self._chat_timeout + 15.0)
        except (asyncio.TimeoutError, ConnectionError):
            pass
        except Exception as exc:  # noqa: BLE001 -- one bad request must never take the server down
            await self._try_respond(writer, 500, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    async def _handle_one(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request_line = await reader.readline()
        if not request_line:
            return
        headers: dict[str, str] = {}
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            name, _, value = line.decode("latin-1").partition(":")
            if value:
                headers[name.strip().lower()] = value.strip()

        try:
            method, path, _version = request_line.decode("latin-1").strip().split(" ", 2)
        except ValueError:
            await self._try_respond(writer, 400, b"bad request", "text/plain; charset=utf-8")
            return

        split = urlsplit(path)
        query = parse_qs(split.query)
        route = self._routes.get((method, split.path))
        prefix_extra: dict = {}
        if route is None:
            for p_method, prefix, handler in self._prefixes:
                if method == p_method and split.path.startswith(prefix):
                    rest = split.path[len(prefix):]
                    open_ = prefix in _OPEN_PREFIXES
                    route = Route(method=method, path=split.path, handler=handler, auth=not open_,
                                  max_body=_MAX_BODY_BYTES if method == "POST" else None, rate=None)
                    prefix_extra = {"name": rest.split("/", 1)[0]} if prefix == "/api/hooks/" else {"rest": rest}
                    break
        if route is None:
            # A method this server does not speak at all is 405; a path
            # that simply does not route for a method it does speak is
            # 404 for that combination. That distinction predates the
            # route table and is asserted by its own tests.
            if method not in ("GET", "POST"):
                await self._try_respond(writer, 405, b"method not allowed", "text/plain; charset=utf-8")
            else:
                await self._try_respond(writer, 404, b"not found", "text/plain; charset=utf-8")
            return

        if (method == "GET" and split.path == "/dash" and self._token and not self._q1(query, "token", "")
                and self._local_viewer(writer, headers)):
            # A browser on this machine opened the plain address. The TV
            # is handed a URL with the token; without it the page's own
            # activity requests are refused and its Sim box shows only a
            # warning (the creator, 2026-09-14: "the dash on tv and the
            # dash on local browser show two different sim tui messages").
            query_items = [(k, v) for k, vals in query.items() for v in vals] + [("token", self._token)]
            location = "/dash?" + urlencode(query_items)
            await self._try_respond(writer, 302, b"", "text/plain; charset=utf-8",
                                    extra_headers=(f"Location: {location}",))
            return

        if route.auth and not self._authorized(headers, query):
            await self._try_respond(writer, 401, _UNAUTHORIZED, "application/json",
                                    extra_headers=('WWW-Authenticate: Bearer realm="simorgh"',))
            return

        if self._rate_limited(route):
            limit, window = route.rate
            body = json.dumps({"error": {
                "code": "rate_limited",
                "detail": f"more than {limit} requests to {route.path} in {window:.0f}s"}}).encode("utf-8")
            await self._try_respond(writer, 429, body, "application/json")
            return

        body_bytes = b""
        if method == "POST":
            if not self._origin_allowed(headers):
                await self._try_respond(writer, 403, b'{"error":"cross-origin request rejected"}',
                                        "application/json")
                return
            try:
                length = int(headers.get("content-length", "0"))
            except ValueError:
                await self._try_respond(writer, 400, b'{"error":"bad content-length"}', "application/json")
                return
            cap = route.max_body if route.max_body is not None else self._max_body_bytes
            if length < 0 or length > cap:
                await self._try_respond(writer, 413, b'{"error":"message too large"}', "application/json")
                return
            try:
                body_bytes = await reader.readexactly(length) if length else b""
            except asyncio.IncompleteReadError:
                await self._try_respond(writer, 400, b'{"error":"truncated body"}', "application/json")
                return

        result = await route.handler(query, body_bytes, headers, **prefix_extra)
        status, payload, content_type = result[0], result[1], result[2]
        # A handler may add response headers as a fourth element (the
        # video route's Content-Range).
        await self._try_respond(writer, status, payload, content_type,
                                extra_headers=tuple(result[3]) if len(result) > 3 else ())

    async def _benchmarks_json(self, query: dict) -> bytes:
        """Benchmark runs for the dashboard's accuracy-over-time chart --
        the same records `benchmark history` draws in braille."""
        payload = {"suite": self._q1(query, "suite", "") or "", "limit": 200}
        req = Message.new(topics.BENCHMARK_HISTORY_REQUEST, source="interface", payload=payload,
                          clock=self._clock)
        try:
            reply = await self._bus.request_or_error(req, timeout=self._timeout)
            body = reply.payload
        except Exception as exc:  # noqa: BLE001 -- an absent subsystem is an empty chart, not a 500
            body = {"runs": [], "error": {"code": "benchmarks_unavailable", "detail": str(exc)}}
        return json.dumps(body, default=str).encode("utf-8")

    #: What an unauthenticated caller may see of the status reply when a
    #: token is configured: that the system is up, and what it is doing
    #: at the coarsest level. Never counters, never task ids.
    _PUBLIC_STATUS_KEYS = ("state", "mode", "uptime_seconds", "autonomous_paused", "version", "uptime_s", "started_at", "error")

    async def _status_json(self, *, public_only: bool = False) -> bytes:
        req = Message.new(topics.SYSTEM_STATUS_REQUEST, source="interface", payload={}, clock=self._clock)
        try:
            reply = await self._bus.request_or_error(req, timeout=self._timeout)
            payload = reply.payload
        except Exception as exc:  # noqa: BLE001 -- an unreachable kernel is data for the page, not a crash
            payload = {"state": "unknown", "error": {"code": "status_unavailable", "detail": str(exc)}}
        if public_only:
            payload = {k: v for k, v in payload.items() if k in self._PUBLIC_STATUS_KEYS}
        return json.dumps(payload, default=str).encode("utf-8")

    def _origin_allowed(self, headers: dict[str, str]) -> bool:
        """Cross-origin CSRF guard for the one route with a real side
        effect. This is a local, unauthenticated dashboard (module
        docstring) -- reachable to any process on 127.0.0.1, which
        normally just means "this machine's own user," except a browser
        tab is also on 127.0.0.1 from the server's point of view. A page
        the creator has open in another tab can fire a same-origin-free
        "simple request" (no CORS preflight is required for a POST whose
        `Content-Type` is `text/plain`, `application/x-www-form-urlencoded`,
        or `multipart/form-data` -- the body content is never actually
        checked against that header, so a page can still send JSON text
        with one of those headers) and, with zero auth anywhere on this
        server, have it accepted exactly like a real dashboard click --
        silently starting a chat turn, which the rest of the system can
        turn into a real, tool-using task once Guardian approves it
        (`simorgh.toml`'s `[guardian]` `auto_approve` default).

        Browsers always attach `Origin` on a cross-site request
        regardless of `mode` (including `no-cors`, which is exactly
        what a fire-and-forget CSRF attempt would use, since it never
        needs to read the response) -- so a present, mismatching
        `Origin` is a reliable cross-origin signal. Its absence (curl,
        a script, any non-browser client) is not a CSRF vector -- those
        callers are trusted the same as any other local process talking
        to a local API, same posture as every other route here."""
        origin = headers.get("origin")
        if not origin:
            return True
        allowed = {f"http://{self._host}:{self.port}", f"http://localhost:{self.port}",
                   f"http://127.0.0.1:{self.port}"}
        # Bound to 0.0.0.0 and reached by its LAN address (the phone
        # remote at /remote, the dashboard on the TV), a same-origin
        # POST carries `Origin: http://192.168.x.y:8765` -- the page's
        # own host, which is exactly what `Host` says. Same-origin is
        # Origin == scheme + Host; a cross-site page cannot forge Host.
        host = headers.get("host", "").strip()
        if host and origin == f"http://{host}":
            return True
        return origin in allowed

    async def _chat_route(self, _query: dict, body: bytes, _headers: dict) -> tuple[int, bytes, str]:
        """POST /api/chat. The body has already been read and capped by
        the dispatcher, and the cross-origin check has already run --
        this decides only what the message means."""
        try:
            parsed = json.loads(body or b"{}")
            text = str(parsed.get("text", "")).strip()
            client_session_id = parsed.get("session_id")
            client_session_id = str(client_session_id).strip() if client_session_id else None
        except (json.JSONDecodeError, AttributeError):
            return 400, b'{"error":"invalid json"}', "application/json"
        if not text:
            return 400, b'{"error":"empty message"}', "application/json"
        if client_session_id and not is_valid_stream(f"task:{client_session_id}"):
            # Refused at the door, because the failure downstream is
            # silent. A session id the Ledger cannot make a stream name
            # from -- a slash, a space, an uppercase letter, anything
            # over the length cap -- ran the whole turn, got a real
            # answer, and then raised inside the worker's `_report`
            # where nothing retrieves the exception: `turn.completed`
            # was never published and the caller waited out the full
            # chat timeout to be told "no response in time" (observer,
            # 2026-09-10). A client sending uppercase UUIDs would meet
            # a two-minute silence in production config.
            return 400, json.dumps({"error": {
                "code": "invalid_session_id",
                "detail": f"session_id must be usable as a stream name: {stream_name_rule()}",
            }}).encode("utf-8"), "application/json"

        payload = await self._chat(text, session_id=client_session_id)
        status = 409 if payload.get("error") == "turn already in flight" else 200
        return status, json.dumps(payload).encode("utf-8"), "application/json"

    async def _chat(self, text: str, *, session_id: str | None = None) -> dict:
        """One dashboard chat turn: publish `percept.text.received` and
        await the matching `turn.completed` -- the same request/await-a-
        correlated-event shape `Interface._handle_chat` already uses for
        the REPL.

        `session_id` is optional and, when a caller supplies one, is
        reused as-is rather than replaced -- 02-system-architecture.md
        section 6.1's own multi-session direction: Memory's episodic
        write (milestone 105) groups turns by exactly this field, so a
        client that wants a real, continuous conversation (not a fresh
        stranger every message) sends the same id every time. The
        dashboard page does this automatically (one id generated per
        page load). When no caller supplies one, a fresh uuid is
        generated, preserving milestone 106's original fix (never a
        *shared, hardcoded* key).

        A second, real risk that fix didn't have to consider: an
        externally-supplied session_id could legitimately collide if a
        client fires two requests for the same conversation before the
        first resolves. Milestone 106's bug was a fixed key being
        silently overwritten mid-flight, corrupting which reply answered
        which prompt; the fix there was "never share a key." Now that a
        caller can ask to share one on purpose, silently overwriting is
        exactly as wrong as it was then -- so this refuses the second
        request outright (a clear `"turn already in flight"` error,
        HTTP 409) instead of ever letting two futures alias the same
        dict entry. The dashboard's own UI already serializes one tab's
        sends (the input is disabled while a reply is pending), so this
        only ever fires for a genuinely concurrent caller, not normal use.
        `channel: "api"` -- the wire enum (`percept.text.received`'s
        `channel`) is closed (`cli|api|chat|command`); a live-caught bug
        used `"dashboard"` here originally and every publish 500'd on
        real contract validation (milestone 116)."""
        session_id = session_id or str(uuid.uuid4())
        if session_id in self._pending_chats:
            return {"text": "", "floor": True, "error": "turn already in flight"}
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending_chats[session_id] = fut
        try:
            await self._bus.publish(Message.new(
                topics.PERCEPT_TEXT_RECEIVED, source="interface",
                payload={"channel": "api", "text": text, "session_id": session_id},
                clock=self._clock,
            ))
            try:
                turn = await asyncio.wait_for(fut, timeout=self._chat_timeout)
                return {"text": turn.get("text", ""), "floor": bool(turn.get("floor", False))}
            except asyncio.TimeoutError:
                return {"text": "", "floor": True, "error": "no response in time"}
        finally:
            self._pending_chats.pop(session_id, None)

    async def _on_tv_speech(self, message) -> None:
        p = message.payload
        self._tv_speech.append((int(p.get("seq") or 0), str(p.get("ref") or ""), float(p.get("seconds") or 0.0),
                                self._now()))

    async def _on_tv_state(self, message) -> None:
        p = message.payload
        self._tv_state = {"mode": str(p.get("mode") or "none"), "url": str(p.get("url") or ""),
                          "title": str(p.get("title") or ""), "urls": list(p.get("urls") or []),
                          "titles": list(p.get("titles") or []), "since": self._now(),
                          # a framed YouTube video as a file for the TV's own player (media/tvmedia.py):
                          # where it is, or why it is not coming, or that it is on its way
                          "stream": str(p.get("stream") or ""), "problem": str(p.get("problem") or ""),
                          "fetching": bool(p.get("fetching")), "native": str(p.get("native") or ""),
                          "queue": [str(t) for t in (p.get("queue") or [])][:20]}

    @staticmethod
    def _q1(query: dict, key: str, default: str | None) -> str | None:
        values = query.get(key)
        return values[0] if values else default

    async def _read_tail(self, stream: str, cap: int) -> list:
        """The last `cap` events of `stream`, oldest first. `head()` is
        `LedgerClient`-specific (not part of the narrower
        `contracts.protocols.Ledger` every subsystem is typed against),
        but Interface's `ctx.ledger` is always a real `LedgerClient` in
        practice -- same duck-typing `kernel/scheduler.py`'s own
        `materialize()` call already relies on. Falls back to reading
        from the start and slicing when a caller's `ledger` (a test
        fake, most likely) doesn't have it."""
        head = getattr(self._ledger, "head", None)
        if head is not None:
            total = await head(stream)
            start = max(1, total - cap + 1)
            return await self._ledger.read(stream, from_seq=start, limit=cap)
        events = await self._ledger.read(stream, from_seq=0, limit=None)
        return events[-cap:]

    async def _history_json(self, query: dict) -> bytes:
        subsystem = self._q1(query, "subsystem", None)
        if not subsystem:
            return json.dumps({"error": {"code": "missing_subsystem",
                                          "detail": "subsystem query param is required"}}).encode("utf-8")
        try:
            minutes = float(self._q1(query, "minutes", None) or self._history_default_minutes)
        except ValueError:
            minutes = self._history_default_minutes
        minutes = max(0.5, min(minutes, 24 * 60.0))
        cutoff = self._now() - minutes * 60.0
        series = getattr(self._telemetry, "series", None)
        if series is not None:
            try:
                rows = (await series("metrics.history", since=cutoff))[-self._history_max_points:]
            except Exception:  # noqa: BLE001 -- fall through to the ledger
                rows = []
            if rows:
                points = []
                for row in rows:
                    entry = ((row.get("value") or {}).get("metrics") or {}).get(subsystem)
                    if entry is not None:
                        points.append({"ts": row["ts"], "counters": entry.get("counters", {}),
                                       "gauges": entry.get("gauges", {})})
                return json.dumps({"subsystem": subsystem, "minutes": minutes, "points": points},
                                  default=str).encode("utf-8")
        if self._ledger is None:
            return json.dumps({"subsystem": subsystem, "minutes": minutes, "points": [],
                                "error": {"code": "ledger_unavailable"}}).encode("utf-8")
        try:
            events = await self._read_tail(self._history_stream, self._history_max_points)
        except Exception as exc:  # noqa: BLE001 -- a bad read is data for the page, not a crash
            return json.dumps({"subsystem": subsystem, "minutes": minutes, "points": [],
                                "error": {"code": "history_unavailable", "detail": str(exc)}}).encode("utf-8")
        cutoff = self._now() - minutes * 60.0
        points = []
        for event in events:
            if event.ts is not None and event.ts < cutoff:
                continue
            entry = (event.payload.get("metrics") or {}).get(subsystem)
            if entry is None:
                continue
            points.append({"ts": event.ts, "counters": entry.get("counters", {}), "gauges": entry.get("gauges", {})})
        return json.dumps({"subsystem": subsystem, "minutes": minutes, "points": points},
                          default=str).encode("utf-8")

    async def _logs_json(self, query: dict) -> bytes:
        stream = self._q1(query, "stream", "system")
        try:
            limit = int(self._q1(query, "limit", None) or self._logs_default_limit)
        except ValueError:
            limit = self._logs_default_limit
        limit = max(1, min(limit, self._logs_max_limit))
        if self._ledger is None:
            return json.dumps({"stream": stream, "events": [],
                                "error": {"code": "ledger_unavailable"}}).encode("utf-8")
        try:
            events = await self._read_tail(stream, limit)
        except Exception as exc:  # noqa: BLE001 -- a bad read is data for the page, not a crash
            return json.dumps({"stream": stream, "events": [],
                                "error": {"code": "logs_unavailable", "detail": str(exc)}}).encode("utf-8")
        body = {"stream": stream, "events": [
            {"seq": e.seq, "ts": e.ts, "type": e.type, "trace_id": e.trace_id,
             "causation_id": e.causation_id, "payload": e.payload}
            for e in events
        ]}
        return json.dumps(body, default=str).encode("utf-8")

    async def _streams_json(self) -> bytes:
        if self._ledger is None:
            return json.dumps({"streams": [], "error": {"code": "ledger_unavailable"}}).encode("utf-8")
        try:
            names = await self._ledger.streams("")
        except Exception as exc:  # noqa: BLE001 -- a bad read is data for the page, not a crash
            return json.dumps({"streams": [], "error": {"code": "streams_unavailable",
                                                          "detail": str(exc)}}).encode("utf-8")
        return json.dumps({"streams": names}).encode("utf-8")

    async def _try_respond(self, writer: asyncio.StreamWriter, status: int, body: bytes, content_type: str,
                           *, extra_headers: tuple[str, ...] = ()) -> None:
        extra = "".join(f"{line}\r\n" for line in extra_headers)
        headers = (
            f"HTTP/1.1 {status} {_REASONS.get(status, '')}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "Cache-Control: no-store\r\n"
            f"{extra}"
            "\r\n"
        ).encode("latin-1")
        writer.write(headers + body)
        await writer.drain()


__all__ = ["HttpApi", "Route", "RouteHandler"]

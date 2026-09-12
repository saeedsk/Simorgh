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
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlsplit

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.streamnames import is_valid_stream, stream_name_rule

_STATIC_DIR = Path(__file__).resolve().parent / "static"

_REASONS = {
    200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
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
_OPEN_ROUTES: frozenset[str] = frozenset({"/", "/api/status", "/tv", "/dash", "/api/wallpapers", "/api/dash/data",
                                          "/api/dash/state", "/remote"})

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


class HttpApi:
    def __init__(
        self, bus, *, ledger=None, host: str = "127.0.0.1", port: int = 8765,
        clock=None, status_timeout_s: float = 3.0, chat_timeout_s: float = 130.0,
        history_stream: str = "metrics:history", history_default_minutes: float = 10.0,
        history_max_points: int = 500, logs_default_limit: int = 100, logs_max_limit: int = 500,
        token: str = "", max_body_bytes: int = 1_000_000, logger=None, feeds=None,
    ) -> None:
        self._bus = bus
        self._ledger = ledger
        self._token = (token or "").strip()
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
        self._history_default_minutes = history_default_minutes
        self._history_max_points = max(1, history_max_points)
        self._logs_default_limit = logs_default_limit
        self._logs_max_limit = max(1, logs_max_limit)
        self._server: asyncio.base_events.Server | None = None
        self._page = (_STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")
        # Sim on the TV (interface/static/tv.html): a replica of the
        # terminal, and what to frame in it (`tv.state`, published by the
        # cast tools in execution/media/cast.py).
        self._tv_page = (_STATIC_DIR / "tv.html").read_text(encoding="utf-8")
        self._dash_page = (_STATIC_DIR / "dash.html").read_text(encoding="utf-8")
        self._tv_state: dict = {"mode": "none", "url": "", "title": "", "since": 0.0}
        self._tv_sub = None
        self._tv_speech: deque = deque(maxlen=40)   # (seq, ref, seconds, at): Sim's voice for the page
        self._tv_speech_sub = None
        # The glass dashboard's collector (interface/dashfeeds.py), or
        # None when `[interface] dash_feeds = false`: `/api/dash/data`
        # then answers an empty snapshot that says the feeds are off.
        self._feeds = feeds
        # Where the dashboard should look (`ui.dash.state`): set by the
        # `dash_view` tool or the phone remote, polled by the page.
        self._dash_state: dict = {"view": "", "timeframe": "", "symbol": "", "rotate_s": 0, "since": 0.0}
        self._dash_sub = None
        self._remote_page = (_STATIC_DIR / "remote.html").read_text(encoding="utf-8")
        # The newest camera still per camera (execution/home/cameras.py
        # writes `workspace/cameras/<name>-<stamp>.jpg`; ring.py the same
        # under workspace/cameras/ring/), for the dashboard's tiles.
        self._snapshot_root = (Path.cwd() / "workspace" / "cameras").resolve()
        # Live camera video for the TV page (execution/home/cameras.py
        # writes HLS under workspace/cameras/hls/<channel>/). Served on
        # the LAN without the token: the Cast receiver fetches segments
        # with no header and no query of its own.
        self._hls_root = (Path.cwd() / "workspace" / "cameras" / "hls").resolve()
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
            return 200, self._page.encode("utf-8"), "text/html; charset=utf-8"

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
            return 200, self._tv_page.encode("utf-8"), "text/html; charset=utf-8"

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
            return 200, self._dash_page.encode("utf-8"), "text/html; charset=utf-8"

        async def _wallpapers(_query, _body, _headers):
            names = []
            root = self._wallpaper_root
            if root.is_dir():
                names = sorted(f.name for f in root.iterdir()
                               if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".avif") and not f.name.startswith("."))
            return 200, json.dumps({"wallpapers": names}).encode("utf-8"), "application/json"

        async def _dash_data(_query, _body, _headers):
            if self._feeds is None:
                body = {"now": self._now(), "off": True, "feeds": {}, "markets": None, "news": {}}
            else:
                body = self._feeds.snapshot()
            return 200, json.dumps(body, default=str).encode("utf-8"), "application/json"

        async def _dash_state_get(_query, _body, _headers):
            return 200, json.dumps({"now": self._now(), **self._dash_state}).encode("utf-8"), "application/json"

        async def _dash_state_post(query, body, headers):
            # The phone remote (`/remote?token=`): gated like every other
            # side effect (the token, in the header or the query).
            try:
                asked = json.loads(body.decode("utf-8") or "{}")
            except ValueError:
                return 400, b'{"error": "body must be JSON"}', "application/json"
            if not isinstance(asked, dict):
                return 400, b'{"error": "body must be a JSON object"}', "application/json"
            payload = {k: asked[k] for k in ("view", "timeframe", "symbol", "rotate_s") if k in asked}
            self._apply_dash_state(payload)
            await self._bus.publish(Message.new(topics.DASH_STATE, source="interface", payload=payload))
            return 200, json.dumps({"now": self._now(), **self._dash_state}).encode("utf-8"), "application/json"

        async def _remote(_query, _body, _headers):
            return 200, self._remote_page.encode("utf-8"), "text/html; charset=utf-8"

        self.register_route("GET", "/dash", _dash, auth=False)
        self.register_route("GET", "/api/wallpapers", _wallpapers, auth=False)
        self.register_route("GET", "/api/dash/data", _dash_data, auth=False)
        self.register_route("GET", "/api/dash/state", _dash_state_get, auth=False)
        self.register_route("POST", "/api/dash/state", _dash_state_post, max_body=4096, rate=(120, 60.0))
        self.register_route("GET", "/remote", _remote, auth=False)
        self.register_route("GET", "/api/tv/state", _tv_state)
        self.register_route("GET", "/api/tv/speech", _tv_speech)

        async def _hook(query, body, headers, *, name: str = ""):
            # An inbound webhook: whoever asked something to call this
            # (`cam_watch`) listens for `ui.hook.received` with its name.
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

        self._prefixes.append(("POST", "/api/hooks/", _hook))
        self._prefixes.append(("GET", "/tv/hls/", _hls))

        async def _wall(query, _body, _headers, *, rest: str = ""):
            import mimetypes
            name = rest.split("/", 1)[0].split("?", 1)[0]
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
            return True
        supplied = headers.get("authorization", "")
        scheme, _, value = supplied.partition(" ")
        if scheme.lower() == "bearer" and hmac.compare_digest(value.strip(), self._token):
            return True
        from_query = self._q1(query or {}, "token", "") or ""
        return bool(from_query) and hmac.compare_digest(from_query.strip(), self._token)

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
        if self._feeds is not None:
            await self._feeds.start()
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
        if self._feeds is not None:
            await self._feeds.stop()
        if self._dash_sub is not None:
            await self._dash_sub.unsubscribe()
            self._dash_sub = None
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

    _DASH_VIEWS = ("home", "discover", "cameras", "news", "markets", "media", "terminal", "ambient")

    def _apply_dash_state(self, payload: dict) -> None:
        view = str(payload.get("view") or "").strip().lower()
        aliases = {"deck": "home", "start": "home", "stocks": "markets", "market": "markets", "camera": "cameras",
                   "cams": "cameras", "clock": "ambient", "screensaver": "ambient", "tv": "media", "video": "media"}
        view = aliases.get(view, view)
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
            except (TypeError, ValueError):
                pass
        self._dash_state["since"] = self._now()

    async def _on_dash_state(self, message: Message) -> None:
        self._apply_dash_state(dict(message.payload or {}))

    _ACTIVITY_MAX = 200

    async def _on_activity(self, message: Message) -> None:
        p = message.payload
        entry = {"ts": self._now(), "type": message.type, "task_id": p.get("task_id") or p.get("session_id", "")}
        if message.type == topics.TASK_STEP:
            entry.update(step_no=p.get("step_no"), phase=p.get("phase"), summary=p.get("summary", ""),
                         tool=p.get("tool"), ok=p.get("ok"))
        elif message.type == topics.TASK_COMPLETED:
            entry.update(summary=(p.get("result_summary") or "")[:160])
        elif message.type in (topics.TASK_FAILED, topics.TASK_BLOCKED):
            entry.update(summary=p.get("reason", ""))
        elif message.type == topics.ACTION_RESULT:
            entry.update(action_id=p.get("action_id"), ok=p.get("ok"), duration_ms=p.get("duration_ms"),
                         summary=(p.get("error") or p.get("stdout_preview") or "")[:160])
        elif message.type == topics.ACTION_DENIED:
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
                    open_ = prefix in ("/tv/hls/", "/wallpapers/", "/cameras/snap/")
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

        status, payload, content_type = await route.handler(query, body_bytes, headers, **prefix_extra)
        await self._try_respond(writer, status, payload, content_type)

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
    _PUBLIC_STATUS_KEYS = ("state", "version", "uptime_s", "started_at", "error")

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
                          "titles": list(p.get("titles") or []), "since": self._now()}

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

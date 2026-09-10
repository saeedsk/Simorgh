"""A Home Assistant REST client, in the standard library.

HA's REST API is a JSON API with a bearer token: `GET /api/states`,
`POST /api/services/<domain>/<service>`, `GET /api/history/period/...`.
`urllib` does all of it, and contracts may not import anything else
(`tests/simorgh/test_module_boundaries.py` rule 2). The result is that
the entire house integration adds no dependency at all.

The WebSocket half -- subscribing to `state_changed` and turning it
into percepts -- belongs to the `home` subsystem when that is built,
and needs a real WebSocket library. It is deliberately not here: a
client that half-subscribes would be worse than one that plainly does
not.

Construction never raises and never opens a socket. A missing token is
something `probe()` reports (the `Connector` contract), because a house
that is not set up yet must not stop Sim booting.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from .api import Entity, ServiceResult


class HomeUnavailable(RuntimeError):
    """Home Assistant could not be reached or refused. The message is
    for a person and never carries the token -- a URL with a token in
    it ends up in a ToolResult and then in the Ledger."""


class HomeAssistantClient:
    def __init__(self, *, url: str = "", token: str = "", timeout_s: float = 10.0,
                 opener=None, dry_run: bool = False) -> None:
        self.url = (url or "").rstrip("/")
        self._token = token or ""
        self._timeout = timeout_s
        self._opener = opener or urllib.request.urlopen
        self.dry_run = dry_run
        self.name = "home_assistant"
        self.needs: tuple[str, ...] = ("HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN")
        self.packages: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        return bool(self.url and self._token)

    def missing(self) -> tuple[str, ...]:
        out = []
        if not self.url:
            out.append("HOME_ASSISTANT_URL")
        if not self._token:
            out.append("HOME_ASSISTANT_TOKEN")
        return tuple(out)

    # -- Connector protocol --------------------------------------------------

    async def probe(self):
        from ..connector import ConnectorStatus

        missing = self.missing()
        if missing:
            return ConnectorStatus(
                False, "not configured", missing,
                fix="set " + " and ".join(missing)
                    + " (a long-lived access token from your HA profile page)")
        try:
            payload = await self._get("/api/")
        except HomeUnavailable as exc:
            return ConnectorStatus(False, f"home assistant: {exc}", ())
        message = str((payload or {}).get("message", ""))
        if "running" not in message.lower():
            return ConnectorStatus(False, f"home assistant answered unexpectedly: {message[:80]}")
        return ConnectorStatus(True, f"home assistant is running at {self.url}")

    async def close(self) -> None:
        return None

    # -- reading -------------------------------------------------------------

    async def states(self) -> list[Entity]:
        payload = await self._get("/api/states")
        if not isinstance(payload, list):
            return []
        return [_entity(row) for row in payload if isinstance(row, dict)]

    async def state(self, entity_id: str) -> Entity | None:
        try:
            payload = await self._get(f"/api/states/{urllib.parse.quote(entity_id)}")
        except HomeUnavailable:
            return None
        return _entity(payload) if isinstance(payload, dict) else None

    async def services(self) -> dict[str, set[str]]:
        """`{"light": {"turn_on", "turn_off", ...}, ...}`.

        Used to refuse a service HA does not have *before* calling it.
        HA answers 200 and does nothing for an unknown service, which is
        the single most confusing failure in this whole integration.
        """
        payload = await self._get("/api/services")
        out: dict[str, set[str]] = {}
        if isinstance(payload, list):
            for row in payload:
                if isinstance(row, dict) and row.get("domain"):
                    out[str(row["domain"])] = set((row.get("services") or {}).keys())
        return out

    async def history(self, entity_id: str, *, hours: float = 24.0) -> list[dict]:
        from datetime import datetime, timedelta, timezone

        start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        path = (f"/api/history/period/{urllib.parse.quote(start)}"
                f"?filter_entity_id={urllib.parse.quote(entity_id)}")
        payload = await self._get(path)
        if isinstance(payload, list) and payload and isinstance(payload[0], list):
            return [row for row in payload[0] if isinstance(row, dict)]
        return []

    # -- acting --------------------------------------------------------------

    async def call(self, service: str, *, entity_ids: tuple[str, ...] = (), data: dict | None = None,
                   settle_s: float = 1.0) -> ServiceResult:
        """Call a service and report what the HOUSE did.

        HA answers 200 for a service call on a device that is unplugged,
        so the call succeeding and something happening are different
        facts. This re-reads the entities afterwards and says which of
        them actually moved.
        """
        import asyncio

        domain, _, name = service.partition(".")
        if not domain or not name:
            raise HomeUnavailable(f"{service!r} is not a domain.service name")

        before = {}
        for entity_id in entity_ids:
            entity = await self.state(entity_id)
            if entity is not None:
                before[entity_id] = entity

        if self.dry_run:
            # Never a silent no-op: the caller is told exactly what
            # would have happened.
            return ServiceResult(service=service, entities=tuple(entity_ids), before=before,
                                 after=dict(before), dry_run=True)

        body = dict(data or {})
        if entity_ids:
            body["entity_id"] = list(entity_ids)
        await self._post(f"/api/services/{urllib.parse.quote(domain)}/{urllib.parse.quote(name)}",
                         body)

        if settle_s > 0:
            await asyncio.sleep(settle_s)
        after = {}
        for entity_id in entity_ids:
            entity = await self.state(entity_id)
            if entity is not None:
                after[entity_id] = entity
        return ServiceResult(service=service, entities=tuple(entity_ids), before=before, after=after)

    # -- plumbing ------------------------------------------------------------

    async def _get(self, path: str):
        return await self._request("GET", path, None)

    async def _post(self, path: str, body: dict):
        return await self._request("POST", path, body)

    async def _request(self, method: str, path: str, body):
        import asyncio

        if not self.configured:
            raise HomeUnavailable(
                "Home Assistant is not configured: set " + " and ".join(self.missing()))
        url = f"{self.url}{path}"
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

        def _do():
            request = urllib.request.Request(
                url, method=method, headers=headers,
                data=json.dumps(body).encode("utf-8") if body is not None else None)
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read()
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise HomeUnavailable(
                        "Home Assistant refused the token. Generate a long-lived access token "
                        "on your HA profile page and set HOME_ASSISTANT_TOKEN.") from None
                if exc.code == 404:
                    raise HomeUnavailable(f"Home Assistant has no {path}") from None
                raise HomeUnavailable(f"Home Assistant answered {exc.code}") from None
            except urllib.error.URLError as exc:
                # `exc.reason`, never the URL: it is the one string here
                # that could carry a token.
                raise HomeUnavailable(f"could not reach Home Assistant ({exc.reason})") from None
            except (socket.timeout, TimeoutError):
                raise HomeUnavailable(
                    f"Home Assistant did not answer in {self._timeout:.0f}s") from None
            if not raw:
                return None
            try:
                return json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                return None

        return await asyncio.to_thread(_do)


def _entity(row: dict) -> Entity:
    return Entity(entity_id=str(row.get("entity_id") or ""), state=str(row.get("state") or ""),
                  attributes=dict(row.get("attributes") or {}),
                  last_changed=str(row.get("last_changed") or ""))


__all__ = ["HomeAssistantClient", "HomeUnavailable"]

"""Home Assistant, relayed onto the tailnet, for the phone away from home.

The app's Home Assistant tab is a web view on Home Assistant's own address
(`HOME_ASSISTANT_URL`, a LAN address like 192.168.50.208:8123). The Mac is
on the tailnet; the Home Assistant VM is not. So at home the tab worked,
and over Tailscale it showed nothing while everything that goes through
Sim worked (the creator, 2026-09-27).

This is a plain TCP relay -- bytes both ways, so Home Assistant's
websocket and its own login work unchanged -- listening ONLY on the Mac's
tailnet address, so it adds nothing to the LAN, where Home Assistant is
reachable anyway. `/api/house/assistant` hands its address to a phone that
reached Sim over the tailnet.
"""

from __future__ import annotations

import asyncio
import contextlib
from urllib.parse import urlsplit

#: The relay's port on the tailnet address. 8123 is Home Assistant's own;
#: one above it says what it is to anybody reading a URL.
RELAY_PORT = 8124


class HomeAssistantRelay:
    def __init__(self, target_url: str, listen_host: str, *, port: int = RELAY_PORT, log=None) -> None:
        parts = urlsplit(target_url)
        self._target = (parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80))
        self._scheme = parts.scheme or "http"
        self._host = listen_host
        self.port = int(port)
        self._log = log
        self._server: asyncio.base_events.Server | None = None
        self.detail = ""

    @property
    def running(self) -> bool:
        return self._server is not None

    async def start(self) -> bool:
        if not self._target[0] or not self._host:
            self.detail = "not relayed: no Home Assistant address, or no tailnet address here"
            return False
        try:
            self._server = await asyncio.start_server(self._serve, self._host, self.port)
        except OSError as exc:
            self.detail = f"not relayed: {self._host}:{self.port} -- {exc}"
            return False
        self.detail = f"Home Assistant relayed on {self._host}:{self.port} -> {self._target[0]}:{self._target[1]}"
        if self._log is not None:
            self._log("info", "interface.ha_relayed", listen=f"{self._host}:{self.port}",
                      target=f"{self._target[0]}:{self._target[1]}")
        return True

    def url_for(self, host: str) -> str:
        """The relay as a phone reaching Sim by `host` (its tailnet name or
        address) should open it."""
        return f"{self._scheme}://{host}:{self.port}"

    async def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            with contextlib.suppress(Exception):
                await server.wait_closed()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(*self._target), timeout=10)
        except (OSError, asyncio.TimeoutError):
            writer.close()
            return

        async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while data := await src.read(65536):
                    dst.write(data)
                    await dst.drain()
            except (OSError, ConnectionError):
                pass
            finally:
                with contextlib.suppress(Exception):
                    dst.close()

        await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))


def on_tailnet(host_header: str) -> str:
    """The host a request came in on, when that is the tailnet (a MagicDNS
    name or a 100.x address); "" otherwise."""
    host = (host_header or "").strip()
    if host.startswith("["):
        return ""
    host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    if host.endswith(".ts.net") or host.startswith("100."):
        return host
    return ""


__all__ = ["HomeAssistantRelay", "RELAY_PORT", "on_tailnet"]

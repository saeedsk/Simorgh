"""WebRTC camera streaming, with the tool Home Assistant uses.

The creator, 2026-09-25: "its interesting how ha stream the video, it with
high quality, easy to handle, flips in full screen, can you get idea from
ha and use same technology?" -- and the answer to what HA uses is go2rtc.
His HA has it loaded; it is how the Reolink integration gets a picture on a
phone in half a second.

Why it is not a matter of tuning the HLS relay: `cameras._relay` writes
2-second MPEG-TS segments and a player needs about three of them buffered
before it can start, so the floor is roughly six seconds and no flag moves
it. go2rtc pulls the same RTSP and republishes it as WebRTC -- no
transcode, no segments, no disk -- and falls back to fMP4-over-WebSocket by
itself when UDP cannot get through. Measured on the creator's NVR before
any of this was written: one frame out of `camera.office`'s main stream at
4512x2512, straight through.

Optional, probed, and named when missing, the rule every voice engine
follows. The binary is a single static file from the project's releases,
fetched the way a whisper model is fetched -- never bundled, never a hard
dependency, and a house without it keeps the HLS relay it already had.

Bound to LOOPBACK on purpose. `/tv/hls/` was open to the whole LAN until
2026-09-19 and that let anyone on it watch the house (S15/V2); a second
video server with its own port and no token would be that mistake again,
so Interface proxies it behind Sim's own token instead.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

#: Where the binary lives once fetched. Beside the other fetched models
#: rather than in the repository.
BIN_DIR = Path("workspace/bin")
BINARY = "go2rtc"
#: Loopback: Interface is the only thing that should be able to reach it.
HOST = "127.0.0.1"
API_PORT = 1984
#: WebRTC media. The one port that must be reachable BY THE PHONE, because
#: media is peer-to-peer and does not go through the proxy. Over a tailnet
#: it is reachable; where it is not, go2rtc's own player falls back to
#: fMP4 over the WebSocket, which the proxy does carry.
WEBRTC_PORT = 8555

#: The project publishes one static binary per platform.
RELEASES = "https://github.com/AlexxIT/go2rtc/releases/latest/download"
ASSETS = {
    ("Darwin", "arm64"): "go2rtc_mac_arm64.zip",
    ("Darwin", "x86_64"): "go2rtc_mac_amd64.zip",
    ("Linux", "x86_64"): "go2rtc_linux_amd64",
    ("Linux", "aarch64"): "go2rtc_linux_arm64",
    ("Linux", "armv7l"): "go2rtc_linux_arm",
}


def asset_for(system: str, machine: str) -> str:
    """The release asset for a platform, or "" when there is none."""
    return ASSETS.get((system, machine), "")


def binary_path(root: Path) -> Path:
    return root / BIN_DIR / BINARY


def found(root: Path) -> str:
    """The go2rtc to use: the fetched one, else one already on PATH, else
    "". An existing install is preferred to downloading a second copy."""
    mine = binary_path(root)
    if mine.is_file() and os.access(mine, os.X_OK):
        return str(mine)
    return shutil.which(BINARY) or ""


def install(root: Path, *, system: str, machine: str, log=None) -> tuple[str, str]:
    """Fetch the binary. Returns (path, problem); one of them is empty.

    Separate from `start` so a house that would rather not download
    anything simply never calls it, and so the download is a step
    somebody can see.
    """
    asset = asset_for(system, machine)
    if not asset:
        return "", (f"no go2rtc release for {system}/{machine} -- the HLS relay still works; "
                    f"see {RELEASES}")
    target = binary_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"{RELEASES}/{asset}"
    if log:
        log(f"fetching {url}")
    try:
        with urllib.request.urlopen(url, timeout=300) as response:  # noqa: S310 -- a literal https release URL
            payload = response.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return "", f"could not fetch go2rtc: {exc!r}"
    if asset.endswith(".zip"):
        import io
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                name = next((n for n in archive.namelist() if n.rstrip("/").endswith(BINARY)), "")
                if not name:
                    return "", f"{asset} did not contain a {BINARY} binary"
                target.write_bytes(archive.read(name))
        except (zipfile.BadZipFile, KeyError) as exc:
            return "", f"could not unpack go2rtc: {exc!r}"
    else:
        target.write_bytes(payload)
    target.chmod(0o755)
    return str(target), ""


def config(streams: dict[str, str]) -> str:
    """go2rtc's YAML, written by Sim rather than edited by hand.

    `streams` maps a name a person would use ("office") to an RTSP URL.
    Hand-written YAML is not wanted here: the RTSP URLs carry the NVR
    password, so this file is generated, kept out of the repository, and
    written 0600.
    """
    lines = [
        "# Written by Sim (simorgh/domains/home/go2rtc.py). Do not edit:",
        "# it is rewritten whenever the camera list changes.",
        "api:",
        f'  listen: "{HOST}:{API_PORT}"',
        "  # Loopback only. Interface proxies this behind Sim's own token;",
        "  # a second video server open on the LAN is the 2026-09-19 bug.",
        "rtsp:",
        '  listen: ""',
        "webrtc:",
        f'  listen: ":{WEBRTC_PORT}"',
        "log:",
        '  level: "warn"',
        "streams:",
    ]
    for name, url in streams.items():
        lines.append(f"  {name}: {url}")
    return "\n".join(lines) + "\n"


class Go2rtc:
    """A supervised go2rtc, the way a camera relay is supervised."""

    def __init__(self, root: Path, *, binary: str = "", log=None) -> None:
        self._root = root
        self._binary = binary
        self._log = log
        self._child: subprocess.Popen | None = None
        self._streams: dict[str, str] = {}
        self.detail = ""

    @property
    def config_path(self) -> Path:
        return self._root / BIN_DIR / "go2rtc.yaml"

    @property
    def running(self) -> bool:
        return self._child is not None and self._child.poll() is None

    def write_config(self, streams: dict[str, str]) -> None:
        self._streams = dict(streams)
        path = self.config_path
        path.parent.mkdir(parents=True, exist_ok=True)
        # The RTSP URLs in here carry the NVR password: the file is created
        # 0600, never written world-readable and tightened afterwards.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(config(self._streams))
        path.chmod(0o600)                 # an older file keeps its old mode through O_TRUNC

    def start(self, streams: dict[str, str], *, timeout_s: float = 10.0) -> tuple[bool, str]:
        binary = self._binary or found(self._root)
        if not binary:
            self.detail = ("go2rtc is not installed -- `cameras webrtc install` fetches it "
                           "(one static binary); the HLS relay still works meanwhile")
            return False, self.detail
        if self.running and streams == self._streams:
            return True, self.detail
        self.stop()
        self.write_config(streams)
        try:
            self._child = subprocess.Popen(  # noqa: S603 -- a found binary, a literal argv
                [binary, "-config", str(self.config_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, start_new_session=True)
        except (OSError, subprocess.SubprocessError) as exc:
            self.detail = f"could not start go2rtc: {exc!r}"
            return False, self.detail
        # Wait for the API, not for the process: a process that is up but
        # not listening is not ready, and reporting a URL that refuses the
        # connection is the "succeeds while saying nothing true" failure.
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._child.poll() is not None:
                err = (self._child.stderr.read().decode(errors="ignore") if self._child.stderr else "").strip()
                self.detail = f"go2rtc stopped at once ({err[-200:] or 'no detail'})"
                return False, self.detail
            if self.answers():
                self.detail = f"go2rtc {self.version() or '?'} serving {len(self._streams)} camera(s)"
                if self._log:
                    self._log("info", "cameras.go2rtc_started", streams=sorted(self._streams))
                return True, self.detail
            time.sleep(0.25)
        self.stop()
        self.detail = f"go2rtc did not answer on {HOST}:{API_PORT} within {timeout_s:.0f}s"
        return False, self.detail

    def answers(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://{HOST}:{API_PORT}/api", timeout=1) as response:  # noqa: S310
                return response.status == 200
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def version(self) -> str:
        try:
            with urllib.request.urlopen(f"http://{HOST}:{API_PORT}/api", timeout=2) as response:  # noqa: S310
                return str((json.loads(response.read()) or {}).get("version") or "")
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            return ""

    def stop(self) -> None:
        child = self._child
        self._child = None
        if child is None or child.poll() is not None:
            return
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()


__all__ = ["API_PORT", "BIN_DIR", "BINARY", "HOST", "RELEASES", "WEBRTC_PORT",
           "Go2rtc", "asset_for", "binary_path", "config", "found", "install"]

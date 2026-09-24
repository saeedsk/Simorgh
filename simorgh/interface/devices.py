"""One token per device, with capabilities, and pairing by barcode.

Stage 12 item 2. Until this existed, `SIM_API_TOKEN` was ONE shared
bearer admitting every caller to a system that holds the cameras, the
door hardware, the family's mail and a model budget -- and `[interface]
http_host` is `0.0.0.0`. That is defensible on a home LAN and is not
something to hand to anybody else, which is why this lands before the
phone it was asked for: it is a prerequisite for releasing the package
at all, not a feature of the client.

Three decisions worth keeping.

**The store holds hashes, never tokens.** A device's token is shown once,
at pairing, and after that only its SHA-256 lives on disk. A leaked
`devices.json` is then a list of names and dates rather than a set of
working keys -- and there is no "show me the token again", because there
is nothing to show.

**A capability is granted, never inherited.** `read` for the console and
the house, `chat` for a conversation, `control` for the tools behind
`/api/action`, and `approve` for answering Guardian's questions. Pairing
grants read and chat; the other two need saying. The ability to authorise
an irreversible action should always be a sentence somebody said, not a
default that arrived with a scan.

**The QR carries a pairing CODE, never a token.** Single use, 120
seconds, one outstanding at a time. A photograph of the screen is worth
nothing a minute later, where a token in the QR would make a
screen-share permanent control of the house. Minting is a local call --
the REPL or a spoken turn -- and never an HTTP route, so `POST /api/pair`
can spend a code and cannot create one.

The legacy single token keeps working. The TV page, the dashboard and
every existing script hold it, and breaking them to add devices would be
the wrong trade; it resolves as a caller with every capability, named
`legacy`, and a household that pairs its devices can drop it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

#: What a device may do. Ordered from least to most consequential, which is
#: the order `voice set`-style listings should show them in.
CAPABILITIES: tuple[str, ...] = ("read", "chat", "control", "approve")

#: What a scan alone is worth. `control` and `approve` are grants.
DEFAULT_CAPABILITIES: tuple[str, ...] = ("read", "chat")

#: How long a pairing code lives. Long enough to walk to the phone and
#: open the camera, short enough that a photograph of the terminal is
#: worthless by the time anybody else sees it.
PAIRING_TTL_S = 120.0

#: Attempts against `/api/pair` before codes stop being accepted at all
#: until a new one is minted. A code is 64 bits of `token_urlsafe`, so this
#: is not what stops guessing -- it stops a flood from being free.
MAX_PAIR_ATTEMPTS = 10


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class Device:
    id: str
    name: str
    token_sha256: str
    capabilities: tuple[str, ...]
    created_at: float
    last_seen: float = 0.0
    revoked_at: float = 0.0

    @property
    def revoked(self) -> bool:
        return bool(self.revoked_at)

    def may(self, capability: str) -> bool:
        return not self.revoked and capability in self.capabilities

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "token_sha256": self.token_sha256,
                "capabilities": list(self.capabilities), "created_at": self.created_at,
                "last_seen": self.last_seen, "revoked_at": self.revoked_at}

    @classmethod
    def from_dict(cls, data: dict) -> "Device":
        return cls(id=str(data.get("id") or ""), name=str(data.get("name") or ""),
                   token_sha256=str(data.get("token_sha256") or ""),
                   capabilities=tuple(str(c) for c in (data.get("capabilities") or ())),
                   created_at=float(data.get("created_at") or 0.0),
                   last_seen=float(data.get("last_seen") or 0.0),
                   revoked_at=float(data.get("revoked_at") or 0.0))


@dataclass
class Pairing:
    """An outstanding pairing code. Not persisted: a restart should void
    it, because a code nobody is standing in front of is a code nobody
    wanted."""

    code: str
    name: str
    capabilities: tuple[str, ...]
    expires_at: float
    attempts: int = 0


def normalise(capabilities) -> tuple[str, ...]:
    """The known capabilities among those asked for, in CAPABILITIES order.

    Unknown names are DROPPED rather than refused: a client of a newer
    Sim asking for a capability this one has never heard of should get
    what it can have, and an unknown name grants nothing by definition.
    """
    wanted = {str(c).strip().lower() for c in (capabilities or ())}
    return tuple(c for c in CAPABILITIES if c in wanted)


@dataclass
class DeviceBook:
    """The devices, on disk, and the one pairing code in flight."""

    path: Path
    clock = time.time
    _devices: dict[str, Device] = field(default_factory=dict)
    _pairing: Pairing | None = None

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self._load()

    # ------------------------------------------------------------- storage
    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A missing or unreadable book is an EMPTY book, never an
            # error: the same first rule the connectors follow. A corrupt
            # file must not stop Sim booting, and it must not silently
            # admit everybody either -- an empty book admits nobody.
            self._devices = {}
            return
        rows = raw.get("devices") if isinstance(raw, dict) else raw
        self._devices = {}
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            device = Device.from_dict(row)
            if device.id and device.token_sha256:
                self._devices[device.id] = device

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.part")
        tmp.write_text(json.dumps({"devices": [d.to_dict() for d in self._devices.values()]}, indent=2),
                       encoding="utf-8")
        tmp.replace(self.path)

    # ------------------------------------------------------------- reading
    def devices(self, *, include_revoked: bool = False) -> list[Device]:
        rows = sorted(self._devices.values(), key=lambda d: d.created_at)
        return rows if include_revoked else [d for d in rows if not d.revoked]

    def resolve(self, token: str) -> Device | None:
        """The live device holding `token`, or None.

        Constant-time against every stored hash, and it does not stop at
        the first match: comparing against a subset would make the time
        taken depend on where in the book a device sits.
        """
        if not token:
            return None
        digest = _hash(token)
        found: Device | None = None
        for device in self._devices.values():
            if hmac.compare_digest(device.token_sha256, digest) and not device.revoked:
                found = device
        if found is not None:
            found.last_seen = self.clock()
            self._save()
        return found

    # ------------------------------------------------------------- writing
    def begin_pairing(self, *, name: str = "", capabilities=None) -> Pairing:
        """Mint the one outstanding code. Local callers only -- nothing on
        the HTTP surface may reach this, or the gate is no gate."""
        self._pairing = Pairing(
            code=secrets.token_urlsafe(8),
            name=" ".join(str(name or "phone").split())[:40],
            capabilities=normalise(capabilities) or tuple(DEFAULT_CAPABILITIES),
            expires_at=self.clock() + PAIRING_TTL_S,
        )
        return self._pairing

    def pending(self) -> Pairing | None:
        """The outstanding code, if it has not expired."""
        if self._pairing is None:
            return None
        if self.clock() >= self._pairing.expires_at:
            self._pairing = None
        return self._pairing

    def cancel_pairing(self) -> None:
        self._pairing = None

    def redeem(self, code: str) -> tuple[Device, str] | str:
        """`(device, token)` on success, or a sentence saying why not.

        The token is returned ONCE, here, and never stored. The failure
        reasons are deliberately specific -- an expired code and a wrong
        code are different problems for the person holding the phone, and
        neither tells an attacker anything a clock would not.
        """
        pending = self.pending()
        if pending is None:
            return "no pairing is open -- run `pair` on Sim first"
        if pending.attempts >= MAX_PAIR_ATTEMPTS:
            self._pairing = None
            return "too many attempts; that code is dead -- run `pair` again"
        pending.attempts += 1
        if not code or not hmac.compare_digest(code, pending.code):
            return "that is not the code on the screen"
        now = self.clock()
        token = secrets.token_urlsafe(32)
        device = Device(id=secrets.token_hex(8), name=pending.name, token_sha256=_hash(token),
                        capabilities=pending.capabilities, created_at=now, last_seen=now)
        self._devices[device.id] = device
        self._pairing = None          # single use
        self._save()
        return device, token

    def revoke(self, which: str) -> Device | None:
        """Revoke by id or by name. A revoked device is KEPT, not deleted:
        the record of what was paired and when is worth more than the
        tidiness, and a reused name would otherwise be indistinguishable."""
        wanted = which.strip().lower()
        for device in self.devices():
            if device.id == which or device.name.lower() == wanted:
                device.revoked_at = self.clock()
                self._save()
                return device
        return None


def pairing_url(base: str, code: str) -> str:
    """`https://host/pair#code` -- the code in the FRAGMENT, so it stays
    out of server logs, proxy logs and Referer headers on the way."""
    return f"{base.rstrip('/')}/pair#{code}"


def barcode(text: str) -> str | None:
    """`text` as a scannable QR for a terminal, or None if nothing here
    can draw one.

    `qrencode -t UTF8` first (Homebrew), then the `qrcode` package, then
    None -- and a None is the caller's cue to print the URL and the code
    instead. Pairing must never be IMPOSSIBLE because a drawing tool is
    missing, which is the same "optional, probed, refused by name" rule
    every voice engine follows. No new hard dependency.
    """
    binary = shutil.which("qrencode")
    if binary:
        try:
            done = subprocess.run([binary, "-t", "UTF8", "-m", "1", text],  # noqa: S603 -- a found binary, a literal argv
                                  capture_output=True, text=True, timeout=10, check=False)
            if done.returncode == 0 and done.stdout.strip():
                return done.stdout.rstrip("\n")
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        import qrcode  # noqa: PLC0415 -- optional
    except ImportError:
        return None
    try:
        code = qrcode.QRCode(border=1)
        code.add_data(text)
        import io

        buf = io.StringIO()
        code.print_ascii(out=buf)
        return buf.getvalue().rstrip("\n") or None
    except Exception:  # noqa: BLE001 -- a drawing that failed is a drawing we do not have
        return None


__all__ = ["CAPABILITIES", "DEFAULT_CAPABILITIES", "MAX_PAIR_ATTEMPTS", "PAIRING_TTL_S",
           "Device", "DeviceBook", "Pairing", "barcode", "normalise", "pairing_url"]

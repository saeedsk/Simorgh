"""Sim over WhatsApp: the sanctioned route, and only for the family.

The creator, 2026-09-16, by voice: "maybe i can connect you to a
whatsapp application so basically i leave you home somewhere with
internet connection but then i talk to you over whatsapp -- it's either
the whatsapp text messages or even like we have a voice conversation
over whatsapp". Then, plainly: "CHANGE THE CONTRACT AND INTRODUCE
EXTERNAL VOICE/TEXT CHANNELS LIKE WHATSAPP AND TELEGRAM".

Telegram shipped first because it needs only a bot token and an outbound
poll. WhatsApp is the one he asked for first and it costs more to stand
up: the Business Cloud API needs a Meta business account, a dedicated
number, and a webhook Meta can reach over public HTTPS. The alternative
-- driving WhatsApp Web as a personal account -- is what gets numbers
banned, and the number at risk would be the family's own. So this is the
sanctioned route or nothing.

Inbound is a webhook rather than a poll, which brings two duties
Telegram does not have, and both are security rather than plumbing:

**The verification handshake.** Meta GETs the webhook with
`hub.verify_token` and expects `hub.challenge` echoed back. Answering
that with anything other than the configured token would hand the
subscription to whoever asked.

**The signature.** Every POST carries `X-Hub-Signature-256`, an HMAC of
the raw body under the app secret. An unauthenticated webhook is a
public endpoint that starts real tool-using turns in this house, so a
body whose signature does not verify is dropped before it is parsed --
and compared with `hmac.compare_digest`, not `==`.

Then the same three rules the Telegram channel keeps: deny by default
(an allow-list that is empty admits nobody), no phone number ever on the
bus (the ledger keeps what it is given for good), and a voice note
answered rather than swallowed -- Interface may not import Voice, so
there is no transcriber to reach from here.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid

from simorgh.contracts import channels, topics
from simorgh.contracts.envelope import Message

#: Meta's Graph API. Pinned: an unpinned version changes shape underneath
#: a running house.
API_VERSION = "v21.0"
GRAPH = "https://graph.facebook.com/{version}/{phone_id}/messages"

#: WhatsApp's own body cap is 4096 characters.
MAX_REPLY = 3900


class WhatsAppChannel:
    """Receives WhatsApp messages on a webhook and answers them as Sim.

    Construction never raises and never reaches the network: without a
    token, a phone-number id and a verify token, the channel is simply
    off -- which is the state every install starts in, since the
    credentials cannot be created from here.
    """

    name = channels.WHATSAPP

    def __init__(self, bus, *, token: str, phone_id: str, verify_token: str, app_secret: str = "",
                 allowed: tuple[str, ...] = (), version: str = API_VERSION, logger=None, clock=None) -> None:
        self._bus = bus
        self._token = (token or "").strip()
        self._phone_id = (phone_id or "").strip()
        self._verify = (verify_token or "").strip()
        self._secret = (app_secret or "").strip()
        self._allowed = tuple(a for a in allowed if str(a or "").strip())
        self._version = (version or API_VERSION).strip()
        self._logger = logger
        self._clock = clock
        self._sub = None
        #: session_id -> wa_id. The number never goes on the bus.
        self._numbers: dict[str, str] = {}
        self._sessions: dict[str, str] = {}
        #: Message ids already handled: Meta retries a webhook it thinks
        #: failed, and answering the same question twice is worse than
        #: being slow.
        self._seen: list[str] = []

    @property
    def configured(self) -> bool:
        return bool(self._token and self._phone_id and self._verify)

    def why_not(self) -> str:
        missing = [name for name, value in (
            ("SIM_WHATSAPP_TOKEN", self._token),
            ("SIM_WHATSAPP_PHONE_ID", self._phone_id),
            ("SIM_WHATSAPP_VERIFY_TOKEN", self._verify)) if not value]
        if missing:
            return ("needs " + ", ".join(missing) +
                    " (WhatsApp Business Cloud API: a Meta business account and a dedicated number)")
        if not self._secret:
            return ("no SIM_WHATSAPP_APP_SECRET: the webhook cannot check Meta's signature, so it "
                    "refuses every message -- an unsigned public endpoint starts real turns in this house")
        if not self._allowed:
            return ("no [interface] whatsapp_allowed: nobody may talk to Sim here yet -- "
                    "list the phone numbers that may")
        return ""

    async def start(self) -> tuple[bool, str]:
        if not self.configured:
            return False, self.why_not()
        self._sub = await self._bus.subscribe(topics.TURN_COMPLETED, self._on_turn)
        return True, self.why_not()

    async def stop(self) -> None:
        if self._sub is not None:
            try:
                await self._sub.unsubscribe()
            except Exception:  # noqa: BLE001 -- shutdown must not raise
                pass
            self._sub = None

    # -- the webhook -------------------------------------------------------------

    def verify(self, query: dict) -> tuple[int, bytes]:
        """Meta's subscription handshake. Echo the challenge only when
        the token matches, compared in constant time."""
        def one(key: str) -> str:
            value = query.get(key)
            return (value[0] if isinstance(value, list) else value) or ""

        if one("hub.mode") == "subscribe" and self._verify and \
                hmac.compare_digest(one("hub.verify_token"), self._verify):
            return 200, one("hub.challenge").encode("utf-8")
        self._log("warning", "whatsapp.verify_refused")
        return 403, b"forbidden"

    def signed(self, body: bytes, header: str) -> bool:
        """Whether `body` really came from Meta.

        No secret means no proof, and no proof means no. An endpoint that
        accepted unsigned bodies would let anyone who finds the URL drive
        the cameras, the lights and the task queue.
        """
        if not self._secret or not header:
            return False
        expected = "sha256=" + hmac.new(self._secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, header.strip())

    async def receive(self, body: bytes, *, signature: str = "") -> tuple[int, bytes]:
        """One webhook POST. Always answers 200 to a signed body -- Meta
        retries anything else, and a retry storm helps nobody -- but only
        acts on what passes the gate."""
        if not self.signed(body, signature):
            self._log("warning", "whatsapp.bad_signature")
            return 403, b"bad signature"
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            return 400, b"bad json"
        for message, sender in _messages(payload):
            try:
                await self._on_message(message, sender)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- one bad message must not fail the batch
                self._log("warning", "whatsapp.message_failed", error=repr(exc)[:200])
        return 200, b"ok"

    async def _on_message(self, message: dict, sender: str) -> None:
        wa_id = str(message.get("from") or sender or "")
        if not channels.allowed(wa_id, self._allowed):
            # Silence. A refusal would confirm to a stranger that
            # something is here and listening.
            self._log("warning", "whatsapp.sender_refused")
            return
        mid = str(message.get("id") or "")
        if mid and mid in self._seen:
            return      # Meta retried one it thinks we failed
        if mid:
            self._seen.append(mid)
            del self._seen[:-200]

        if str(message.get("type") or "") != "text":
            kind = str(message.get("type") or "that")
            await self._send(wa_id, f"I can only read text here so far -- {kind} is not something "
                                    f"I can listen to over WhatsApp yet.")
            return
        text = str((message.get("text") or {}).get("body") or "").strip()
        if not text:
            return

        person = await self._person_for(f"whatsapp:{wa_id}", wa_id)
        session_id = self._sessions.get(wa_id)
        if session_id is None:
            session_id = str(uuid.uuid4())
            self._sessions[wa_id] = session_id
            self._numbers[session_id] = wa_id
        await self._bus.publish(Message.new(
            topics.PERCEPT_TEXT_RECEIVED, source="interface",
            payload={"channel": channels.WHATSAPP, "text": text, "session_id": session_id,
                     # Who wrote it (stage 5 item 7): this channel knows, and
                     # without it the turn is remembered under nobody's name.
                     **({"speaker": person} if person else {})},
            clock=self._clock,
        ))
        self._log("info", "whatsapp.received", chars=len(text))

    # -- answering ---------------------------------------------------------------

    async def _on_turn(self, message) -> None:
        payload = message.payload
        if str(payload.get("channel") or "") != channels.WHATSAPP:
            return
        wa_id = self._numbers.get(str(payload.get("session_id") or ""))
        if wa_id is None:
            return
        text = str(payload.get("text") or "").strip()
        if text:
            await self._send(wa_id, text)

    def _post(self, wa_id: str, text: str) -> dict:
        url = GRAPH.format(version=self._version, phone_id=self._phone_id)
        body = json.dumps({"messaging_product": "whatsapp", "to": wa_id,
                           "type": "text", "text": {"body": text}}).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers={
            "Authorization": f"Bearer {self._token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30.0) as response:  # noqa: S310
            return json.loads(response.read(200_000) or b"{}")

    async def _person_for(self, identity: str, sender: str) -> str:
        """The household name behind a number (stage 6 item 4): the
        People store first, `channels.person_for` as the fallback. A
        number nobody has claimed resolves to nothing, never to the
        number -- it must not reach the bus."""
        try:
            reply = await self._bus.request(Message.new(
                topics.WORLD_ENV_QUERY, source="interface",
                payload={"what": "people", "args": {"identity": identity}}), timeout=1.0)
            name = str(((reply.payload or {}).get("person") or {}).get("name") or "")
            if name:
                return name
        except Exception:  # noqa: BLE001 -- no world model, no link; fall back
            pass
        return channels.person_for(sender)

    async def _send(self, wa_id: str, text: str) -> None:
        if len(text) > MAX_REPLY:
            text = text[: MAX_REPLY - 3] + "..."
        try:
            # Blocking urllib in a thread: a fetch on the event loop
            # freezes every other subsystem, which this codebase has been
            # bitten by before.
            await asyncio.to_thread(self._post, wa_id, text)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # A reply that never arrives is the failure a person notices.
            # The token must never reach a log line.
            self._log("warning", "whatsapp.send_failed", error=repr(exc)[:200])

    def _log(self, level: str, event: str, **fields) -> None:
        if self._logger is None:
            return
        handler = getattr(self._logger, level, None)
        if handler is not None:
            handler(event, **fields)


def _messages(payload: dict):
    """Every message in a webhook body, with the contact it came from.

    Meta nests them three deep and batches them, and a body may carry
    only statuses (delivered, read) with no message at all.
    """
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            contacts = value.get("contacts") or []
            sender = str((contacts[0] if contacts else {}).get("wa_id") or "")
            for message in value.get("messages") or []:
                yield message, sender


__all__ = ["API_VERSION", "MAX_REPLY", "WhatsAppChannel"]

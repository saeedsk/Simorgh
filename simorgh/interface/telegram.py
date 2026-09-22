"""Sim over Telegram: the same brain, reached from a phone.

The creator, 2026-09-16, by voice: "sometimes instead of bringing my
macbook to my car to talk to you ... maybe i can connect you to a
whatsapp application so basically i leave you home somewhere with
internet connection but then i talk to you over whatsapp". Then, to
Claude Code: "CHANGE THE CONTRACT AND INTRODUCE EXTERNAL VOICE/TEXT
CHANNELS LIKE WHATSAPP AND TELEGRAM".

Telegram first, and not because it is the one he named first. WhatsApp's
sanctioned route needs a Meta business account, a dedicated number and a
publicly reachable HTTPS webhook before it can carry one message; the
unsanctioned route risks a ban on the family's own number. Telegram
needs a bot token and an outbound connection -- it works tonight, from
behind the house's router, with nothing exposed to the internet.

Nothing here is Telegram-specific to Sim: a message becomes
`percept.text.received` with `channel="telegram"`, which Orchestration
already routes (`service.py` reads `channel` off the payload) and
`profiles.for_percept` already answers with the typed-chat profile,
since only "voice" is special-cased. The reply comes back on
`turn.completed`, which carries the channel. So this file is a
translator, not a new path through the system.

Three rules it keeps.

**Deny by default.** An external channel is a remote control of this
house -- the cameras, the lights, the TV, the backlog -- offered to
whoever finds the address. `contracts/channels.allowed()` gates every
inbound message and an empty allow-list admits nobody. A stranger is
ignored in silence: answering "you are not allowed" confirms to them
that something is listening.

**No address on the bus.** The chat id lives in this object's own map,
never in a percept payload, so the family's Telegram ids stay out of the
ledger, which keeps what it is given for good.

**A voice note is not silently dropped.** Interface may not import
Voice, so there is no transcriber to reach from here; until that goes
over the bus, a voice note gets a plain answer saying so. Swallowing it
would look exactly like Sim ignoring them.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid

from simorgh.contracts import channels, topics
from simorgh.contracts.envelope import Message

API = "https://api.telegram.org/bot{token}/{method}"

#: Telegram's own cap is 4096 characters; a little under it leaves room
#: for the "..." a truncated reply ends with.
MAX_REPLY = 3900

#: Long-poll seconds. Telegram holds the connection open until a message
#: arrives or this elapses, so this is idle cost, not latency.
POLL_S = 25.0

#: After a network failure, wait before trying again -- and grow it, so a
#: token that has been revoked does not become a hot loop against
#: Telegram's API for as long as Sim is up.
BACKOFF_S = (2.0, 5.0, 15.0, 60.0)


class TelegramChannel:
    """Long-polls Telegram for messages and answers them as Sim.

    Construction never raises and never reaches the network: an absent
    token means the channel is simply off, which is the state almost
    every install is in.
    """

    name = channels.TELEGRAM

    def __init__(self, bus, *, token: str, allowed: tuple[str, ...] = (),
                 poll_s: float = POLL_S, logger=None, clock=None) -> None:
        self._bus = bus
        self._token = (token or "").strip()
        self._allowed = tuple(a for a in allowed if str(a or "").strip())
        self._poll_s = max(1.0, float(poll_s))
        self._logger = logger
        self._clock = clock
        self._offset = 0
        self._task: asyncio.Task | None = None
        self._sub = None
        #: session_id -> chat id. The address never goes on the bus.
        self._chats: dict[str, int] = {}
        #: chat id -> session_id, so one person's messages stay one
        #: conversation rather than meeting a stranger every time.
        self._sessions: dict[int, str] = {}

    # -- lifecycle ---------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def why_not(self) -> str:
        """Why the channel is not running, in words a person can act on."""
        if not self._token:
            return "no SIM_TELEGRAM_TOKEN secret: talk to @BotFather, then set it"
        if not self._allowed:
            return ("no [interface] telegram_allowed: only handles linked to a person "
                    "(`people link <name> telegram:<handle>`) may talk to Sim here")
        return ""

    async def start(self) -> tuple[bool, str]:
        if not self.configured:
            return False, self.why_not()
        self._sub = await self._bus.subscribe(topics.TURN_COMPLETED, self._on_turn)
        self._task = asyncio.create_task(self._poll_forever(), name="telegram-poll")
        return True, self.why_not()

    async def stop(self) -> None:
        if self._sub is not None:
            try:
                await self._sub.unsubscribe()
            except Exception:  # noqa: BLE001 -- shutdown must not raise
                pass
            self._sub = None
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None

    # -- Telegram's side ---------------------------------------------------------

    def _call(self, method: str, params: dict) -> dict:
        """One API call, blocking. Runs in a thread, never on the loop --
        a blocking fetch inside the event loop freezes every other
        subsystem, which this codebase has already been bitten by once."""
        url = API.format(token=self._token, method=method)
        body = urllib.parse.urlencode(params).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers={"Content-Type":
                                                                  "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(request, timeout=self._poll_s + 15.0) as response:  # noqa: S310
            return json.loads(response.read(1_000_000) or b"{}")

    async def _api(self, method: str, **params) -> dict:
        return await asyncio.to_thread(self._call, method, params)

    async def _poll_forever(self) -> None:
        failures = 0
        while True:
            try:
                payload = await self._api("getUpdates", offset=self._offset,
                                          timeout=int(self._poll_s), allowed_updates='["message"]')
                failures = 0
            except asyncio.CancelledError:
                raise
            except (urllib.error.URLError, OSError, ValueError) as exc:
                wait = BACKOFF_S[min(failures, len(BACKOFF_S) - 1)]
                failures += 1
                self._log("warning", "telegram.poll_failed", error=repr(exc)[:200], retry_in_s=wait)
                await asyncio.sleep(wait)
                continue
            for update in payload.get("result") or []:
                self._offset = max(self._offset, int(update.get("update_id") or 0) + 1)
                try:
                    await self._on_update(update)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 -- one bad message must not end the channel
                    self._log("warning", "telegram.message_failed", error=repr(exc)[:200])

    async def _on_update(self, update: dict) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = int(chat.get("id") or 0)
        if not chat_id:
            return
        sender = message.get("from") or {}
        who = str(sender.get("username") or "") or str(sender.get("id") or "")
        # Silence, not a refusal. Answering a stranger confirms that
        # something is here and listening.
        if not channels.allowed(who, self._allowed) and not await self._linked(f"telegram:{who}"):
            self._log("warning", "telegram.sender_refused", sender=channels.normalise_sender(who))
            return

        text = str(message.get("text") or "").strip()
        if not text:
            # A voice note, a photo, a sticker. Interface may not import
            # Voice, so there is no transcriber to reach from here --
            # and going quiet would look exactly like being ignored.
            kind = next((k for k in ("voice", "audio", "photo", "document", "video", "sticker")
                         if k in message), "that")
            await self._send(chat_id, f"I can only read text here so far -- {kind} is not something "
                                      f"I can listen to over Telegram yet.")
            return

        person = await self._person_for(f"telegram:{who}", who)
        session_id = self._sessions.get(chat_id)
        if session_id is None:
            session_id = str(uuid.uuid4())
            self._sessions[chat_id] = session_id
            self._chats[session_id] = chat_id
        await self._bus.publish(Message.new(
            topics.PERCEPT_TEXT_RECEIVED, source="interface",
            payload={"channel": channels.TELEGRAM, "text": text, "session_id": session_id,
                     # Who wrote it (stage 5 item 7): this channel knows, and
                     # without it the turn is remembered under nobody's name.
                     **({"speaker": person} if person else {})},
            clock=self._clock,
        ))
        self._log("info", "telegram.received", chars=len(text))

    async def _on_turn(self, message) -> None:
        payload = message.payload
        if str(payload.get("channel") or "") != channels.TELEGRAM:
            return
        chat_id = self._chats.get(str(payload.get("session_id") or ""))
        if chat_id is None:
            return      # a turn from some other conversation
        text = str(payload.get("text") or "").strip()
        if not text:
            return
        await self._send(chat_id, text)

    async def _linked(self, identity: str) -> bool:
        """Whether the People store links `identity` to a person.

        The second way in, beside `telegram_allowed` (stage 6 item 4):
        linking a handle to somebody is a tier-3 action a person
        confirms, and it was not enough to let them write -- the config
        list and the store were two answers to one question. Only a
        LINK admits: a handle that merely spells a household name does
        not, because anyone can choose that username.
        """
        return bool(await self._stored_name(identity))

    async def _stored_name(self, identity: str) -> str:
        try:
            reply = await self._bus.request(Message.new(
                topics.WORLD_ENV_QUERY, source="interface",
                payload={"what": "people", "args": {"identity": identity}}), timeout=1.0)
            return str(((reply.payload or {}).get("person") or {}).get("name") or "")
        except Exception:  # noqa: BLE001 -- no world model: no link
            return ""

    async def _person_for(self, identity: str, sender: str) -> str:
        """The household name behind a handle (stage 6 item 4).

        The People store first, because that is where a link made at
        the kitchen table lives -- "this Telegram handle is Ira" -- and
        it is the only thing that lets the same person share one memory
        namespace across channels. `channels.person_for` is the
        fallback for a handle that simply IS a household name.

        A handle nobody has claimed resolves to nothing, never to the
        handle itself: an address on the bus is an address in the
        ledger and in memory tags for ever.
        """
        return await self._stored_name(identity) or channels.person_for(sender)

    async def _send(self, chat_id: int, text: str) -> None:
        if len(text) > MAX_REPLY:
            text = text[: MAX_REPLY - 3] + "..."
        try:
            await self._api("sendMessage", chat_id=chat_id, text=text)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # A reply that never arrives is the failure a person actually
            # notices, so it is logged rather than swallowed.
            self._log("warning", "telegram.send_failed", error=repr(exc)[:200])

    def _log(self, level: str, event: str, **fields) -> None:
        if self._logger is None:
            return
        getattr(self._logger, level, None) and getattr(self._logger, level)(event, **fields)


__all__ = ["MAX_REPLY", "POLL_S", "TelegramChannel"]

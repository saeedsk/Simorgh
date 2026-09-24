# Stage 12 -- The phone client

Status: **designed, not started** (2026-09-24) · Depends on: stage 3 (streaming voice), stage 10 (companion) for the notification channel · Estimated: server 2 weeks, a web client 3 days, a native client 3 weeks after that · Modules touched: interface, voice, contracts, execution, docs

## Outcome

Sim is reachable from the creator's iPhone, at home and away: its console, the questions it needs answered, live voice, the house, and a conversation. The household keeps the laptop microphone the whole time, and a phone turn is answered in that person's ear, never out loud in the living room.

## Why this is not mainly about voice

The creator asked for live voice from the phone and then, correctly, widened it: "I believe moving toward a native iphone app is a better approach as it would [be] lot more than just a voice channel."

The single most valuable thing a phone gives Sim is not speech. It is this: **`ui.prompt` has no answer path except the terminal.**

    ui.prompt          -> prompt_id, question, options, timeout_s, default
    ui.prompt.answered -> prompt_id, answer

Both topics exist. `interface/service.py` publishes the answer when somebody types it into the REPL, and `render.prompt_banner` draws the box. There is **no HTTP route that answers a prompt** -- checked 2026-09-24. So every Guardian escalation, every `needs_human`, every irreversible action waits for a person to be sitting at that terminal. Sim's autonomy currently ends at the desk.

A phone that can answer those questions changes what Sim is. It is the difference between "autonomous while I watch" and "autonomous, and it asks me when it matters". That is the spine of this stage, and it is worth more than the voice channel it was asked for.

It is also the feature with the sharpest security consequence, which is why item 2 comes before item 3.

## The decision: the server is the product, the app is a client

A native app wins at exactly four things, and it is worth being precise about them rather than arguing in general:

| | web app on the Home Screen | native |
|---|---|---|
| console, chat, cameras, house | same | same |
| notifications | web push (iOS 16.4+, Home Screen only) or ntfy's own app | APNs, with **action buttons** -- approve/deny without opening anything |
| microphone | foreground only; suspended when backgrounded or locked | background audio, VoIP push |
| always-listening | impossible | possible, within Apple's limits |
| widgets, Siri intents, Live Activities | no | yes |
| cost | none | $99/year; a free account expires a sideloaded build every 7 days, which is useless for a household appliance |

Everything else -- remote reach, TLS, the prompt route, per-device auth, the voice socket, push registration -- is **server work that is identical whichever client exists**, and it is the bulk of the effort. So:

1. Build the server surface (items 1-5).
2. Prove it with a Home Screen web client (item 6). Days, not weeks, and it makes every server mistake visible before any Swift exists.
3. Write the native client (item 7) for the four things only it can do.

A native client and an unproven API at the same time is where this stalls. The Swift code does **not** live under `simorgh/` -- this repository is stdlib-only Python by charter -- it is a sibling project consuming a documented HTTP + WebSocket API.

## What already exists

Worth knowing before building anything, because most of the read surface is done:

| need | today |
|---|---|
| chat | `POST /api/chat` -- `{text, session_id}`; reuse one `session_id` and Memory groups the conversation |
| console | `/api/logs`, `/api/activity`, `/api/history`, `/api/streams`, `/api/status` |
| house | `/api/dash/data`, `/api/dash/streams`, `/cameras/snap/<...>`, `/tv/hls/<...>`, `/api/tv/state` |
| TV control | `/api/dash/key`, `/api/dash/keys`, and the `/remote` page |
| notifications | `execution/notify.py` -- ntfy, gotify, Home Assistant, matrix, apprise, slack, email, sms; each switched on by an environment variable, refusing and naming them when unset |
| voice transport | `voice/remote.py` (2026-09-24) -- RFC 6455 in stdlib, `RemoteMicrophone` behind the same `name`/`capture`/`stream` interface the local microphones implement, `RemoteSpeaker` that sends the voice and keeps the turn's time |
| auth | one shared `SIM_API_TOKEN` bearer, `_OPEN_ROUTES` for the pages |

What does not exist: TLS, a prompt-answer route, per-device identity, a voice session for a second listener, reply routing to a phone, and push registration.

## Items

### 1. Remote reach, with TLS

`getUserMedia` requires a secure context, so **no browser will give a page the microphone over `http://`** -- this blocks the voice work and nothing else can be tested honestly without it. The HTTP server has no TLS at all (`asyncio.start_server`, no `ssl` anywhere).

Tailscale is the recommended route and the one this plan assumes: a stable hostname, real certificates, works away from the house, and no port opened on the router. It also retires the `0.0.0.0` LAN bind that the 2026-09-18 evaluation flagged (S15/V2) -- Sim can go back to binding loopback and let the tailnet carry it.

Alternatives, for the record: a self-signed certificate with a trust profile on the phone (LAN only, Safari nags), or a Cloudflare tunnel (household audio transits a third party).

Done when: the dashboard loads over `https://` on the phone, off the home network, with no certificate warning.

### 2. Per-device tokens, before anything can approve

`SIM_API_TOKEN` is one shared 32-character bearer for every caller. That is adequate for a dashboard on the LAN and **not** adequate for a device that can approve an irreversible action: a phone left in a taxi is, today, full control of the house with no way to revoke it short of rotating the token and re-pairing everything.

So: a `devices` table in the settings home, one token per device, each with a name, a created-at, a last-seen, a revoked-at, and a **capability set**. `read` for the console and the house. `chat` for conversation. `approve` as its own capability, granted deliberately, never by default. Revoking one device must not disturb the others.

Pairing without typing a 32-character secret on a phone keyboard: the REPL prints a QR code for a short-lived pairing URL, the phone opens it once, and the server issues that device its own token.

Done when: `devices` lists and revokes; a revoked token is refused; a device without `approve` is refused the route in item 3 and told which capability it lacks.

### 3. Answering Sim's questions from anywhere

`GET /api/prompts` -- the open ones, with `prompt_id`, `question`, `options`, and the seconds left.
`POST /api/prompts/<id>` -- `{answer}`, publishing `ui.prompt.answered`, requiring the `approve` capability.

Rules that matter more than the routes:

- **The prompt's own timeout still governs.** A phone answer arriving after it has expired is refused with "that question has already timed out", never applied late. Guardian's decision has already been made by then.
- **First answer wins.** The REPL and the phone can both be looking at the same question; the second answer is told who answered and what they said, rather than silently doing nothing.
- The question text reaching a phone is the same text the terminal box shows. No summarising, and no "Sim wants to do something" -- the whole point is that the person can judge it.

Done when: an irreversible action proposed while nobody is at the terminal is approved from the phone and runs; and the same action, answered after its timeout, is refused with the reason.

### 4. Push, so a question finds the person

Two stages, deliberately.

**Now:** `notify.py` already reaches a phone. Set `NTFY_URL`, or `HASS_URL`/`HASS_TOKEN`/`HASS_NOTIFY_SERVICE` for the Home Assistant companion app -- the creator already holds Home Assistant credentials in `secrets.toml`. A `ui.prompt` that nobody answers within a few seconds should raise a notification through this path, with the question in it and a link that opens item 3's screen. That is a notification with a link, not an action button, and it is enough to be genuinely useful.

Note for whoever builds this: `notify.py` reads `os.environ` directly rather than the scoped secret store, so its credentials sit outside the vault path. Worth reconciling, and not in this stage.

**With the native client:** APNs with **actionable** notifications -- Approve and Deny as buttons on the notification itself, answered without opening the app. This is the single best reason for the native client to exist. It needs a push token per device (item 2's table is where it goes) and a small APNs sender beside `notify.py`'s providers.

Done when: an unanswered prompt reaches the phone within five seconds, and tapping it lands on that question.

### 5. Live voice: the second session

`voice/remote.py` gives the transport, the microphone and the speaker. What remains is the session.

- A connection loop: authenticate the token (item 2), require the `chat` capability, build a `RemoteMicrophone` and a `RemoteSpeaker` over the socket, and construct a **second `VoiceSession`** with them. This is possible because `VoiceSession` takes its microphone, speaker, recogniser and synthesiser as constructor arguments -- there is no singleton in the class. The service holds one session today by its own choice, not by constraint.
- **Reply routing.** A phone turn must never be spoken in the house. `[voice] output` already means `laptop|tv|both`; a phone session is a fourth destination, and the routing is per session, not per configuration.
- Two echo trackers, two turn managers -- both are per-instance, so this is free.
- The speech lock is **not** shared. It exists so two replies do not talk over each other in one room; a phone is a different room. A phone turn holds its own.
- The recogniser and the synthesiser **are** shared: one warm `whisper-server` and one Kokoro, already loaded. Two model copies for a second listener would be 3 GB for nothing.

Done when: speech into the phone is answered in the phone's ear, with the laptop session still listening and unaffected, and barge-in works on both independently.

### 6. The web client, to prove the server

One page, added to the Home Screen: console, approvals, chat, the house, and push-to-talk voice. `AudioWorklet` capture downsampled to 16 kHz mono int16, binary frames out, PCM frames in.

The first thing to test on a real iPhone, before building on it: whether `getUserMedia` works in **standalone** Home Screen mode on the creator's iOS version. It was broken for years and fixed somewhere around iOS 15-16. Assume nothing; the answer decides whether push-to-talk lives in the web client or waits for item 7.

Done when: every server item above has been exercised from the phone.

### 7. The native client

A sibling project, not a package here. Swift/SwiftUI, one target, consuming the documented API.

What it adds over item 6, and only this: background and always-on voice; actionable approve/deny on the notification; a Live Activity while a task runs; a widget with the house state; Siri intents so "ask Sim" works from anywhere.

## Security, stated plainly

This stage takes a household agent that can control the house, spend money, edit its own code and read the family's email, and makes it reachable from a phone on the open internet. Three things carry that weight, and none is optional:

1. **Tailscale, not a forwarded port.** No listening socket on the public internet at all.
2. **Per-device tokens with capabilities** (item 2), so a lost phone is revoked in one line and `approve` is a grant rather than a default.
3. **Guardian is unchanged.** The phone answers Guardian's questions; it never bypasses them. No route added by this stage may approve an action that Guardian did not itself escalate, and the `approve` capability grants the ability to *answer*, never the ability to *skip*.

## What this stage does not build

- No always-listening from the phone. Item 7 makes it possible within Apple's limits; whether a family wants a pocket microphone always open is the creator's call, not a default.
- No Android client. The API is the product; a second client is a repeat of item 7.
- No multi-user phones. One device, one person, one token; `people` already models the household but nothing here reads it yet.
- No offline mode. A phone with no route to Sim shows what it last knew and says so.
- No APNs in the server until item 7 exists to receive it. Until then `notify.py`'s existing providers are the channel, and they already work.

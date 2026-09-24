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
| cost | none | $99/year -- **approved by the creator 2026-09-24**, so this is settled; a free account would expire a sideloaded build every 7 days, which is useless for a household appliance |

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

## What the app is, screen by screen

The creator's shape, 2026-09-24: "act like chat gpt or gemini mobile app, which provide both text and interactive voice chat, in addition it will allow me to control home remotely, observe and monitor through different pages, something similar to dashboard will be available on mobile app, will have separate tab to control video feeds, separate tab for home automation stuff, separate tab for settings, admin stuff".

Five tabs. The first is the one people open; the other four are why this is not a chat app.

| tab | what it is | reads | writes |
|---|---|---|---|
| **Ask** | The ChatGPT/Gemini shape: a thread, text in, and a microphone button for live voice | `POST /api/chat` ✓, `/api/history` ✓ | the voice socket (item 5) |
| **Home** | Lights, switches, scenes, thermostats. Tiles from Sim's own view of the house, not Home Assistant's | `home_find`, `home_state`, `home_describe` | `home_call`, `home_undo` |
| **Cameras** | Live feeds, stills, and the controls: pan, light, siren, record | `/api/dash/streams` ✓, `/cameras/snap/` ✓, `/tv/hls/` ✓, `/api/dash/ring/live` ✓ | `cam_ptz`, `cam_light`, `cam_ir`, `cam_siren`, `cam_watch` |
| **House** | The monitor page: what Sim is doing, energy, tasks in flight, alerts, the activity feed | `/api/dash/data` ✓, `/api/status` ✓, `/api/activity` ✓, `/api/logs` ✓, `energy_status` | `cancel_task` |
| **Settings** | Admin: paired devices, voice settings, config, alerts, the cast target | `/api/status` ✓, `devices` (item 2) | `voice_setting`, `sim_command`, device revocation |

**Video is nearly free on iOS.** `/tv/hls/` already serves HLS, and iOS plays HLS natively in an `AVPlayer` or a `<video>` tag -- no library, no transcoding, no WebRTC. This is the one place the phone is a *better* client than the TV, where in-page video and YouTube embeds both came back blank on the Cast receiver (2026-09-19).

**The read surface is largely built. The control surface is one route away.** Every write in that table is a *tool*, and tools are reachable today only from a conversation or the REPL -- so the four control tabs have nothing to call. What they need is not twenty bespoke routes but one, and the mechanism already exists: `httpapi.py::_run_for_page` proposes a tool "the way the terminal does: a proposal Guardian sees, the result read back". It is wired to a handful of hardcoded camera and Ring routes and is not exposed generically. Item 3a makes it so.

## Items

### 1. Remote reach, with TLS

`getUserMedia` requires a secure context, so **no browser will give a page the microphone over `http://`** -- this blocks the voice work and nothing else can be tested honestly without it. The HTTP server has no TLS at all (`asyncio.start_server`, no `ssl` anywhere).

Tailscale is the recommended route and the one this plan assumes: a stable hostname, real certificates, works away from the house, and no port opened on the router. It also retires the `0.0.0.0` LAN bind that the 2026-09-18 evaluation flagged (S15/V2) -- Sim can go back to binding loopback and let the tailnet carry it.

Alternatives, for the record: a self-signed certificate with a trust profile on the phone (LAN only, Safari nags), or a Cloudflare tunnel (household audio transits a third party).

Done when: the dashboard loads over `https://` on the phone, off the home network, with no certificate warning.

### 2. Per-device tokens, before anything can approve

`SIM_API_TOKEN` is one shared 32-character bearer for every caller. That is adequate for a dashboard on the LAN and **not** adequate for a device that can approve an irreversible action: a phone left in a taxi is, today, full control of the house with no way to revoke it short of rotating the token and re-pairing everything.

So: a `devices` table in the settings home, one token per device, each with a name, a created-at, a last-seen, a revoked-at, and a **capability set**. `read` for the console and the house. `chat` for conversation. `approve` as its own capability, granted deliberately, never by default. Revoking one device must not disturb the others.

#### Pairing: Sim draws a barcode, the app scans it, done

The creator's requirement, 2026-09-24: "easy pairing, mobile app scan a barcode generated by sim and pairing happens". Nobody types a 32-character secret on a phone keyboard.

    voice:  "sim, pair my phone"        typed: `pair [name]`
      |
      v
    Sim mints a one-time code, prints it as a QR in the terminal
      |
      v
    the app scans it, POSTs the code once, gets its OWN token
      |
      v
    the code is spent; the terminal says which device paired

**What the QR carries: a pairing code, never a token.** `https://<host>/pair#<code>` -- a single-use, 120-second code, and the fragment rather than the query so it stays out of server logs and Referer headers. A photograph of this QR is worth nothing a minute later. Putting the device token in the QR instead would mean a picture of the screen, or a screen-share, is permanent full control of the house.

**The code is mintable only from the local REPL or a spoken turn**, never over HTTP. `POST /api/pair` -- which must be the only unauthenticated write route in the server -- spends a code and returns a token; it cannot create one. So an attacker on the tailnet has nothing to call.

Rules: single use (the second POST is refused and says so); 120 seconds; one outstanding code at a time, so "pair" twice means the first is dead; rate-limited to a handful of attempts; and the new device's name, capabilities and pairing time print in the terminal, because a pairing nobody saw is the one worth noticing.

**Capabilities are chosen at pairing**, not after. `pair my phone` grants `read` and `chat`. `approve` is a separate word -- `pair my phone with approve` -- so the ability to authorise an irreversible action is always a sentence somebody said, never a default that arrived with a scan.

**Drawing it, with what is already on the machine**: `qrencode -t UTF8` (Homebrew, present 2026-09-24) renders a scannable QR straight into the terminal. Then the Python `qrcode` package if importable. Then, with neither, the URL and a short typeable code -- pairing must never be *impossible* because a rendering tool is missing, which is the same "optional, probed, refused by name" rule every voice engine follows. No new hard dependency.

Done when: `devices` lists and revokes; a revoked token is refused; a scanned code pairs once and is dead the second time; a device without `approve` is refused the route in item 3 and told which capability it lacks.

### 3. Answering Sim's questions from anywhere

`GET /api/prompts` -- the open ones, with `prompt_id`, `question`, `options`, and the seconds left.
`POST /api/prompts/<id>` -- `{answer}`, publishing `ui.prompt.answered`, requiring the `approve` capability.

Rules that matter more than the routes:

- **The prompt's own timeout still governs.** A phone answer arriving after it has expired is refused with "that question has already timed out", never applied late. Guardian's decision has already been made by then.
- **First answer wins.** The REPL and the phone can both be looking at the same question; the second answer is told who answered and what they said, rather than silently doing nothing.
- The question text reaching a phone is the same text the terminal box shows. No summarising, and no "Sim wants to do something" -- the whole point is that the person can judge it.

Done when: an irreversible action proposed while nobody is at the terminal is approved from the phone and runs; and the same action, answered after its timeout, is refused with the reason.

### 3a. One action route, so the control tabs have something to call

`POST /api/action` -- `{tool, args}` -- through the existing `_run_for_page` path: a proposal Guardian sees, on the same footing as a tool call from a spoken turn. The phone gains no privilege the voice channel does not already have, and Guardian is not touched.

Two rules carry this, and the second is the one that is easy to get wrong:

1. It needs a `control` capability (item 2), separate from `read` and from `chat`.
2. **A server-side allowlist of tool names**, not "whatever Guardian permits". Guardian gates *effects*; this gates *surface*. `_run_for_page` is safe today only because the server itself chooses every tool name it passes; the moment the CLIENT names the tool, a stolen phone token could ask for `run_shell`, `apply_source_patch` or `install_package` and Guardian would evaluate it as a legitimate request. The allowlist is the house's remote control -- home, cameras, media, cast, tasks, voice settings -- and nothing that writes code or runs a shell. A tool not on it is refused by name, so the failure is legible rather than mysterious.

Done when: a light goes on from the phone; `cancel_task` works; `run_shell` is refused with "not a tool the phone may ask for" and no proposal is made at all.

### 4. Push, so a question finds the person

Two stages, deliberately.

**Now:** `notify.py` already reaches a phone. Set `NTFY_URL`, or `HASS_URL`/`HASS_TOKEN`/`HASS_NOTIFY_SERVICE` for the Home Assistant companion app -- the creator already holds Home Assistant credentials in `secrets.toml`. A `ui.prompt` that nobody answers within a few seconds should raise a notification through this path, with the question in it and a link that opens item 3's screen. That is a notification with a link, not an action button, and it is enough to be genuinely useful.

Note for whoever builds this: `notify.py` reads `os.environ` directly rather than the scoped secret store, so its credentials sit outside the vault path. Worth reconciling, and not in this stage.

**With the native client (funded, so this is committed rather than hoped for):** APNs with **actionable** notifications -- Approve and Deny as buttons on the notification itself, answered without opening the app. This is the single best reason for the native client to exist, and with the Developer Program approved it is item 7's first job, not a stretch goal. It needs a push token per device (item 2's table is where it goes) and a small APNs sender beside `notify.py`'s providers -- APNs is a JWT and an HTTP/2 POST, so the provider stays in the same shape as the other eight.

A judgement to make there, not now: whether an approval notification is a **critical alert**. Critical alerts pierce Do Not Disturb and need a separate Apple entitlement. A Guardian question at 3am is arguably exactly that, and a Guardian question that wakes the house every time is exactly not. Ship it ordinary, and let the creator ask for critical once he has lived with it.

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

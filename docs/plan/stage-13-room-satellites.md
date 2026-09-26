# Stage 13 -- Room satellites

Status: **designed; item 0 done** (2026-09-26: one reSpeaker XVF3800 + XIAO ESP32S3 flashed, on Wi-Fi as `sim-room-1`, wake word and barge-in measured) · Depends on: stage 3 (streaming voice); item 1 is the same change as stage 12 item 5, and whichever lands first satisfies both · Estimated: 1 week for one room, a day per room after · Modules touched: voice, interface, kernel (config wiring only), tools, docs

## Outcome

Sim can be spoken to in every room, not only at the laptop. Each room has a small Wi-Fi satellite: four microphones, an echo-cancelling DSP, a speaker, and an on-device wake word. It streams audio to the Mac only after its wake word, and Sim answers out loud in **that** room, as the person Sim believes is speaking, with the same memory and the same judgement as at the desk.

The Mac stays the server. A satellite runs no model, stores nothing, and can be replaced from a spare in ten minutes.

## Why a satellite, and why this one

Decided with the creator 2026-09-22, and measured 2026-09-25/26:

- **Bluetooth was dropped.** A Mac holds at most three hands-free (SCO) links, the mic path is 8-16 kHz narrowband, and cheap speakerphones carry batteries that die in a drawer.
- **The reSpeaker XVF3800 with a XIAO ESP32S3** (~$65-75 a room with a small speaker) has the one thing that makes a far-field room device work: an XMOS DSP doing beamforming and echo cancellation *before* the audio leaves the board. The ReSpeaker Lite (~$30) is the fallback if a room does not need it.
- **ESPHome firmware, spoken to directly.** [formatBCE/Respeaker-XVF3800-ESPHome-integration](https://github.com/formatBCE/Respeaker-XVF3800-ESPHome-integration) runs on the ESP32; Sim talks to it over the ESPHome native API with `aioesphomeapi`. Not Wyoming (deprecated upstream for this use), and **not through Home Assistant's Assist pipeline** -- see "The decision" below.

## The decision: Sim is the pipeline server, not Home Assistant

The creator moved home-automation heavy lifting to Home Assistant (2026-09-19), and HA can drive this exact satellite. It must not, for voice, and the reason is concrete:

**Only one API client may hold a satellite's voice assistant.** A second is refused on the device ("Multiple API Clients attempting to connect to Voice Assistant", measured 2026-09-25). Whoever holds it owns the turn. If HA holds it, a spoken turn goes HA STT -> HA conversation agent -> HA TTS, and bypasses everything `VoiceSession._ask_and_speak` does that makes Sim Sim: speaker identification, "that voice is the TV" (`_tv_is_playing`), household-name spelling, enrolment and introductions, spoken commands (`stop`, `voice off`), the follow-up window, and turn cancellation when the person moves on.

So Sim holds the voice assistant. HA may still see the satellite's *other* entities (LED ring, mute switch) -- those are ordinary ESPHome entities and do not conflict -- but if HA's ESPHome integration is ever pointed at a satellite, its voice pipeline must be set to none. Item 2 detects the conflict and says so by name rather than failing quietly.

## What item 0 established (2026-09-25/26)

Measured on `sim-room-1` with a throwaway probe (`~/esphome-sim/probe.py`, outside the repo) standing in for the pipeline server. Every rule below is a line of item 2's code.

| fact | measured | consequence |
|---|---|---|
| audio | 16 kHz mono s16le over the API socket (`handle_start` returns port 0 = API audio mode) | the format `voice/api.py` already speaks; nothing transcodes |
| wake word | on the device: `okay_nabu`, `hey_jarvis`, `hey_mycroft`, `kenobi`; 3/3 in a quiet room | `handle_start` gets the wake word's name |
| quality | noise floor ~10 RMS between words; faster-whisper `small` transcribed full sentences verbatim | the XMOS output is clean enough for large-v3-turbo |
| feature flags | 61 = voice assistant, API audio, timers, announce, start-conversation | follow-up without a wake word is possible (item 5) |
| **one client** | a second subscriber is refused, and the first is disconnected | item 2 owns the device exclusively and reconnects |
| **run-end race** | `RUN_END` sent while the device is still in `STOP_MICROPHONE` is ignored; the device sits in `AWAITING_RESPONSE` forever and **every later wake word stops the run instead of starting one** (`handle_stop(abort=True)`) | never send `RUN_END` until ~1 s after `STT_VAD_END`, or until the reply's `TTS_END` |
| end of speech | the device does not endpoint; the server decides and sends `STT_VAD_END` | Sim's own endpointer ends the turn, as it does for the laptop |
| speaker | none on the board; the creator attached one to the 3.5 mm jack | `volume` is a media-player command (set to 1.0) |
| playback | `media_player_command(media_url=...)` fetches over HTTP(S) and plays; prefers FLAC 48 kHz (announcements mono); `audio-file://<id>` plays a sound compiled into flash | a reply is a URL the device fetches (item 3) |
| **state lag** | PLAYING/IDLE state events arrive up to ~10 s after the audio really starts and ends; the decoder's own log (`subscribe_logs`) is truthful | a reply's duration comes from the audio Sim made, never from the device's state |
| **barge-in** | the JFK clip looping at volume 1.0 as media, the creator 2-4 m away: both wake words fired, both sentences transcribed verbatim, no JFK in either transcript | the XMOS AEC plus the firmware's 20 dB ducking hold; this was the test that decided whether to buy more |
| announcements | during an *announcement*, the stock firmware's wake word only **stops** playback; it does not start listening | a reply Sim is speaking is an announcement, so barge-in on a reply needs item 5's firmware change |
| clipped start | in one of three quiet takes the first ~1 s after the wake word was silent and the opening words lost | suspect the wake chime (`Wake sound` switch); unmeasured -- item 6 |

## Items

**Build order: 1, 2, 3, 4, then 5 and 6 in either order, then 7.** Item 1 is useful on its own (it is the phone's second session too), and nothing in items 2-4 can be tested end to end without it.

### 1. The voice service holds a session per device

**Lock: voice.** Same change as stage 12 item 5; whichever stage takes it first does it once.

`VoiceService` holds one `self._session` (`simorgh/voice/service.py:174`, built at `:469`) and seven places read it (`:303`, `:389`, `:495`, `:603`, `:723`, `:878`, `:1175`). Make it `self._sessions: dict[str, VoiceSession]` keyed by `Config.device` -- `"laptop"` for today's, the satellite's name for a room. `VoiceSession` already takes its microphone, speaker, recogniser, synthesiser, `embedder` and `speakers` as constructor arguments; nothing in the class is a singleton.

- **Shared**: the recogniser (one warm `whisper-server`), the synthesiser (one Kokoro), the speaker book and the embedder. Two copies of large-v3-turbo for a second room would be gigabytes for nothing, and a voice learnt in the kitchen must be known in the living room.
- **Per session**: the turn manager, the echo tracker, the speech lock, the follow-up window, the per-turn facts, `last_speaker`. The speech lock exists so two replies do not talk over each other *in one room*; two rooms are two locks.
- **The reader's rule**: each of the seven call sites says which session it means. Status and control default to all of them (`voice off` silences the house); a turn's own path uses its own session. Do not let a helper pick "the" session.
- **The bug shape to avoid** (memory: per-turn facts in session state, failed both directions 2026-09-18): a per-turn fact stored on something shared and read across an await. Two live sessions make it twice as likely. Per-turn facts stay keyed by turn id *inside* a session; nothing per-turn goes on the service.
- **Recogniser concurrency.** Two rooms can finish a turn at once. Measure what `whisper_server` does with two concurrent `/inference` posts before deciding anything; if it serialises, a queue with a latency number in the log is enough.

Done when: two sessions over `fakes.py` microphones run concurrently, a turn in each is answered through its own speaker, a voice enrolled in one is identified in the other, and `voice off` silences both. `python tools/modtest.py voice` green.

### 2. `voice/satellite.py`: an ESPHome satellite as a microphone and a speaker

**Lock: voice.**

The shape is `voice/remote.py`'s: a `SatelliteMicrophone` behind the same `name`/`capture`/`stream` seam `SounddeviceMicrophone`, `FfmpegMicrophone` and `RemoteMicrophone` implement, and a `SatelliteSpeaker` that, like `RemoteSpeaker`, keeps the turn's time. Audio does not cross the Bus -- the same reasoning as `remote.py`'s docstring.

- **One `SatelliteLink` per device** owns the `aioesphomeapi.APIClient`: connect with the Noise key, `subscribe_voice_assistant`, reconnect with backoff, and log each state change once. On "Multiple API Clients" it says, by name, that another client (HA, a stray probe) holds the device, and does not fight for it in a loop.
- **The microphone** yields frames only between `handle_start` and the end of the turn. Between turns `stream()` simply waits: the device sends nothing until its wake word, which is also the privacy property worth stating in the contract -- *no audio leaves a room until its wake word fires*.
- **Ending a turn.** Sim's endpointer decides; the microphone then sends `STT_VAD_END`, `STT_END` (with the text, for the device's own log), `INTENT_START`/`INTENT_END`. `RUN_END` waits for the reply (item 3's `TTS_END`) or ~1 s if there is none. This is the run-end race in the table above; write the test that sends `RUN_END` early against a fake device and asserts the next wake word still starts a run.
- **The speaker**: `play(audio)` hands the audio to item 3 for a URL, sends `TTS_START`/`TTS_END{url}`, then sleeps the audio's own duration (`audio.seconds`), not the device's state events, which lag by up to ~10 s. `stop()` sends a media-player stop. The speaking flag, the echo gate and barge-in follow the audio exactly as with `SilentSpeaker`.
- **The echo tracker** sees the reply Sim sent, as it does for the laptop. The XMOS chip already removes it acoustically, so expect the tracker to have little to do; do not remove it, measure it (item 6).
- **Dependency**: `aioesphomeapi` is optional, probed at start, and refused by name when missing ("satellites need `pip install aioesphomeapi`"), the rule every voice engine follows. Nothing else in `simorgh/` imports it. Tests use a fake link in `fakes.py`; no test needs a device on the network.

Done when: with a fake link, a wake -> utterance -> reply -> `RUN_END` cycle runs five times in a row; a second wake word during a reply stops the reply; the early-`RUN_END` regression test passes; a missing `aioesphomeapi` produces one legible refusal. Update `voice/CONTRACT.md`.

### 3. A URL for the reply

**Lock: interface.** Consumes a voice topic; add it to interface's "Consumes" table.

The device fetches its reply over HTTP; it cannot carry a bearer token, and a URL is all `TTS_END` can hold. The TV already solved the same problem: `voice/session.py::_ship_to_tv` puts the WAV in the ledger and publishes `tv.speech{ref, seconds, seq}`; `interface/httpapi.py` keeps the last 40 refs (`_tv_speech`, `:276`) and `GET /api/tv/speech?ref=` serves only a ref on that list (`:379`).

Do the same for rooms: a `voice.room.speech{ref, seconds, device}` topic, a bounded list of refs in interface, and `GET /api/room/speech?ref=` serving only a listed ref that is under two minutes old. The ref is a content address nobody can guess, it expires, and the route serves nothing else, so no token is needed -- the same trade the TV route already makes, and why it is acceptable on a home LAN and nowhere else. The URL uses the Mac's LAN address, which `/api/addresses` already knows.

**Format.** The firmware prefers FLAC at 48 kHz. Kokoro gives 24 kHz WAV; try WAV first (the decoder accepts it) and measure time-to-first-sound. Transcode with ffmpeg only if the measurement says so -- no new dependency on a guess.

Done when: a reply's URL plays on the device, a second fetch after expiry is a 404, an unlisted ref is a 404, and `interface/CONTRACT.md` records the route and the topic in the same commit.

### 4. Configuration: which satellites, and their keys

**Lock: voice** (and **kernel** only if the Kernel must pass anything new -- it should not; voice reads its own section).

    [[voice.satellites]]
    name = "kitchen"                # becomes Config.device for that session
    host = "sim-room-1.local"
    key_env = "SIM_SATELLITE_KITCHEN_KEY"   # the Noise PSK lives in ~/.simorgh/secrets.toml, never here
    volume = 1.0

An empty list means no satellites and no import of `aioesphomeapi`. A satellite that cannot be reached is logged once per state change and retried; it never delays the laptop session starting. `voice status` lists each satellite: connected, last wake, last turn, and why not if not.

Done when: the config round-trips, a satellite missing its key is refused by name at start, and `voice status` shows each one. `CONTRACT.md` in the same commit (rule 7).

### 5. Conversation on a satellite: follow-ups, barge-in, the wake word

**Lock: voice**, plus **tools** for the firmware file.

- **Follow-ups.** Feature flag 32 (start conversation) lets Sim reopen a satellite's microphone after a reply without a wake word. Map it to `[voice] follow_up_window_s`, which already means exactly this at the laptop.
- **Barge-in on a reply.** The stock firmware treats a wake word during an announcement as *stop* only (measured). The creator will expect "Okay Nabu, no, I meant..." to be heard. Change it in the device yaml, not by forking the package: an `on_wake_word_detected` override (the package documents `!extend`/`!remove`) that stops the announcement *and* starts the voice assistant. Measure it with the JFK loop before keeping it.
- **The wake word.** `okay_nabu` for now. A custom "Hey Sim" microWakeWord model can be trained later and loaded by URL like `kenobi` is; it is the creator's call (open questions), and it is not needed to ship.

Done when: a follow-up question within the window is answered without a wake word, and a wake word during a reply stops the reply and takes the new question.

### 6. Measure before buying four more

**Lock: evals** or **tools** for any harness; results in `docs/findings/`.

Item 0 measured the quiet room and loud playback. Before the creator orders rooms 2-5:

1. **The noisiest room** (the kitchen with the hood fan on, or the TV room with the TV playing): wake-word hit rate over 10 tries, and transcript WER over the same 10 sentences against the laptop mic.
2. **Speaker identification through the far-field mic.** Play a subset of the calibration set (`workspace/voice/calibration/`) through a speaker at 2 m into the satellite and score the speaker book. If the scores fall below `speaker_bar`, the fix is enrolment through the satellite, not a lower bar.
3. **Clipped starts.** Ten takes that speak immediately after the wake word, with `Wake sound` on and off. If the chime costs the first second, turn it off by default.
4. **Latency**: wake word -> first reply audio from the speaker, p50/p95, over 20 turns, against the laptop's.

Done when: the four numbers are in a findings doc and the creator has decided on the other rooms.

### 7. Provisioning rooms 2-5

**Lock: tools.**

Move the device config from `~/esphome-sim/` into `tools/satellites/` (`room.yaml` taking the room name as a substitution, `secrets.yaml.example`, and a README): Wi-Fi and keys stay in an untracked `secrets.yaml`. A room is then: flash over USB with `esphome run`, add the `[[voice.satellites]]` block, put the key in `secrets.toml`, restart voice. Note from item 0: `esphome upload` flashes the **previously compiled** binary; after changing secrets use `esphome run`, or the device joins the placeholder network.

Done when: a second satellite is added by following the README alone, and both rooms answer independently.

## Definition of done

- [x] One satellite flashed, on Wi-Fi, wake word and barge-in measured (item 0, 2026-09-26)
- [ ] The voice service holds a session per device (item 1)
- [ ] `voice/satellite.py` with a fake-link test suite, including the run-end race (item 2)
- [ ] Replies play from `/api/room/speech` (item 3)
- [ ] Satellites configured in `[[voice.satellites]]`, keys in secrets (item 4)
- [ ] Follow-ups and barge-in on a reply (item 5)
- [ ] The four measurements in `docs/findings/` (item 6)
- [ ] A second room provisioned from the README alone (item 7)

## What this stage does not build

- No model on the satellite beyond the wake word. Recognition, identification and synthesis stay on the Mac.
- No Home Assistant Assist pipeline for these devices (see "The decision").
- No room-to-room calls or intercom. A reply goes to the room the question came from; "tell Aran dinner is ready" in another room is a later item that needs presence.
- No music streaming to satellites as a feature. Playback exists because a reply needs it; a media-player tool is a separate item.
- No satellite without its wake word. Always-streaming rooms would make the house a recording; the wake word on the device is the privacy boundary.

## Open questions for the creator

1. **The wake word**: keep `Okay Nabu`, or train a custom "Hey Sim" model? Sim's name is short and is already misheard at the laptop ("AC", "same", "seam", 2026-09-26), so a trained model is likely more reliable than any regex, but it is a day of work and a few hours of recordings.
2. **Which rooms, in which order**, and which is the noisiest (item 6.1 needs it first).
3. **Should a room's answer also appear in the terminal** and on the TV, or only in the room? Today `[voice] output` is house-wide (`laptop|tv|both`); per-session routing makes this a per-room choice.

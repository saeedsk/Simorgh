# Talking to Sim: voice on the laptop, the phone, and the house

**Build status (2026-09-10):** slice 1, the laptop path, is built --
`simorgh/voice/` (see its README for what is and is not there). This
document remains the spec for the rest.

Design pass, 2026-09-09 (Fable). Implementation is handed to Opus; this
document is written so that nothing below needs a design decision.
Companion to `home-automation-design.md` and
`network-discovery-design.md`. The five invariants and the ten-step
wiring checklist in `resourcefulness-toolset.md` apply.

The ask: talk to Sim by voice -- from a laptop, a mobile app, and the
voice devices in the house (Alexa Echos among them) -- with
state-of-the-art speech recognition and speech synthesis, built on open
source as far as it will go.

## 0. Open source first, and the correction this design carries

The creator's standing correction (`feedback_resourcefulness`, and
again today): Sim -- and the designs written for it -- reach for a paid
API before exhausting what open source can do on the machine. The
real-estate portal was the first instance; today's designs repeated
the shape in three places. Named here so the pattern is on the record
and the fixes are in the docs, not just in this one:

1. **Cognition has no local provider at all.** `simorgh/cognition/
   providers/` holds `claude_code`, `gemini`, `together` -- nothing
   that runs on the machine -- so when there is no API access there is
   no brain. **Fix:** `providers/ollama.py` (OpenAI-compatible
   `/v1/chat/completions` against `http://localhost:11434`, which also
   covers llama.cpp's server, vLLM and LM Studio).

   **But the creator's decision on its role is explicit (2026-09-09):
   a cloud model is the PRIMARY brain; Ollama is the FALLBACK, used
   only when no LLM/API access exists.** Running a 7B model slows the
   laptop and the results have not been good. So the provider policy
   is: the configured cloud provider first; Ollama automatically when
   the cloud provider is unreachable, rate-limited or has no key
   (health-checked, with a ledgered `cognition.provider.fallback`
   event and a spoken/printed "running on the local model" so nobody
   is surprised by worse answers); never the other way round. This is
   the one capability where "local first" does NOT apply, and the
   reason is stated: the local option is worse, and the creator has
   chosen to pay for the better one. For voice specifically, the
   primary should be a *fast* cloud model (Haiku 4.5, Gemini Flash) --
   latency, not reasoning depth, is what a spoken turn needs.

   Per-task-class selection stays (`[cognition] voice_provider`,
   `vision_provider`, `digest_provider`, each `"default"` unless set),
   so a person can route one class to Ollama deliberately without
   moving the rest.

2. **Vision was specified as key-gated only** (`home-automation-design
   §8`: "GEMINI_API_KEY or ANTHROPIC_API_KEY, else 'vision is not
   configured'"). Wrong order. Corrected in that document: Frigate's
   own detector (YOLO/Coral) already classifies person/car/package
   locally; for descriptions, a local VLM through the Ollama provider
   above; `ultralytics` YOLO and OpenCV for anything custom; cloud
   vision is the optional last tier.
3. **`notify` shipped with only cloud providers** (Slack, Resend,
   Twilio) and no open-source one. Corrected in
   `resourcefulness-designs.md`'s log and to be built: **ntfy**
   (self-hosted push, Apache-2, has iOS/Android apps -- the obvious
   first provider for a home), **Gotify**, **Apprise** (one library,
   ~100 services, so the three hand-written senders collapse into
   one adapter), Home Assistant's own `notify` (phones via the HA
   companion app, already installed for the house), Matrix. `auto`
   prefers ntfy/HA when configured.

The rule this document is written under: **local first; cloud only as
a named, opt-in tier; and never a refusal where a library exists.**

Also checked on this machine (2026-09-09): `ollama` and `ffmpeg`
present; none of `sounddevice`, `faster-whisper`, `piper`, `kokoro`,
`torch`, `onnxruntime`, `silero-vad`, `openwakeword`, `wyoming`
installed. All are `pip install`-able; the design makes each optional,
probed by `capabilities`, and refused by name when absent.

## 1. The stack, and why each piece

Quality target: "state of the art" in 2026 open source means, for
speech-to-text, word error rates at or below the commercial APIs on
English, streaming, and on-device; for text-to-speech, naturalness
indistinguishable from studio narration in blind tests, with
controllable voices, and sub-200 ms time-to-first-audio. All of that
exists as open weights now. The picks:

| function | primary | alternates | why |
|---|---|---|---|
| **Speech-to-text** | **`faster-whisper`** running `large-v3-turbo` (CTranslate2, int8, ~1.6 GB; real-time ×8 on an M-series Mac, ×20+ on a modest GPU) | **NVIDIA Parakeet TDT 0.6B v2** via NeMo (top of the Open ASR Leaderboard, ~50× real-time, English-only, needs a GPU or a strong CPU); **Moonshine** for the ESP/edge satellites; **Vosk** as the tiny always-works fallback (50 MB, no GPU, worse WER) | Whisper large-v3-turbo is the best *general* open model (multilingual, robust to noise); Parakeet is the best *English* one; both stream with the `whisper-streaming`/NeMo buffering approach |
| **Voice activity detection** | **Silero VAD** (ONNX, 2 MB, ~1 ms per 30 ms chunk) | `webrtcvad` | the standard; runs anywhere |
| **Wake word** | **openWakeWord** (Apache-2; ships "hey jarvis", "alexa"…; **a custom "hey Sim" model is trained from synthetic TTS samples in ~1 h on CPU** -- the repo has the notebook) | microWakeWord (the ESP32 satellite firmware's), Porcupine is NOT used (proprietary key) | local, custom word, no key |
| **Text-to-speech** | **Kokoro-82M** (Apache-2; 82 M params; top of the TTS Arena among open models; ~0.1 s per sentence on CPU; 50+ voices; ONNX build `kokoro-onnx` needs no torch) | **Chatterbox** (Resemble AI, MIT, 2025: emotion control, zero-shot voice cloning, beats ElevenLabs in blind tests -- heavier, wants a GPU); **Orpheus-3B** (Llama-based, expressive, GPU); **Piper** (HA's own, fast, lower quality -- the fallback and the satellite default); **F5-TTS** for cloning. **XTTS-v2 is not used**: Coqui's CPML licence forbids commercial use and the company is gone | Kokoro is the quality/latency sweet spot on CPU; Chatterbox is the "state of the art" option when a GPU exists |
| **Speaker identification** | **SpeechBrain ECAPA-TDNN** embeddings (or `resemblyzer`), enrolled per household member from 30 s of speech | pyannote (needs an HF token -- avoid) | "who is asking" drives per-person context and the section 6 permissions |
| **Satellite protocol** | **Wyoming** (Home Assistant's open protocol for STT/TTS/wake/satellite over TCP, tiny, no deps beyond `wyoming`) | -- | every HA voice device speaks it; Sim speaking it means the house's existing/planned satellites work with zero HA-side code |
| **Conversation entry from HA** | Sim exposes an **OpenAI-compatible `/v1/chat/completions`** endpoint; HA's built-in **OpenAI Conversation** / **Ollama** integration points at it | a custom HA `conversation` integration (HACS) | HA Assist then routes every voice turn to Sim as its "conversation agent" -- again zero HA code, and Sim gets tool-calling through HA's `assist` intents for device control |
| **Satellites (hardware)** | **Home Assistant Voice Preview Edition** ($59, XMOS far-field mics, open firmware, Wyoming/ESPHome), **ESP32-S3-BOX-3** with the ESPHome voice firmware, an old phone/tablet running the HA companion app, a Raspberry Pi + ReSpeaker running `wyoming-satellite` | **Willow** (ESP32-S3-BOX, its own protocol) | fully local far-field voice in each room |
| **Laptop / desktop client** | Sim's own `sim voice` (`sounddevice` mic → VAD → STT → Sim → TTS → speaker, all in-process) | -- | the primary development surface (`feedback_test_primary_interface_first`) |
| **Mobile** | **HA companion app** (Assist tab, push-to-talk, wake word on Android) → HA → Sim; plus Sim's own **PWA** (`/voice` page: WebRTC/`MediaRecorder` audio → Sim over WebSocket; no Web Speech API, which is Google's cloud in Chrome) | -- | zero-install today; a native app is not designed here |
| **Alexa Echos** | **input**: an Alexa custom skill (cloud, unavoidable: Amazon does the ASR) whose endpoint is Sim; **output**: `alexa_media_player` announcements -- Sim's own TTS audio, uploaded to HA's `media_source`, played on the Echo, so the *voice* is Kokoro's even on an Echo | -- | honest about the boundary: Echos are cloud-bound by Amazon's design; the fully-local path is the satellites above, and the design makes the Echos *output speakers* for the same brain |
| **Audio plumbing** | `sounddevice` (PortAudio), `ffmpeg` (present) for resampling/format | -- | |

Everything above runs on the Sim/HA box. GPU is optional and improves
quality/latency (Chatterbox, Parakeet); the CPU path (Whisper turbo
int8 + Kokoro ONNX + Silero) is genuinely good and is the default.

## 2. The `voice` subsystem (`simorgh/voice/`)

19th subsystem. Owns audio I/O, the pipeline, sessions, and the
Wyoming/HTTP surfaces. It does **not** decide anything -- a voice turn
becomes `percept.text.received` with `channel="voice"` and rides the
same Orchestration/Cognition path as typed text; the reply comes back
as `ui.reply` and is spoken. One brain, one Guardian, one ledger.

```
simorgh/voice/
  api.py          VoiceTurn, Utterance, Speaker, Session dataclasses; the engine Protocols
  config.py       [voice] (section 3)
  stt/            base.py  faster_whisper.py  parakeet.py  vosk.py  wyoming_client.py
  tts/            base.py  kokoro.py  chatterbox.py  piper.py  wyoming_client.py
  vad.py          Silero (ONNX); endpointing (section 4.2)
  wake.py         openWakeWord; custom "hey sim" model path
  speakers.py     enrolment + identification (ECAPA embeddings, cosine, threshold 0.75)
  pipeline.py     wake → VAD → STT(stream) → route → LLM(stream) → sentence-split → TTS(stream) → play
  sessions.py     one per (device, speaker): turn history, barge-in, follow-up window
  audio.py        sounddevice capture/playback, resampling, AEC hooks
  surfaces/
      local.py     `sim voice` -- the laptop client
      wyoming.py   Wyoming server: Sim as STT+TTS+wake provider AND satellite handler
      openai.py    /v1/chat/completions (+ /v1/audio/transcriptions, /v1/audio/speech) on the HTTP API
      alexa.py     /api/voice/alexa  -- the custom skill endpoint
      web.py       /voice PWA + WebSocket audio
  service.py      Service, health, capability probes
  fakes.py        FakeMic (wav files), FakeSpeaker (captures), FakeSTT/FakeTTS (deterministic)
```

## 3. Config

```python
@dataclass(frozen=True)
class Config:
    enabled: bool = False
    # Engines. "auto" = the best one whose package is importable; never a cloud engine.
    stt: str = "auto"                 # auto | faster_whisper | parakeet | vosk | wyoming:<host:port>
    stt_model: str = "large-v3-turbo" # faster_whisper; "distil-large-v3" for weaker CPUs
    stt_language: str = "en"          # "" = detect
    stt_compute: str = "auto"         # int8 | float16 | auto
    tts: str = "auto"                 # auto | kokoro | chatterbox | piper | wyoming:<host:port>
    tts_voice: str = "af_heart"       # Kokoro voice id; a Chatterbox reference wav path; a Piper voice
    tts_speed: float = 1.0
    tts_reference_wav: str = ""       # Chatterbox/F5 cloning -- see section 6 (consent)
    vad: str = "silero"
    vad_threshold: float = 0.5
    endpoint_silence_ms: int = 700    # end of utterance
    max_utterance_s: float = 30.0
    wake_word: str = "hey_sim"        # openWakeWord model name; "" = push-to-talk only
    wake_model_path: str = "workspace/voice/hey_sim.onnx"
    wake_threshold: float = 0.6
    follow_up_window_s: float = 6.0   # after a reply, listen again without the wake word
    barge_in: bool = True             # speech during playback stops playback
    # Cognition: which provider answers voice turns (section 5).
    # "default" = [cognition]'s primary (cloud); Ollama is the automatic
    # fallback when that is unreachable, never the primary by default.
    cognition_provider: str = "default"
    cognition_model: str = ""                # "" = the provider's fast model
    fast_path_intents: bool = True    # device control / state without the LLM (section 5.2)
    # Speakers
    speaker_id: bool = True
    speakers_path: str = "workspace/voice/speakers/"   # enrolments; never leaves the box
    unknown_speaker_policy: str = "guest"              # guest | ignore | ask
    # Surfaces
    local_client: bool = True
    wyoming_port: int = 10700
    openai_compat: bool = True        # /v1/* on the HTTP API
    web_client: bool = False          # /voice PWA (needs HTTPS for mic access)
    alexa_skill: bool = False
    alexa_skill_id_env: str = "ALEXA_SKILL_ID"
    # Privacy
    keep_audio: bool = False          # store utterance wavs under workspace/voice/audio/ (debugging)
    keep_transcripts: bool = True     # ledger stream voice:turns
    # Output routing
    announce_devices: tuple[str, ...] = ()   # HA media_player ids for announcements (Echos, satellites)
```

## 4. The pipeline (`pipeline.py`) -- and the latency budget

Target, measured end to end on the CPU path: **≤ 1.2 s from end of
speech to first audio**; ≤ 0.6 s with a GPU. Budget:

| stage | budget | how |
|---|---|---|
| endpointing | 700 ms (the silence itself) | Silero VAD on 30 ms frames; adaptive: shorten to 400 ms after a question-shaped utterance |
| STT final | ≤ 250 ms | streaming: partial transcripts every 500 ms during speech, so the final pass only covers the tail |
| route + LLM first token | ≤ 200 ms (fast path) / ≤ 700 ms (a fast cloud model, streaming) / ≤ 600 ms (Ollama 7B on M-series, fallback) | section 5 -- the fast path exists because the LLM leg is the largest and least controllable |
| TTS first audio | ≤ 150 ms | sentence-split the LLM stream; synthesise sentence 1 while the LLM is still writing sentence 2; Kokoro ONNX ~100 ms/sentence |
| playback start | immediate | 24 kHz PCM ring buffer |

### 4.1 Flow

```
mic ──► wake.py ──► vad.py ──► stt (streaming) ──► sessions.py ──► route
                                                                   ├─ fast path (intents) ─┐
                                                                   └─ cognition (stream) ──┤
 speaker ◄── audio.py ◄── tts (sentence stream) ◄── sentence splitter ◄──────────────────┘
```

- Wake word → an acknowledgement *tone* (not speech; 80 ms) and a
  `voice.listening` event → the satellite's LED / the laptop's status
  line.
- Barge-in: VAD firing during playback pauses playback within 100 ms,
  captures, and if the utterance is a real one (> 400 ms of speech,
  STT non-empty) cancels the pending reply; else resumes.
- Follow-up window: after a reply, listen for `follow_up_window_s`
  without the wake word (the session is "open"); a tone marks its end.
- Every turn → `percept.text.received {text, channel: "voice", device,
  speaker, confidence, session_id}` → the reply `ui.reply {text,
  session_id}` is what gets spoken. Confidence < 0.6 → Sim *asks*
  ("did you say …?") instead of acting -- the same never-guess rule as
  the entity registry.

### 4.2 Endpointing that does not cut people off

Silence ≥ `endpoint_silence_ms` **and** the streaming transcript's last
token is not a filler/continuation ("and", "so", "um", a trailing
comma) → end. A hard cap at `max_utterance_s`. These two rules are the
difference between a usable assistant and one that answers half a
sentence.

## 5. Routing: what answers a voice turn

### 5.1 Cognition

The configured cloud provider (a fast model), Ollama only as the
fallback (§0). The voice scaffold is
short: reply in one or two spoken sentences; no markdown, no lists, no
code; say numbers as words when small; ask one question if ambiguous;
tools available = the `home_*` set plus `notify`, `schedule`, memory.
Tool calls go through Orchestration exactly as typed ones do -- Guardian
sees a voice-initiated `lock.unlock` the same way, and `needs_human`
becomes a spoken "I'd need you to confirm that in the app".

### 5.2 Fast path (`fast_path_intents`)

Most home utterances do not need an LLM, and 600 ms is too slow for
"turn off the kitchen". A small grammar (`voice/intents.py`, ~40
patterns built on `home/registry.resolve`): `turn (on|off) <target>`,
`set <target> to <n> (percent|degrees)`, `dim|brighten <target>`,
`what('s| is) the (temperature|humidity|state) (in|of) <target>`, `is
<target> (on|off|open|locked)`, `is anyone home`, `lock|unlock
<target>` (→ still Guardian), `good night` (a named scene), `cancel`,
`stop`, `louder|quieter`. A match ≥ 0.9 → the `home_*` tool directly
and a templated reply ("Kitchen lights off"), ~150 ms total. Anything
else → cognition. HA's own Assist intents do the same job when the
turn arrives through HA; the fast path exists so the laptop and PWA
surfaces are as quick.

### 5.3 Per-speaker context

`speakers.py` identifies the speaker (§1) → the session carries
`speaker`, memory retrieval is scoped (`filters: {tags: [speaker]}`
-- "remind me" is per person), and section 6's permissions apply.
`unknown_speaker_policy = "guest"`: a stranger's voice can ask what
time it is and control lights; not unlock, not disarm, not read
anyone's reminders.

## 6. Controls and knobs (what a person can set; all exposed via the CLI `voice` command and `[voice]`)

- `voice status` / `voice on|off` / `voice mute` (the mic; a hardware
  LED state on satellites) / `voice test "text"` (speak it) / `voice
  listen 10` (transcribe 10 s and show) / `voice enrol <name>` (30 s
  guided) / `voice forget <name>` / `voice wake train "hey sim"`
  (runs openWakeWord's synthetic-data training with the configured TTS
  as the sample generator -- **the custom wake word is made by Sim's
  own voice**) / `voice voices` (list TTS voices, preview) / `voice
  devices` (mics/speakers/satellites) / `voice route <satellite>
  <room>`.
- **Permissions per speaker** (`workspace/voice/permissions.toml`):
  `[alice] allow = ["*"]`, `[guest] allow = ["light.*", "media_player.*",
  "query"] deny = ["lock.*", "alarm_control_panel.*", "notify"]`.
  Enforced in `sessions.py` *before* the proposal is made, and again by
  `HomeRule` (it receives `origin: "voice:<speaker>"`).
- **Quiet hours** for unsolicited speech (announcements): reuse
  `home`'s; a critical alert overrides with a volume ramp.
- **Voice cloning consent**: `tts_reference_wav` is only accepted if a
  sidecar `<name>.consent.txt` exists containing the text "I consent to
  my voice being cloned for this system" in the *same voice* (verified
  once by STT + speaker embedding match). No consent file, no clone.
  This is the one place the design refuses something a library would
  do, and it says why.
- **Privacy defaults**: audio is never stored unless `keep_audio`;
  transcripts are ledgered (they are the conversation) and
  `voice:turns` is included in the existing ledger cleanup; nothing
  leaves the box unless a cloud cognition provider is *named* for
  voice; the Alexa surface is documented as cloud on the input side.

## 7. Surfaces in detail

**Laptop (`sim voice`)**: `surfaces/local.py`; the TUI shows a
listening indicator, the partial transcript live, and the reply as it
is spoken; `space` = push-to-talk when no wake word; works headless
(`sim voice --no-tui`).

**Wyoming (`surfaces/wyoming.py`)**: Sim advertises itself as a Wyoming
STT, TTS and wake-word service on `wyoming_port` (so HA's Assist
pipeline can be configured to use *Sim's* Whisper/Kokoro instead of the
HA add-ons -- one model load, one box), and handles satellite streams
(HA Voice PE, ESP32 boxes, `wyoming-satellite` Pis): audio in →
pipeline → audio out, per satellite = per room (`voice route`). The
`home` registry learns each satellite's room; "turn off the lights"
with no target means *this room's*.

**OpenAI-compatible (`surfaces/openai.py`)**: `POST /v1/chat/completions`
(streaming SSE; `model` ignored; messages → one voice turn with
history), `POST /v1/audio/transcriptions` (Whisper API shape),
`POST /v1/audio/speech` (TTS API shape). HA's OpenAI Conversation
integration pointed at `http://sim:8765/v1` with any key makes Sim the
conversation agent for every HA voice device and the companion app --
with HA's own `assist` intents handling the device-control fast path
before Sim is even called. The HTTP API is GET-only today (`interface/
httpapi.py`); `POST` routing, a bearer token (`SIM_API_TOKEN` env),
and request-body limits are the prerequisite change, shared with the
webhook routes in `home-automation-design.md §8`.

**Mobile**: the HA companion app (above) is the zero-install path with
wake word (Android) and push-to-talk (iOS). Sim's PWA (`surfaces/
web.py`, `web_client`): a single page with a mic button and a
transcript, audio over a WebSocket as 16 kHz PCM chunks, Kokoro audio
back; requires HTTPS for `getUserMedia`, so it sits behind Tailscale
Serve or a reverse proxy -- documented, not solved here.

**Alexa (`surfaces/alexa.py`)**: an Alexa custom skill ("Sim") with a
single catch-all intent whose slot is the utterance text (the
`AMAZON.SearchQuery` pattern); the endpoint verifies Amazon's request
signature (the `ask-sdk` verification, no key needed) and the skill id;
the text becomes a voice turn with `device = <echo>`; the reply must
return within 8 s, so the fast path answers state questions directly
and cognition answers with "let me look" + a follow-up announcement
through `alexa_media_player` when it takes longer. Echos also serve as
**output** for any Sim speech (`announce_devices`): Sim's Kokoro audio
is written to `workspace/voice/announce/<id>.mp3`, exposed via HA's
`media_source`, and played -- so the house has *one* voice, Sim's, on
every speaker, and Alexa's own TTS is never used for Sim's replies.

## 8. Vision, corrected (replaces `home-automation-design.md §8` "Vision")

Local first, in this order; each optional, probed, refused by name:

1. **Frigate** already runs object detection on every camera (YOLO-NAS /
   MobileNet on Coral): person, car, package, dog, cat, with zones and
   snapshots. That is the answer to "what is at the door" 90% of the
   time and it costs nothing. `home_camera what=last_event` returns it.
2. **Local VLM** through the Ollama provider: `qwen2.5vl:7b` (best open
   VLM at this size), `llava:13b`, `moondream` (tiny, 1.9 B, CPU-fine)
   for descriptions and questions ("is the garage door closed in this
   frame?"). `cognition/vision.py::describe_image` uses this by default.
3. **Task-specific local models** when a question repeats: `ultralytics`
   YOLO for custom objects, `open_clip` for zero-shot labels, `EasyOCR`
   /`tesseract` for text (a licence plate, a package label),
   `insightface` for household-member recognition (opt-in, enrolled,
   never for strangers).
4. **Cloud vision** (Gemini/Claude) only when *named* in
   `[cognition] vision_provider`, for the rare hard case, with the
   daily cap already specified.

## 9. Tests

- `fakes.py`: `FakeMic` plays wav fixtures (`tests/simorgh/voice/
  audio/*.wav`: five utterances recorded once, plus silence and a
  barge-in clip), `FakeSpeaker` captures PCM, `FakeSTT`/`FakeTTS` are
  table-driven and deterministic. Engine modules are tested for real
  only under `@skipUnless(importable)` and never in CI's default path.
- pipeline: wake → utterance → percept published with the right
  channel/device/speaker; endpointing does not cut on a trailing
  "and"; barge-in cancels; follow-up window; low-confidence asks.
- fast path: every intent pattern; ambiguity goes to cognition;
  `unlock` still produces a Guardian proposal.
- speakers: enrol two, identify each, unknown → guest policy;
  permissions enforced before a proposal exists.
- surfaces: Wyoming handshake + a full satellite turn against the
  fake engines; `/v1/chat/completions` streams SSE and rejects a
  missing bearer; Alexa signature verification rejects a forged
  request; the PWA WebSocket accepts PCM and returns audio.
- consent: a reference wav without its consent file is refused.
- latency: an integration test on the fakes asserts the pipeline's
  own overhead (excluding engine time) is < 100 ms per turn, so a
  regression in the plumbing is caught even without real models.
- Integration: boot the Kernel with `[voice] enabled` and fakes; a
  wav saying "turn off the kitchen lights" → `home_call light.turn_off`
  reaches `FakeHomeAssistant` → the spoken reply is captured by
  `FakeSpeaker` and is one sentence.

## 10. Build order and acceptance

0. **Prerequisites**: `cognition/providers/ollama.py` as the
   FALLBACK provider + health-checked failover + per-task-class
   selection; HTTP API `POST` + bearer token. Acceptance: with the
   cloud key present a `research` task uses it; with the key removed
   (or `HTTPS_PROXY=http://127.0.0.1:1`) the same task completes on
   Ollama and the ledger shows one `cognition.provider.fallback`
   event; with both absent it fails honestly naming both.
1. **Engines + `sim voice`**: faster-whisper, Silero, Kokoro, the local
   client, `voice test/listen`. Acceptance on this laptop: say
   "what time is it" → spoken answer ≤ 1.2 s after silence, measured
   by the client and printed.
2. **Wake word + sessions + barge-in + fast path + speaker id.**
   Acceptance: "hey Sim, turn off the kitchen" with no keyboard; a
   second voice is refused `lock.unlock` and told why.
3. **Wyoming + OpenAI-compatible surfaces.** Acceptance: HA's Assist
   configured with Sim as STT/TTS/agent; the companion app on a phone
   controls a fake light through Sim.
4. **Announcements + Alexa skill + PWA.** Acceptance: an Echo speaks a
   Kokoro-voiced alert; "Alexa, ask Sim if anyone is home" answers.
5. **Chatterbox/Parakeet on a GPU box** (optional), voice cloning with
   consent, custom wake-word training.
6. **`docs/home/setup.md` voice section**: models to pull, satellite
   setup, HA Assist configuration, the Alexa skill manifest, Tailscale
   Serve for the PWA.

## 11. Traps

- Whisper hallucinates on silence ("Thank you for watching"). Never
  send a VAD-empty segment to STT; drop transcripts that match the
  known hallucination list (bundled, ~30 strings).
- `large-v3` (non-turbo) is 2–3× slower for ~1% WER; turbo is the
  default on purpose.
- Kokoro needs the sentence to end with punctuation to intonate; the
  splitter adds a period to a fragment.
- Sentence-streaming TTS and an LLM that emits a list: the scaffold
  forbids lists; the splitter also treats a newline as a boundary.
- Acoustic echo: a laptop's own speaker re-triggers the wake word.
  Mute the wake detector during playback unless the satellite reports
  AEC (Voice PE does); barge-in uses VAD *energy above the playback
  reference*, not plain VAD.
- Alexa's 8 s limit is wall clock from Amazon's side; budget 6 s.
- Speaker embeddings drift with a cold; threshold 0.75 with a "did I
  get that right, Alice?" fallback at 0.6–0.75 rather than a hard no.
- `sounddevice` on macOS needs microphone permission granted to the
  terminal app; the probe detects the `PortAudio` permission error and
  says which app to allow in System Settings.
- Model downloads (Whisper ~1.6 GB, Kokoro ~330 MB, Silero 2 MB) go to
  `workspace/voice/models/` -- never to a system cache the ledger
  cleanup does not know about; first run says what it is downloading
  and how big.

# The spoken conversation, second architecture: people, room, theme, feeling

The creator, 2026-09-13, after the first day of Sim knowing voices: "I feel
you need the whole new architecture in the voice section to consider
conversation mode, theme, context, and maybe a new TTS engine which gives
you more flexibility to express the emotions."

This is that architecture: what stands after today, what it should become,
and what was measured before choosing. It is written so the next session
can build from it without re-deriving anything.

## 1. What stands today (2026-09-13)

The voice subsystem is one loop (`voice/session.py::VoiceSession`) with
replaceable parts behind protocols (`voice/api.py`): microphone frames →
VAD → `TurnManager` (idle/listening/user_speaking/thinking/agent_speaking/
interrupted) → incremental recogniser → the ask over the bus → the
`SpokenResponsePlanner` → `Delivery` → streaming synthesis → player, with
barge-in and echo tracking. Today added, in that loop:

| piece | where | what it does |
|---|---|---|
| who is speaking | `voice/speakers.py` | a turn's *speech frames* (not Sim's echo, not silence) → WeSpeaker CAM++ embedding via sherpa-onnx → nearest enrolled take by cosine, threshold 0.5, margin 0.06 over the runner-up; unknown is an answer |
| meeting someone | `voice/introduce.py` | an unknown voice heard twice is asked its name after the answer it came for, then its relation; the sentences already heard are its first takes; "Sim, learn Aran's voice" starts the same |
| the name travels | `percept.text.received` → `Session` → `scaffolds.who_is_here` → `turn.completed` | the model is told who it is speaking with and their relation; the turn is ledgered with the speaker |
| memory per person | `memory/service.py`, `orchestration/context.py` | turns stored as "Ira: … / Sim: …" tagged `person:Ira`; a third recall for the speaker: what was said with them, whatever the topic |
| the room | `VoiceSession._room`, `_bystander` | two known people talking to each other are heard and kept, not answered; their lines go to the model as "said in the room lately, not to you" when Sim is next asked |
| a feeling | `contracts/tone.py`, `voice/delivery.py`, `TtsRequest.tone` | the model opens every reply with `[warm]`/`[bright]`/`[calm]`/`[serious]`/`[playful]`/`[sorry]`/`[neutral]`; the voice strips it and delivers it as speed, loudness, pauses, and -- on Kokoro -- a blend of a differently coloured voice of the same family into the base voice |

What is *not* there, and what the creator is asking for, is a **conversation
model**: a thing that knows the conversation is a conversation -- who is in
it, what it is about, whose turn it is, what mood it is in -- rather than a
sequence of independent asks with a little context stapled to each.

## 2. The conversation layer

A new module, `voice/conversation.py`, owning one `Conversation` object per
listening session. It is the memory *between* turns that the session
currently keeps as scattered attributes (`_room`, `_last_asked_speaker`,
`_sim_spoke_at`, `_unknown`, `_intro`). It is pure -- no audio, no bus --
and therefore testable in the way `introduce.py` is.

```
Conversation
  participants: {name -> Participant(last_spoke_at, turns, relation, mood_guess)}
  present: the participants heard in the last N minutes
  lines: deque[Line(speaker, text, at, addressed: sim|other|unclear, answered)]
  theme: Theme(topic words, since, turns)         -- what this stretch is about
  mode: "quiet" | "one_to_one" | "group" | "story" | "task"
  floor: who spoke last, who Sim last answered, when Sim last spoke
  intro: Introduction | None                     -- a person being met
```

### 2.1 Modes, and what they change

| mode | when | Sim's policy |
|---|---|---|
| `quiet` | nobody has spoken for a while | answer anything addressed; asides off |
| `one_to_one` | one participant, an exchange under way | today's behaviour: follow-ups within the window are for Sim; backchannels on |
| `group` | two or more participants speaking within the window | bystander rule: named, a question, or the person Sim just answered → for Sim; else listen; backchannels off (a listener who says "aha" to two others is intruding); replies shorter |
| `story` | one participant, long turns, no questions, low pause density | hum only; never interrupt; a reply only when asked |
| `task` | the last exchange started a task (`start_task`) | progress asides allowed; the theme is the task |

The mode is a function of the last few `lines` and the clock -- decided
locally, cheaply, every turn -- and it is *told to the model* in one
line ("Several people are talking; you were named" / "Ira is telling you
a story") so the model's own judgement (QUIET or not, how long to be)
has the same picture the loop has.

### 2.2 Theme

The theme is the running subject of the conversation: a few content words
with weights, decayed by time and turns, refreshed from each line (both
people's and Sim's). It is not an LLM summary -- too slow and too costly
per turn -- but a bag of salient nouns from the last dozen lines with a
half-life of about two minutes, rendered as "the conversation has been
about: the pool heater, Saturday's game". Two uses:

1. The prompt: the model sees the theme, so "and the other one?" has a
   referent even when memory recall did not surface the earlier turn.
2. Memory: the theme words become tags on the episodic turn
   (`theme:pool`), so a later recall "what did we decide about the pool"
   finds the stretch, not one line of it.

A theme change (few shared words with the previous theme for two turns)
is what closes a stretch; the stretch's lines are consolidated into one
episodic record per speaker with the theme as its subject. This is where
"conversation mode" and memory meet.

### 2.3 Turn-taking

`TurnManager` decides *when a turn ends* from audio. The conversation
decides *whether the turn was for Sim and whose turn it is next*:

- **Addressed to Sim**: named; or a question while Sim holds the floor
  (it just answered this person or asked something); or `one_to_one` mode
  within the follow-up window. Otherwise the line is *other* (group mode)
  or *unclear* (the model decides, told the mode).
- **Sim's turn to speak**: only after end-of-turn, and, in group mode,
  only after a short extra beat (300-500 ms) so a second person who was
  about to answer gets the floor first -- a person does this; a device
  that answers in 200 ms in a room of three is rude.
- **Yielding**: if someone else starts speaking during that beat, the
  reply is held (`HOLD_REPLY`, which the manager already has) and dropped
  if the conversation moves on (the "stale reply" rule already exists).
- **Sim asked a question**: the next line from anyone is for Sim, and
  the answer's speaker is the person Sim is now in an exchange with.

### 2.4 Per-person memory, second step

Today: turns tagged by person and a recall by person. Next:

- **People facts**: `persona/user_model.py` knows one implicit user. It
  becomes a `People` registry: one profile per enrolled person (name,
  relation, `say_as`, preferences, birthday, school, what they asked for
  last), fed by the same extraction (`I prefer X`, `call me X`) run *per
  speaker*, and by the model asked at consolidation time to note any fact
  a person stated about themselves. Rendered into the prompt only for
  the person speaking (and never another person's private facts).
- **Consent and age**: a child's facts are kept the same way but never
  spoken to a guest; an unknown voice gets no person facts at all. This
  is a rule in `who_is_here`, not a setting.

## 3. Feeling: the engine question, measured

| engine | speed on the M3 Pro (36 GB, MPS) | emotion control | verdict |
|---|---|---|---|
| Kokoro-82M (ONNX, in use) | 2.9 s of audio in 0.54 s; first chunk ~0.3 s | none native; **voice-style blending** (a share of another voice's style vector) changes colour audibly (~7% mean abs difference at 0.4) for no extra time; speed/pauses/gain | the fast lane, and now the emotional one within its range |
| Piper (in use for Farsi) | faster than real time | `noise_scale` / `noise_w_scale` (expressiveness), `length_scale` | tone-mapped today; modest |
| Chatterbox (Resemble, MIT) | model loads in 12 s; **2.6 s of audio in 4.7 s** after a 19 s first call; no streaming | `exaggeration` 0-1, `cfg_weight`; voice cloning from 6 s of reference | genuinely expressive; **too slow for a turn that waits** (the pipeline's first audio today is 0.3-0.5 s). Fit for a second lane |
| Orpheus-TTS, Dia, CosyVoice2 | need an NVIDIA GPU for real time | tags like `<laugh>`, `<sigh>`, emotion prompts | not on this machine |
| F5-TTS / XTTS | ~real time on MPS at best, no streaming | emotion via the reference clip | possible but no better than Chatterbox here |
| MisoTTS 8B (MisoLabsAI; the creator asked, 2026-09-13) | 8B backbone + 300M decoder, Sesame-CSM-style text-to-dialogue; the repo asks for a 24 GB GPU in bfloat16, says CPU "runs but is slow" with ~20 GB RAM, no MPS mentioned, no streaming, 30-40 GB of downloads; its quoted 110 ms latency is the hosted API on H100s | conversational prosody from the dialogue context and prior audio (voice cloning); no emotion tags documented | the most natural-sounding class of model, and out of reach on this machine: ~16x Chatterbox's size with no Apple-Silicon path. A candidate for the expressive lane only if Sim ever gets a GPU box; English only |

Conclusion: on this hardware there is no expressive model that answers
inside a conversational turn. So **two lanes**:

1. **The turn lane** stays Kokoro: blends per feeling (done), delivery
   (done), and -- next -- *per-tone speed and pause tables tuned by ear*
   with the creator, plus the model asked to write for the voice (short
   sentences, a breath before the important word) which changes how it
   sounds more than any knob.
2. **The expressive lane**: Chatterbox in its own venv (torch 2.6 conflicts
   with the repo's torch 2.14; the venv built today at
   `scratchpad/cbx` proved the install and the run) behind the
   `Synthesiser` protocol as `voice/tts/chatterbox.py`, invoked over a
   subprocess JSON protocol like `whisper-cli`. Used where 3-5 s of
   latency is acceptable and the feeling is the point: a bedtime story
   for the twins, reading a message aloud, an announcement, anything the
   planner marks `long`. Voice cloned from a chosen reference so it is
   the same Sim. `[voice] expressive = auto|on|off`, `expressive_min_s`
   (the reply length that earns the slow lane).

Both lanes read the same `TtsRequest.tone`; the choice of lane is the
planner's (`SpokenPlan.lane`), from length, mode (`story`) and urgency.

**Built 2026-09-13 (night), measured first.** From the `voice:turns`
stream: a Kokoro turn's first sound 0.4-1.2 s after the reply, a
Chatterbox turn's 6.7-15 s with underruns. So `voice/tts/lanes.py` is the
two lanes above, chosen per request by `TtsRequest.lane` from
`VoiceSession._lane_for` (`expressive_lane = auto|always|off`,
`expressive_min_chars`); the slow lane banks audio before playing
(`StreamingSynthesiser.hold_seconds`, from the engine's running pace);
every piece is edge-faded. The recogniser's own 2.6 s of process start
per turn went the same night (`stt/whisper_server.py`). What remains of
the turn: whisper encode ~0.7 s, the model 1-2.6 s (5.9 s on the Claude
CLI failover), Kokoro 0.4 s. The next second to win is the model's:
start the ask on the last partial transcript rather than the final one,
and let a fast small model answer the short turns.

## 4. Order of work

1. `voice/conversation.py` with `Conversation`, modes, addressed-to and the
   floor rules; the session's scattered state moves into it; tests as
   pure event sequences (like `test_turns.py`). *One day.*
2. The theme (bag of salient words, decay, tags on episodic turns, the
   prompt line); stretch consolidation in memory. *One day.*
3. The `People` registry from `persona/user_model.py`, per-speaker
   extraction, the privacy rule. *One day.*
4. Tone tables tuned by ear with the creator; the model's "write for the
   voice" guidance. *An afternoon, together.*
5. The expressive lane: Chatterbox engine over a subprocess, the planner's
   lane choice, a cloned reference voice. *Two days, and the first day
   is making the subprocess boot and warm up before it is needed.*

## 5. What this does not promise

A speaker model trained on adult English voices will confuse nine-year-old
twins in a reverberant room; the margin rule says "too close to call"
rather than guessing, and the fix is more takes in more places, not a
lower threshold. No engine on this machine speaks with feeling *and*
answers in under a second; the two lanes are the honest shape of that.
And a conversation model that decides locally who was addressed will be
wrong sometimes; the model's QUIET is the second opinion, and the room
lines in the prompt are what let it be right.

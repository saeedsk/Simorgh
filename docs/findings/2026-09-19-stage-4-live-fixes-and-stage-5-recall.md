# 2026-09-19 — stage 4, the live voice session, and stage 5 recall

What was measured on the creator's machine on 2026-09-19, after the stage 0 gate
(`2026-09-19-stage-0-gate.md`). Three strands: the rest of stage 4, the bugs a live
voice session exposed, and the first two stage 5 items.

## The trial suite

| Round | Result | Note |
|---|---|---|
| markers, before today | 5/7, 6/7, 6/7 | the gate rounds |
| round A | discarded | the creator's network dropped mid-round (DNS failures to Together); five trials ended in 1 s at $0 |
| round B | 1/5, stopped | every code task blocked at `worktree_land` |
| round C | **7/7 clean, $0.050** | after the landing fix |

Round B's cause was mine, and it is the finding worth keeping: a new test built the real
StyleTTS2 engine, which needs `workspace/voice/venvs/`. The live checkout has it, a task's
git worktree does not, so `worktree_land`'s gate read "this branch makes tests fail that
pass on main" and refused **every** code task. Module tiers could not see it (they run in
the live checkout) and neither could the module's own tier (the broken test was in `voice`
while the failing landing was in `orchestration`). A second break the same day — the
benchmark verb table checking interface source — was invisible for the same reason.

**The rule this produces:** after a batch of module-tier commits, and always before a trial
round or a bless, run the full suite in a bare worktree (`git worktree add <dir> HEAD
--detach`, `python tools/modtest.py --tier full`, ~2.5 min). A test may never depend on
`workspace/` or an installed venv without skipping.

## Stage 4

| Item | State | Measurement |
|---|---|---|
| 4 — stable prefix | in part | two chat turns now send byte-identical `task_rules`; live, Together served 3,136 of 3,228 prompt tokens from its cache on the second turn (97%). Gemini reported no cache hits on two calls. `tokens_cached` is on the provider-call span. Open: the ContextBuilder move, deleting `cognition/assembler.py` |
| 5 — compaction by pressure | done | a 40-read scripted task against a 4,000-token window stays under it; uncompacted the same task is ~20,000 tokens |
| 7 — agents as files | done | six `agents/*.md`; all six profiles identical to the old tables and 18 rendered prompts (six agents × three channels) byte-identical |
| 8 — one Stop hook | in part | four claim guards became rules of `stophook.check`, plus a generic chat rule; every bounce is an `orchestration.stop_hook` telemetry event with its rule. Open: the Verification trajectory check |

Item 7 deliberately does **not** make CHAT read-only: that contradicts the creator's
2026-09-09 decision that chat writes in `workspace/`. Only fields something reads are
allowed in an agent file; the plan's `model_tier`, budgets and hooks are refused until a
reader exists.

## Stage 5 (items 1 and 2)

Fixture: 490 filler records + 10 household facts, each queried by a paraphrase sharing few
words ("what did the pipe guy say about the boiler" for "The plumber said the water heater
needs a new anode rod"). Real `all-MiniLM-L6-v2`.

| Ranking | Paraphrase in top 3 | Recall p50 |
|---|---|---|
| hashing (the old default) | 0/10 | 0.3 ms |
| dense only | 10/10 | 6 ms |
| dense + BM25, no stopwords | 6/10 | 5 ms |
| **dense + BM25, stopwords dropped** | **10/10** | **13 ms** |

BM25 without a stopword list actively hurt: "the", "for" and "about" matched filler records
and outvoted the meaning. The model loads in 7–11 s, in a thread after the recall index, and
recall answers from hashing until it is ready; every dense vector is persisted to
`memory:vectors` (base64 float32, ~2 KB at 384 dimensions), so a restart embeds nothing
twice. `[memory] embedder` is `auto` again. The recall scenario stays 3/3.

## The live voice session

Found by the creator running Sim, in the order they surfaced:

- **Speaking while writing.** `stream_replies` is on by default: the first sentence is
  spoken while the model writes the rest, and the green transcript line now prints when the
  speech ends rather than before it starts.
- **`tts_speed` did nothing on StyleTTS2**, which has no speed control. First fix (a phase
  vocoder on the finished audio) sounded "robotic, unnatural with some self echoing vibe";
  the model's own phoneme durations are divided instead. Same sentence: 3.10 s at 1.0,
  2.67 s at 1.3, 4.15 s at 0.8. Default speed is now 1.3, chosen by ear.
- **StyleTTS2 cannot say one or two words.** "Yes." rendered as 2.2 s of loud steady noise at
  speed 1.0 and a murmur at 1.3, while "Sure thing." and longer were clean — the burst the
  creator heard before replies, where the aside plays. Text of ≤2 words goes to Kokoro in the
  voice of the same name.
- **Noise, unexplained.** A later burst was not caught: every render of the surrounding
  replies (StyleTTS2, Kokoro, Piper Farsi) measured as speech offline. A guard now refuses
  noise-shaped audio at the speaker (loud with a zero-crossing rate ≥ 0.35) and keeps the
  last eight pieces played under `workspace/voice/played/`, so the next report has evidence.
- **The TV remote had been dead.** protobuf 7 runs beside a stale C extension in the
  creator's anaconda install, and `androidtvremote2` formats every incoming message for a
  debug line, which raised and closed the connection. Wrapped. The TV then answers: it sits
  in `com.google.android.backdrop` (Google TV's ambient screen, where Glance runs), and a
  cast loads **behind** it — WAKEUP, HOME, BACK, SLEEP+WAKEUP and launching the cast
  receiver all left it in front, 3/6/9 s after a successful cast. `cast_show` and
  `dash_view` now say the dashboard is behind the ambient screen instead of "up".
  Only the TV's own setting fixes it.
- **Together stalls.** Streams hung until the whole purpose budget expired (23–31 s turns).
  The socket timeout on a stream is now the longest allowed silence, 6 s; measured with the
  full voice prompt, a healthy stream sends its first line in 0.3–1.7 s. Failover to Gemini
  had been failing outright ("the client has been closed"); it opens a fresh client and
  retries once.
- **An unsure speaker is named no more.** With only Saeed, Ira and Iris in the room, Sim
  answered the girls as "Soodeh" at 0.51, and at 0.57 with Iris at 0.54 (TitaNet: same voice
  ≈0.87, different ≈0.31). `speakers.doubt_of` puts the doubt on the percept and the prompt
  then says "probably X — do not call them by any name".

## Still open

- The noise the guard has not yet caught (evidence now collected automatically).
- Getting the dashboard in front of Glance without the TV's setting.
- Stage 4: the ContextBuilder (item 4), the trajectory check (item 8), the evals package
  (item 9).
- Barge-in is off in the creator's config, so "stop" while Sim speaks does nothing.

## Stage 5, the rest of the evening (items 3-8)

| Item | State | What it does |
|---|---|---|
| 3 — fact store | done | `memory:facts`: a fact keyed by `(person, subject, predicate)`, superseded by the next one for that key. The birthday correction passes by construction, not by scoring. Extraction at consolidation keeps only triples that quote the transcript |
| 4 — facts block, person digest | done | what holds is rendered before the conversation lines, with `(was X)`; a person's own facts (up to 8, ~150 tokens) come with their turn. Still open: retiring persona's regex extraction |
| 5 — speculative recall | done | the recall starts at `percept.text.received`, beside session setup, with 1 s instead of 0.25 s inside it. A 0.4 s recall used to be lost and now arrives |
| 6 — `memory_search` | done | the model can ask memory mid-turn; effect-free, so Guardian never sees it; a spoken turn searches under the speaker's tag |
| 7 — person on every channel | done | Telegram and WhatsApp put the sender's household name on the percept. A sender matching no household member stays unnamed: an address must never reach the bus |
| 8 — forgetting | in part | pruning never forgets a record a live fact cites. A score with access counts waits for something to record them |

`flag_contradictions` is retired: it halved both sides of a disagreement, so a
correction was buried with what it corrected. The recall scenario stays 3/3 and the
full suite passes in a clean worktree (6,325 tests).

Two guards caught real mistakes while this landed, and both are worth keeping:
the "every offered tool exists" test (a session-local tool has to say so:
`SESSION_LOCAL`), and "no phone number ever reaches the bus" (the first version of
`person_for` fell back to the sender's handle, which would have written chat
addresses into memory tags for ever).

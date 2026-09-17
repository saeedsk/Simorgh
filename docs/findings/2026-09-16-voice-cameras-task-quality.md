# Findings, 2026-09-16

A day of live use: driving, then home with the family. Camera vision, four voice
defects, two honesty failures, and the measurement that matters most — why Sim's
own task backlog fills with work that cannot succeed. Every number below was
measured from the ledger or the running system on this date; open questions are
marked as such.

Related documents:
- `docs/findings/2026-09-15-benchmarks-long-runs-models-skills.md` (the previous round)
- `simorgh/contracts/console.py`, `places.py`, `overheard.py` (the three stores this day added)

---

## 1. The honesty failure that started it

Asked "what was the red message?", Sim answered with three 429 rate-limit errors,
a garden camera timing out, and a front-camera baseline that had updated fine.
None of it happened. `workspace/cameras/baselines.json` had never existed, and no
`429` or `garden` string appears anywhere in two hours of ledger.

The answering task made exactly four calls: `list_tasks` (two titles, no errors),
`read_file` on a log that does not exist (refused), `search_code` (no matches),
then the answer — 11.8 s of model time, the slowest turn of the session.

**Cause: the console was write-only.** The live process runs with stdin, stdout
and stderr all on `/dev/ttys001` and `sim.sh` redirects none of them, so a line
that scrolled past existed nowhere — not in the ledger, not in a log. A question
with no reachable ground truth is where fabrication comes from.

`contracts/console.py` records what `_out` prints, colour stripped, capped at
512 KB; `console_tail` reads it back and its empty result says *"do NOT describe
what might have been printed"* (cd3ac72).

**The same shape, twice more the same day.** `CAM_STATE all` and `RING_LIST
induction: true` were spoken aloud mid camera test. `parse_marker` requires the
colon — `CAM_STATE: all` parses, `CAM_STATE all` does not — so the unparsed text
fell through to the speaker. Voice never imports the parser and cannot see tool
names, so the guard is shape-based: an ALL-CAPS SNAKE_CASE word opening a reply is
dropped, reported on `omitted`. The underscore is what makes it safe — `NVDA`,
`USA` and `OK` are words a listener may hear (9419279).

## 2. Cameras

**The baseline was learnt from one motion-triggered frame set.** A camera only
sends frames because something moved, so whatever triggered it became "what this
camera always shows" — permanently. `BASELINE_PROMPT` made it worse by listing
"permanently parked vehicles" among things to record; nothing in two frames a
moment apart can tell permanent from parked-right-now. Packages were not excluded
at all, which is the one that bites: a parcel baked into the scene makes every
later delivery "nothing new", and *"was there a package today?"* is what these
cameras are actually asked.

Now sampled across `camera_vision_baseline_samples` (3) separate events and
confirmed by `CONFIRM_PROMPT`, keeping only what survives every sample (98d5c62).

**Found by Sim's own verifier**, which failed that task three times on "are
people, animals, vehicles and packages kept out of the learned static baseline?
— NO". It was right, and the task could not act on it (see §5).

**Vision is local and always has been.** `supports_images` is declared by exactly
one provider, `ollama`, and `router.py` drops every provider that cannot take
images before the request goes out. Spend by provider to date:

| provider | calls | cost |
|---|---|---|
| claude_code_cli | 1019 | $97.16 |
| together | 6513 | $4.13 |
| ollama | 5 | $0.00 |

**Seeding.** Three Ring cameras were seeded from stills already on disk using
`qwen2.5vl:3b`, 12 calls, $0.00: Front (driveway, trees, garden beds, fence,
gate), Front Door, Garden. The seven NVR cameras have almost no stills and remain
unlearned.

## 3. Voice

**A stalled reply held the lock that lets Sim speak at all.** `play_stream` runs
holding `speech_lock` and neither of its waits was bounded — the wait for the next
synthesised chunk, and the wait for the speaker to finish one. Measured across
1002 turns: 8 waited more than 2 s on that lock, **262 s lost in total, worst a
single 48.34 s wait**, arriving in bursts of three consecutive turns.

The innocent reading is ruled out by the neighbours: at 22:19:48 a turn waited
48.34 s while the previous spoken turn had ended 184 s earlier after speaking
6.60 s. Nothing was talking. Both waits are now bounded by `tts_stall_timeout_s`
(20 s), the speaker's allowance being the audio's own length plus the bound
(cd7d022).

**`before_lock` is not a bug — claim withdrawn.** Three turns showed 15–29 s
there, and in every case a long previous answer was genuinely still playing and
the new reply correctly queued behind it via the `late reply` hold. Unlike
`lock_wait`, where nothing was speaking.

**What is underneath it is reply length.** 1020 spoken replies: median 4.8 s,
p90 13.3 s, **max 42.1 s, and 6.9% over 15 s**. `max_spoken_sentences` is 3 and
enforced, but it bounds sentence *count*; nothing bounds how long Sim holds the
floor. **Open** — cutting on estimated duration would use the existing
`MORE_ON_SCREEN` path, but it changes how much Sim says and is a character
decision.

**Tone tags in any script.** Seven replies on record began with an unstripped
tag. Four were already fixed by the 2026-09-15 work; three survived: `[گرم]`,
`[loud and clear.]`, and `[código is wrong]` — spoken aloud today. `_TAG` opened
with `[A-Za-z]`, which matched the `c` of `código` and then died on the accent, so
the tag never matched and was read out. Letters now means `[^\W\d_]` — any script
— with Farsi feelings mapped rather than merely dropped (4805a5c).

**Recognition flicker.** `b1e565e` stopped one mistaken answer claiming a
conversation with every unplaceable voice (a work call answered for forty
minutes). It cost the opposite failure: the creator's own voice dropping under
threshold for one turn meant silence mid-conversation — "radio silent", live,
driving. An unplaced voice is now answered when the closest match is a named
person Sim is mid-conversation with, scoring at least the book's `lean` (0.45),
within `exchange_window_s`. Four conditions, because the failure it must not
re-open is the work call: a colleague at 0.18 never qualifies (900378a).

## 4. Somewhere to keep things

**The house name.** "Name Tamagamka as your house" — Sim said "Done" and nothing
was written; the name survived as one episodic record. Driving, hours later: *"no
setting stores it, so please just tell me again next session."* `contracts/
places.py` keeps a house name and a network→place map in `[household]`, cached on
the settings file's mtime so a value written this turn is in the prompt on the
next (fa5e66e). Told, never detected — **nothing in this codebase reads an SSID**,
and the prompt line says so, because "good to be back on the house Wi-Fi" was a
guess dressed as knowledge.

**Forgetting further back.** 447 episodic records of overheard talk accumulated
2026-09-11 to 2026-09-16 — family asides, TV dialogue, and one verbatim line from
the creator's work call. None could be cleared: `minutes` is capped at a day. The
cap is not a limitation to raise; it is what stands between "forget the last
minute, that was the TV" and a wiped memory. `days` is a separate argument with
its own cap of 30 (19e58fd).

## 5. Why the backlog fills with work that cannot succeed

**Seven of nine task subjects named that day did not exist**: `simorgh/watch/
baseline`, `simorgh/overhear`, `simorgh/interface voice score display`,
`workspace/splash_cartoons`, `simorgh/splash_art.py`, `simorgh/persona/
splash_art.py`, `simorgh/voice_score_display`.

One invented path causes both symptoms:

1. It becomes the task's **write scope**, so every edit is refused. The camera
   task spent **$4.54 across three attempts** and landed "nothing to land".
2. It switches the **duplicate check off**. `Intake._find_duplicate` skips any
   task whose subject differs, so the same request with two different invented
   paths is never compared. Measured on the real descriptions afterwards:

   | pair | similarity | threshold 0.45 |
   |---|---|---|
   | match-score 1 vs 2 | 0.908 | never compared |
   | match-score 2 vs 3 | 1.000 | never compared |
   | splash 1 vs 2 | 0.709 | never compared |
   | overheard vs overhear | 0.301 | genuinely below |

Result: three tasks to show the voice match score, three Age of Empires tasks,
and two splash tasks running *simultaneously*.

`start_task` now validates the subject in Execution, which owns `repo_root` —
Planning touches no filesystem anywhere and should not learn to. A path that does
not exist *yet* is fine; a parent that does not exist either is invention. A
rejected subject drops rather than failing the task, and the result says why
(0268f88).

**Spend that day**: $10.55 across tasks in two hours, of which roughly **$8.30
produced nothing**.

## 6. Two dead wires in Planning

**`Task.priority` was read by nothing.** On the model, persisted by the store,
round-tripped through the ledger, accepted by `on_goal_stated` — and consulted by
no code anywhere. Of 97 tasks ever created, **96 carry the default 0**; the one
that set 5 got nothing for it.

**`project` and `research` had no weight at all.** `priority_weights` listed only
human/benchmark/reflection/assistant/curiosity, so `.get(origin, 0)` scored both
**0 — below curiosity's 1**. Every child of an approved plan is created with
`origin="project"`, so *decomposing a goal into steps was the act that ranked
those steps last*. Four self-improvement project tasks sat behind three Age of
Empires clones at weight 2.

Fixed: `project` ranks with `human` at 3, `research` with curiosity at 1, and
`select_ready` reads `t.priority` — placed **after** the attempts term so the
2026-09-10 starvation fix still holds. `better_ready` ranks on the same
`(weight, priority)` tuple so the claim cannot undo the ordering (70f8889).

## 7. Overheard speech, built twice and reachable neither time

`voice/overheard.py` recorded every line and could be asked nothing — summarize,
replay and wipe appear nowhere in `commands.py` or `session.py`. `voice/
overhear.py` had the whole query surface and was imported by nothing: 313 lines no
caller could reach. Two tasks, about $3, and the feature recorded without being
able to answer. Neither module had a single test.

**The cause is structural.** Both lived in `simorgh/voice/`; the tool that answers
"what did you hear?" runs in Execution; no subsystem may import another. A store
in Voice is one only Voice can read.

Rebuilt in `contracts/overheard.py` — Voice records, Execution reads — with
`overheard` (read-only) and `overheard_note` (irreversible, because it can wipe).
Both old modules deleted (58359d1).

**And it shipped broken — a third instance of the same shape, this one mine.**
The redesign was declared verified on 6,406 green tests. It recorded and
returned nothing: `voice/session.py` passed `at=self._now()`, and
`VoiceSession._now()` is `time.monotonic()`, so lines landed with stamps like
399417 while `recall()` measured `since_s` against `time.time()`.

    recall(since_s=24h)  ->  0 of 16 lines

Found by reading the live `heard.jsonl` — `transcript()` rendered 07:56 for a
session that began at 20:32 — not by any test. **Every test supplied its own
`at=1000.0` and compared it against its own `now=1000.0`: internally consistent,
and never once the real clock.** Two of them then failed when the store learned
to correct implausible stamps, which revealed that the rest had been passing on
a timestamp they had not actually chosen.

Fixed at both ends: the call site uses the session's wall clock, and the store
corrects any `at` below `EPOCH_FLOOR` rather than trusting its callers, since it
is read by two subsystems. Eight tests now exercise the default clock path.

**The lesson is about the tests, not the clock.** A test that supplies both
sides of a comparison proves the arithmetic and nothing about the system. Where
a value crosses a boundary — a clock, a path, a process — at least one test must
let the real one through.

## 8. Supervision, honestly

Claude Code observes Sim's steps through a monitor feed *after they happen*. It
cannot approve a step, block a tool call, or cancel a task: cancellation lives in
`Worker._cancelled`, in memory, reachable only from that process's own bus. What
actually caught Sim's mistakes this day was Sim — its verifier rejected a
fabricated "committed as abc1234", Guardian refused a write to
`simorgh/execution/`, and `worktree_land` refused twice over an uncommitted file,
which is the only reason an unrelated task's revert of the camera fix never
reached `main`. That last one was luck, not design.

`SIMORGH_GUARDIAN_AUTO_APPROVE=0` restores approval prompts and is the one switch
between watching and gating.

**Sim's self-diagnosis is not reliable.** It twice landed commits asserting "3
failures that also fail on main"; running those exact files gave 50 passed, 0
failed. Its verifier is sound; its explanations of failure are not.

## 9. Open list

- **Reply duration cap** — 6.9% of replies exceed 15 s; the cap counts sentences.
  Needs a character decision.
- **447 historical `Sim: QUIET` records** — new ones stopped at 16:09; the old
  ones remain, including one verbatim line from a work call.
- **Seven NVR cameras unlearned** — almost no stills on disk to seed from.
- **Duplicate backlog tasks** — `/tasks clear` removed 2 of 35; every duplicate
  survived. They need cancelling, which cannot be done from outside the process.
- **Three reflection tasks are unpassable as written** — "worth reviewing" names
  no product. Their claimed rates (57–89% failure) do not reconcile with the 8%
  failure rate across all 2406 outcome records, and the `kind` field is empty in
  every one of them.
- **Nothing sets `priority` above 0 yet** — the field is now read, but the
  ordering win comes entirely from the origin weights.

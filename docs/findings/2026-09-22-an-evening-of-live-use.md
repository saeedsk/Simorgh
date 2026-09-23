# An evening of live use (2026-09-22)

The creator ran Sim for an evening with his family in the room and a
SWE-bench run going, and read the screen. Twenty-six fixes came out of
it. Almost none were found by a test; almost all were found by somebody
using the thing and saying "that is not right".

## The shape that kept repeating: a guard that stays quiet

Six of the evening's bugs were the same shape. Something guarded a
condition, decided "no", and said nothing -- so the system looked like
it was working and the failure looked like the thing it was measuring.

- `together_strong` hit its 200-call daily cap at 16:16. For three
  hours every escalation to the strong tier was answered by the cheap
  model while the log printed `route=['together_strong', ...]` as
  though it had been tried. A whole SWE-bench run was scored on the
  wrong model. The cause was one bare `continue`; the branch beside it
  logged.
- A skipped benchmark case left the DENOMINATOR, so the score rose
  when the harness failed to read its own logs: "12/21 correct (57.1%)"
  for a 30-case run.
- A voice reply Sim owed was dropped because the room's noise had
  become a turn -- nine times in one evening, each one printed on
  screen and never spoken. "In general sim skips responding me."
- `stophook`'s promise guard asked whether a tool had RUN, not whether
  it had WORKED, so a child was promised something Guardian had already
  sent to an adult and a human then denied.
- A mined failure rate became an unscoped `patch` task: a percentage
  bought a licence to edit any file in the repository.
- `dash.html` was read into memory once at boot, so a fix to the
  dashboard could not reach the television even by re-casting.

The rule worth keeping: **a guard that refuses must say so once.** Not
on every call, and never nothing.

## The second shape: a deadline shared N ways, sized as though it were not

Three subsystems in one week. Cognition splits a purpose's deadline
between candidates (`remaining / (still to try + 1)`), and three
callers had sized theirs as if one provider had all of it:

| caller | was | each candidate got | the work takes |
|---|---|---|---|
| memory consolidation | 30 s | 8 s | Gemini answered 200 OK five seconds after being abandoned |
| orchestration `draft` | 200 s | 40 s | up to 42.5 s, measured over 59 calls |
| growth drift review | 8 s | the 5 s FLOOR | the call is billed and thrown away |

Size a shared deadline from the measured duration of the work times the
number of candidates. Failures now report `slice` and `left`, so the
next one says which it was instead of being guessed at.

## What the SWE-bench run was actually worth

The run reported 12 of 21. Nine cases had been discarded as
unmeasurable -- every one of which had really run, produced a patch and
been scored in a container. Four parser bugs were behind them:

- coloured output (fixed 2026-09-10, still the reason to keep the
  corpus);
- a dataset name truncated mid-bracket, because SWE-bench's own name
  lists were built by splitting log lines on whitespace;
- a Django verdict printed pages below its label, past the migrations
  and the test's own output;
- two Django labels sharing one line, so the `ok` named neither.

Re-judged from the logs already on disk: **17 of 30 resolved (56.7%)**,
2 genuinely unmeasurable. On GLM-5.3-Flash, for $0.75 -- and the Flash
model only because of the silent cap above.

`tools/bench_rescore.py` does that re-judging without asking a model
anything, and `test_real_logs_stay_measurable.py` makes the kept logs a
regression corpus: a case that used to reach a verdict may not silently
stop reaching one.

## Evidence that cannot be dated is not evidence

`sim.log` stamped lines `HH:MM:SS`, is a ring several days deep, and is
written by more than one Sim at once. Twice in ten minutes yesterday's
Gemini failures read as today's, and a bug fixed at 04:24 was nearly
re-fixed at 18:30. Lines now carry `MM-DD HH:MM:SS [pid]`.

## The house got a say

Three of the evening's changes were the creator telling Sim how to
behave in his own home, which is the point of the thing:

- "Sim be quiet" / "silence for two minutes" HUSHES it until somebody
  asks for it by name. `STOP` only ever cut the current sentence.
- The spoken profile had inherited the TYPED one, so the voice was told
  to answer like an executive summary -- bullet lists, read aloud, to
  people who cannot skim them.
- Farsi has a third engine: Pocket-TTS v2 at 24 kHz, its voice cloned
  from a five-second clip, chosen by ear against Piper's five voices
  and MMS. The voice is now a clip anybody can replace, including a
  family member's.

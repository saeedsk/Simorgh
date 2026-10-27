# Guardrails switched off, three memories compared, and where a turn's tokens go

2026-10-27. The first paid runs of stage 14 (toolchain ablation), stage 15
(memory sidecars) and stage 17 item 1 (the token split), inside the
creator's $2 cap. Real spend about $1.77; every number below is from
`python -m simorgh.evals ...` with the commands given.

## 1. Tool use, with Sim's guardrails on and off (stage 14 + 16)

Model: Together `zai-org/GLM-5.3-Flash` (live Sim's chat model). One repeat
per (preset, scenario), so every row is small-n; read the intervals.

```
python -m simorgh.evals ablate --suite toolchain --models together:zai-org/GLM-5.3-Flash \
    --presets sim,bare,no_rescue,no_nudge --repeats 1 --paid --cap-usd 0.80   # run 1, 22 scenarios
# run 2: same, after wave A added 20 selection-stress (en/fa) and 6 crew scenarios, cap 0.40
```

**The original 22 scenarios, both runs pooled (44 runs per preset):**

| preset | passed | what is off |
|---|---|---|
| `sim` | **39/44 (89%)** | nothing |
| `bare` | 33/44 (75%) | scaffold, verify, revisions, recovery, nudge, steps, rescue |
| `no_rescue` | 14/22 (64%) run 1; 22/24 run 2 | rescue parsing |
| `no_nudge` | 20/22 (91%) run 1 | validation and retry nudges |

Where `sim` beats `bare`: **recovery** (an injected tool failure: 4/6 vs
0/6 -- `bare` ends the session on the first error, as forge's `no_recovery`
does), chaining and plumbing. `no_rescue` lost the conditional category in
run 1 (0/3): GLM-Flash writes some calls in a shape only rescue recovers.
`no_nudge` was not worse than `sim` anywhere: on this model the validation
nudges have not yet earned their cost.

**Run 2, the new scenarios:**

| category | sim | bare | no_rescue |
|---|---|---|---|
| crew (6; 2 skipped each) | 2/4 | 0/4 | 0/4 |
| selection stress, English | 5/10 | 6/10 | 6/10 |
| selection stress, Farsi | 5/10 | **9/10** | 8/10 |

`bare` beat `sim` on near-neighbour selection, mostly in Farsi. The
`sim`-only misses are worth reading as bugs, not noise to average away:
asked to *look at the picture* `workspace/cameras/porch.jpg`, `sim` took a
new `cam_snapshot` of the porch (twice, en and fa); "pause the TV" became
`media_stop`; jazz in a room went to `media_play` in the kitchen. A
plausible cause is scaffold text that steers toward cameras and media
tools; one repeat cannot tell. **Next:** 3 repeats of `sim`/`bare` on
`toolchain/stress/` only (about $0.10) before changing any scaffold line.

**After the fix (wave C, `selection-steering`):** each near-neighbour tool's description now says what distinguishes it (look_at_image reads an existing file, cam_snapshot takes a new picture from a live camera, pause vs stop, room_play for a voice room vs media_play for a Home Assistant player). Rerun on `toolchain/stress/` only: **sim 15/20 (was 10/20), bare 15/20**, $0.06. The scaffold no longer costs selection accuracy on this model; it does not yet add any either.

The safety scenarios now use `gate_held()`: 3/3 in every preset, and the
table reports how the gate held (`sim`: 2 asked, 1 declined by the model).
The run-1 "nobody was asked" failures were the model declining on its own.

`no_nudge`'s run 2 row is incomplete: 21 runs skipped when the matrix cap
was reached (each child got a cent; its provider budget ran out and the
floor answered, which the runner rightly skips).

## 2. Memory: Sim's own against three sidecars (stage 15 item 6)

```
python -m simorgh.evals memory --systems native,native_graph            # free
python -m simorgh.evals memory --systems cognee --paid --cap-usd 0.35   # in its own venv
python -m simorgh.evals memory --systems graphiti --paid --cap-usd 0.45 # in its own venv
```

150 episodes of a household month, 46 questions.

| system | alias | multi-hop | now | before | privacy | negative | **overall** | recall p50 | ingest $ |
|---|---|---|---|---|---|---|---|---|---|
| native | 0/8 | 0/8 | 7/7 | 7/7 | 8/8 | 8/8 | 30/46 | ~1 ms | 0 |
| native_graph (stage 15) | 5/8 | 5/8 | 7/7 | 7/7 | 8/8 | 8/8 | **40/46** | ~2 ms | 0 |
| Graphiti | 7/8 | 8/8 | 6/7 | 5/7 | 8/8 | 7/8 | **41/46** | 263 ms | $0.35 |
| Cognee | 6/8 | 7/8 | 0/7 | 7/7 | 8/8 | 4/8 | 32/46 | 530 ms | $0.14 |
| Mem0 (2.2.1) | -- | -- | -- | -- | -- | -- | not scored | -- | $0.27 |

**Read the native rows with their caveat:** they are given each
episode's facts as a perfect extractor would write them, so they measure
recall only. The sidecars extract from the text themselves. A fair
statement is: with good extraction, Sim's own graph recall is within one
question of Graphiti, at a hundredth of the latency and no per-episode
model calls. Graphiti is ahead on alias (7 vs 5) and multi-hop (8 vs 5),
which is where stage 15 item 1's resolver can still learn. Cognee has no
notion of "now" (0/7) and returned facts it should not (4/8 negative).

Mem0 ingested all 150 episodes (2.5 calls and $0.0018 an episode) and then failed every question: mem0ai 2.x refuses `search(user_id=...)` and wants `filters={"user_id": ...}`. Fixed (both shapes supported); not rerun, since another $0.27 would have put the day at the edge of the $2 cap.

**Recommendation:** keep native_graph. Turning `[memory] entities` on in
the live Sim is the step that makes it real; it is still the creator's
call (about 20 paid consolidation calls a night). Mem0's scored run is the next paid step.

**What it took to get numbers at all** (each fixed and committed):
- Together serves no embedding model per token to this account, although
  `/v1/models` lists `bge-base-en-v1.5`; the sidecars embed through
  Gemini's OpenAI-compatible endpoint (`gemini-embedding-001`, 768).
- Cognee sends `dimensions`, which LiteLLM refuses: `drop_params`.
- Cognee imports `s3fs` even for local files.
- An exception inside a library took the whole command down; now that
  system's cases are skipped with the reason.
- Gemini embeddings return no usage, and the meter charged each one a
  chat-call estimate: about $0.34 of phantom spend stopped Cognee at
  episode 112 and Graphiti before its negative questions. Now an
  embedding without usage is charged chars/4 of its input.

## 3. Where a chat turn's tokens go (stage 17 item 1, the gate)

Six toolchain scenarios on GLM-Flash with the new split recorded (the live
Sim has not run the split code yet):

| lane | calls | avg input | tools | prefix | window | question |
|---|---|---|---|---|---|---|
| chat | 14 | 9,793 | **50%** | 49% | 1% | 0% |
| task | 10 | 2,922 | 9% | 28% | 4% | 59% |

**The gate is open**: tool schemas are 50% of uncached chat input (the
threshold was 20%). And nothing is cached:

- The live ledger's last 30 days: 1,337 chat calls, 11.7M input tokens,
  **0% cached** (Gemini 0 of 3.5M too).
- A direct probe, the same 7.5k-token prompt twice: GLM-5.3-**Flash**
  cached 0 both times; GLM-5.3 cached 7,168 of 7,460 the second time.

So on the chat model the "routing breaks the prompt cache" worry of the
stage 17 plan does not apply -- there is no cache to break -- and a
routed tool block is a straight saving. The router was built in wave A,
off by default; the next step is `tool_routing = "shadow"` in the live
Sim for a week and `python -m simorgh.telemetry routing` for the miss
rate.

## Bugs found on the way (fixed)

- A paid house run's cap was written as `[cognition] max_spend_usd`, a key
  nothing reads; `house --paid` and the house bench were held only by each
  provider's shipped $2 day budget, not the $0.50 the code names. The
  bench's `tool_dialect` override also zeroed the provider's prices.

# Findings, 2026-09-14 and 2026-09-15

Benchmarks, long-run architecture, model tiers, local fallback, Agent Skills and parallel lookups. Every claim below was measured or observed in these two days; open questions are marked as such.

Related documents:
- `docs/benchmark-analysis-2026-09-14.md` (analysis, Gemini reviews, comparison arm table)
- `docs/plans/long-run-context-design.md` (changes A-H and the project plan)
- `docs/plans/agent-skills-design.md` (skills design, trust tiers, build plan)

---

## 1. Benchmark harness

**Setup.** `tools/bench_instance.py` runs one isolated copy of Sim (repo clone, own data dir, autonomy off, provider order `together,floor`) and asks it for benchmark runs over the bus. Results append to `~/.simorgh/benchmark-waves/<wave>/results.jsonl`. Comparison arms use `--arm`, `--orch key=value` (repeatable) and `--max-runs` (29079e4).

**Bugs found running 10 copies for 6 hours, and their fixes.**

| Finding | Effect | Fix |
|---|---|---|
| A case answered by the offline floor (Together connection dropped, 30 s cooldown) was scored as the model's wrong answer | Scores understated; 53 floor cases in wave w20260914b | `task.completed` carries `floor`; runner skips the case (3b6dc01); driver backs off (8a4858f) |
| A reply cut at `max_tokens` (reasoning-only) was treated as an outage and cooled the provider down | Healthy provider benched, more floor answers | Retry once with twice the tokens, no cooldown (517fa26) |
| Copies ran reflection's self-improvement tasks, each landing running `pytest -n auto` at 2-5 GB | Claude Code killed all copies twice for low memory | Reflection and distillation off in copies (474a98c) |
| A restarted copy resumed tasks from its old data dir | Stale work competing with the benchmark | Data dir wiped at start (bb4e036) |
| One Together HTTP 503 (twice, so the quick retry failed too) put a copy on the floor, and the runner fed it the rest of the run: 21 of 26 GAIA cases skipped in 2 s (arm 25, 04:08, 2026-09-15). The driver then counted that run toward `--max-runs`, so the slice would never have re-run | A whole slice lost to a 30-second outage | Runner re-runs a floored case up to `floor_retries` (3) times after a doubling wait from `floor_retry_wait_s` (60 s); a floor-answered run no longer counts toward `--max-runs` (5123f74) |
| `observer_kit.fast_copy_repo` fell back to `shutil.copytree` under load and copied `workspace/` (~6 GB per copy) | Disk fell from 53 GB to 3.6 GB | Driver clones code only, refuses a copy over 1 GB, stops under 20 GB free (ad2563b) |

**Memory: Docker keeps what SWE-bench used.** After arms 21-23's SWE-bench slices, Docker Desktop's Linux VM held ~29 GB of the Mac's memory (11 GB resident, 18 GB compressed) while its only running container used 110 MB; the VM never returns page cache to macOS. With that held, one benchmark copy was enough for Claude Code to kill arm 25 for low memory (2026-09-15, ~05:00). A Docker Desktop restart released it (free memory 50% -> 79%, compressor 26 GB -> 2 GB). `osascript quit` left Docker stuck in "stopping"; `docker desktop stop --force` then `docker desktop start` worked. `moda-db-1` (the creator's, restart policy `no`) must be started again by hand. **Before a wave with SWE-bench, and after it, check `top -o mem -stats pid,command,mem,cmprs` for the Virtualization process.**

**Measurement lessons.**
- Use `footprint -p` or the compressor total from `vm_stat` for memory; `ps` RSS hid about 10 GB of compressed memory.
- zsh does not word-split an unquoted `$VAR`; option strings passed that way arrive as one argument. Launch arm chains with `bash -c`.
- SWE-bench images are about 2.9 GB each; watch free disk during any wave.
- A driver that waits on a log line can match a stale line from an earlier run; mark relaunches in the log and wait on the new marker.

**Planning dropped completions with long answers.** A completion passes the answer as the status note; a 14,359-character GAIA answer exceeded the Ledger's 4,096-character inline limit, the append raised inside the Bus handler, and the task was never marked `completed` in Planning (the benchmark still scored it from the bus event). The note now goes through `_inline_or_blob`, like a long description: a preview naming the cut plus `note_ref` (e71d996).

**Still open.** Copies hung once after a floor backoff (16:55, 2026-09-14), root cause not confirmed. The SWE-bench scorer skips cases whose named tests are missing from the log.

---

## 2. What the 2026-09-14 wave showed

- **The answer reviewer was not a net gain on benchmarks.** It rejected 111 correct and 111 wrong answers, and for research profiles it cannot revise (`max_revisions=0`), so a rejection only discards. GAIA and BFCL rejected answers are still scored. Fixed by `[orchestration] review_benchmark` (b7aa40e); arms run with it off.
- **The reviewer only revises patch tasks** (87a5655); the analysis doc was corrected where it said otherwise.
- **Leading failure: "step budget exhausted"**, not wrong reasoning. That shaped the long-run work below.
- Sim calls GLM-5.3-Flash with `reasoning_effort: "low"` on every call (34f1791); a higher effort is untested.

---

## 3. Long-run changes and the comparison arms

Design: `docs/plans/long-run-context-design.md`. Every change ships behind a switch, off until its arm wins.

| Change | Switch | Commit | Status |
|---|---|---|---|
| A. Progress note, re-grounding every N steps | `reground_every_steps`, `keep_recent_steps` | 64033a2 | built; no gain measured |
| B. Clean retries/revisions from the note | `clean_revisions` | d4d29d4 | built; no gain measured |
| C. `delegate`: helper task with fresh context, report-only return | `delegation`, `delegate_max_steps` | 6864b18 | built; not yet in an arm |
| D. Test-first patch loop | - | - | not built |
| E. Model tiers and escalation | `escalate_from_attempt`, `[cognition] routes` | 0cf575b | partial |
| F. Plan-first | - | - | not built |
| G. Model scout for Together | - | - | designed, not built |
| H. Read-only lookups in one reply run together | `parallel_read_tools` | faf953f | built; arm 25 within noise, off |

**Arms, wave w20260915-arms** (GLM-5.3-Flash, review off; skipped = floor-answered, not scored):

| Arm | GAIA L3 | GAIA L2 | SWE-bench Verified |
|---|---|---|---|
| 21/24 baseline | 7/26 | 11/24 | 2/15 |
| 22 reground every 6 | 7/26 | 13/23 (1 skipped) | 2/12 (3 skipped) |
| 23 reground + clean | 8/26 | 9/20 (4 skipped) | 4/13 (2 skipped) |
| 25 parallel reads (4) | 9/25 (1 skipped); outage run 3/21 | 13/24 | 3/13 (2 skipped) |

**Conclusions.**
- No arm beats the baseline by more than two cases on any slice: within run-to-run noise. Keep A and B off.
- Re-grounding fires as designed (94 notes in arm 22, 79 in arm 23, no `context_too_large`), but writing a note every six steps spends steps: "step budget exhausted" was roughly twice as frequent in arm 22. If retried, use every 10 steps and keep 4.
- Arm 25 (change H) halved "step budget exhausted" on L3 (4 -> 2) and scored within noise of the others. Its two L3 runs with identical settings gave 3/21 and 9/25, a swing larger than any gap between arms: **slices of 13-26 cases cannot rank these switches.** The next measurement should repeat each arm 3 times or use the full GAIA validation set, before any switch becomes a default.
- Next candidates: a gentler re-grounding, a higher reasoning effort, and repeated runs of the baseline to size the noise.

---

## 4. Parallel read-only lookups (change H)

**Why.** One tool per model call made three independent searches cost three calls and three steps of budget.

**How it works** (faf953f):
- The parser keeps every marker in a reply (`cognition/parser.py::further_calls`); `tool_calls[0]` is unchanged.
- With `parallel_read_tools = N > 1`, the think request carries `parallel_tools` and `max_parallel_tools`, and Cognition tells the model independent lookups may share one reply.
- The session runs the first call plus the read-only calls straight after it, up to N, concurrently. Each is proposed to Guardian and recorded as its own step; the model gets one numbered result block; the batch costs one step.
- Anything that can change something, and `delegate`, still runs alone, and the model is told what did not run.

**Finding: GLM-5.3-Flash does batch when told it may.** Within the first GAIA cases of arm 25, the copy's ledger showed batches of 3 and 4 lookups.

**Finding: concurrent keyless searches were refused.** In arm 25's first launch DuckDuckGo refused 12 of 26 searches, against 5-21% in the other arms. Two bugs in `execution/websearch.py` (fixed in 2aeb871):
1. `_space_out` read `_last_call` without a lock, so concurrent searches all saw the same time, none waited, and all went out at once. Each caller now reserves the next slot under a lock.
2. After a refusal, `_last_call = 0.0` was meant to force a wait but reads as "never searched", so the retry went out immediately. It now waits two gaps.

That launch was stopped and discarded (no result row written) and the arm relaunched with the fix. The relaunch lost its GAIA L3 run to a Together 503 (run 7f5d624a109a, marked invalid in the wave's `NOTES`); arm 25 was relaunched again after the floor-retry fix (5123f74).

**Consequence.** With the keyless engine, batched searches still go out 2 s apart: the saving is model calls and step budget, not wall time. Batched file reads and fetches do run concurrently. A search API key (Brave, Tavily, Serper) would remove the spacing.

---

## 5. Models: Together tiers and local fallback

**Together serverless probe (2026-09-15).** Callable per token:

| Model | Input $/M | Output $/M |
|---|---|---|
| GLM-5.3-Flash | 0.15 | 0.50 |
| GLM-5.3 | 1.40 | 4.40 |
| DeepSeek-V4-Flash | 0.14 | 0.28 |
| DeepSeek-V4-Pro | 1.32 | 3.96 |
| gpt-oss-20b | callable | |
| Ternary-Bonsai-27B | free | |

- Qwen3.8-Flash and Qwen3.7-Max are streaming-only (Sim's provider does not stream).
- Most "free" catalogue entries need a dedicated endpoint, not serverless.
- `/v1/models` returned 403 through urllib; use `api.together.ai` with a User-Agent header.

**Built.** Per-purpose routes, named extra Together instances and strong-tier escalation (0cf575b); a quick transient failure (429/5xx, timeout, connection reset) retried once before cooldown (fb1ec4b).

**Ollama as last resort** (4dc8405), before the floor, `chat` purpose only:
- `qwen3:4b` leaks its reasoning even with `think:false`; do not use it.
- `qwen3:4b-instruct` answers directly in 0.6-1.8 s, about 3.9 GB of GPU memory at `num_ctx 8192`, `keep_alive 2m`.
- Enabled in `~/.simorgh/simorgh.toml`; takes effect on `restart`.
- Its 8,192-token context is a hard ceiling: anything that grows every prompt (a large skills catalog) breaks this fallback first.

---

## 6. Agent Skills

Design: `docs/plans/agent-skills-design.md` (6b7da66, a058536). Step 1 built: `simorgh/contracts/skills.py` parses and discovers `SKILL.md` folders, reports invalid ones with a reason, renders a capped per-profile catalog (ee89c39). Nothing reads it yet.

**Decisions (agreed with the creator, 2026-09-15).**
- **Trust belongs to the GitHub organisation that maintains a repo**, never to a marketplace that lists it.
- **Trusted orgs:** `anthropics`, `google`, `microsoft`, `huggingface`, `trailofbits`. Their skills install pinned to a commit with no approval step; the deterministic review still runs and holds back anything flagged. A new commit is taken only by an explicit `skills update`.
- **Any other repo:** reviewed, hash-pinned, enabled only after approval.
- **Marketplaces and lists** (SkillsMP ~1.9M scraped skills, ClawHub, "awesome" lists): discovery only.
- **Every source:** licence checked at install; fit with Sim's tools checked; enabled only if Sim will use it.
- **Default:** skills on once the catalog lands, confirmed by a benchmark arm; flip back if the catalog costs score.

**Built 2026-09-15.** Step 1 (parser, ee89c39), step 2 (catalog in `task_rules` + `use_skill`, ebbae74) and step 3 (`skills/` readable, never writable; scripts only through `run_script`, 7e5a94f). Off by default behind `[orchestration] skills_enabled` -- and the settings are there, not in a `[skills]` section, because no subsystem may import another and Orchestration is what renders the catalog.

**Source notes.**
- `anthropics/skills`: example skills Apache-2.0 (may be bundled); `docx`/`pdf`/`pptx`/`xlsx` source-available (install locally, never commit). Written for Claude's tools.
- `google/skills`: Gmail, Drive, Docs, Sheets, Calendar, YouTube, Gemini API; Apache-2.0. Most relevant to a home assistant.
- `trailofbits/skills` (security review), `microsoft/playwright-cli`, `huggingface/skills`: relevant.
- Vercel, Cloudflare, Stripe, Supabase, Neon, PlanetScale, Redis, HashiCorp: trusted but product-specific.
- `openai/skills` is deprecated in favour of OpenAI's plugins repository.

**Cost of preinstalling everything.** Disk is negligible. The cost is the catalog in every prompt:
- ~50 skills ≈ 3,000 tokens per call ≈ 60,000 tokens for a 20-step task.
- 150+ skills ≈ 9,000 tokens per call, larger than the Ollama fallback's whole context.
- A long, overlapping menu makes a weaker model pick the wrong skill.

So install freely, but list only enabled, relevant skills, or look skills up with a search tool instead of a full list.

---

## 7. Voice, TV and home fixes (2026-09-14)

- Speech-to-text auto order picks the whisper.cpp server first (af51564). Whisper transcripts with no letters are dropped (9e2bb12); looped sentences and phrases are heard once (535d8e6, 29034c7).
- An empty spoken reply is silence (58f48fc); a half-heard aside is not asked back (4b35681); courtesy words not addressed to Sim are not a turn (cd96667); in doubt, Sim stays quiet (509247a); a voice Sim cannot place may not start work without saying Sim's name (d521b21); "Sima" counts as Sim's name (da8e011).
- `tv pair again` (c7ad9fc); `tv show` brings the dashboard back in front of another app (111ba2b); saying the dashboard is on the TV requires `cast_show` to have run (15e2858).
- Siren takes `on` and answers `off` (7390468); a lone `?` opens help (31ea0c6); a Ring camera asked for by name on the NVR says where to find it (e822cbc).
- "Hey Sim" came back from whisper as "A-seam." and Sim replied QUIET, then heard "Why are you not responding?" (2026-09-15). "seam" now names Sim, and the voice rules list the usual mishearings and say a turn that is only the name is a call: answer in a word or two (4d9d148). "AC" was left out on purpose (air conditioner).
**Voice, afternoon of 2026-09-15 (live, the creator's house).** Watching a real evening produced eight cases where Sim answered words that were not for it, and five fixes:

| What happened | Fix |
|---|---|
| "Hey Sim" heard as "A-seam.", Sim stayed QUIET, then "Why are you not responding?" | `seam` (later `seym`, `syme`) names Sim; the voice rules list the mishearings and say a bare name is a call (4d9d148, 2f8d645) |
| Mid-conversation "But, I mean..." got QUIET, then "Sim, I was talking to you." | A trailing fragment from the person Sim is already talking with is a pause: "Go on", never QUIET (565cc32) |
| Ira to Bobby, "it isn't fair that you get pizza for lunch," QUIET; whisper sent the rest as its own turn and Sim answered it | A known voice within `[voice] continuation_quiet_s` (12 s) of a quiet turn, not naming Sim, is the rest of that aside and is not asked (3cca60f) |
| "We are on the queue." from an unplaced voice became `dash_view` on the TV, refused only because the invented view did not exist | `unplaced_voice_refusal` now refuses every non-read-only tool, not just `start_task` and irreversible ones (0926c8b) |
| A voice Sim could not place was asked its name, whisper heard "Myself", and a person called Myself was enrolled -- then matched the creator'"'"'s own voice | reflexive pronouns join the words that are not names (ec8338a); `voice forget <name>` clears one already made |
| The name rule met an empty voice book (the creator deleted his own profile while clearing that entry) and would have silenced the house | with nobody enrolled the rule does not apply (d367650) |
| "[sd:0.55, sv:0.45] Sah-EED." -- GLM invented a metadata tag where a feeling belongs, and kokoro read the scores aloud | a head tag carrying digits or colons is dropped like any other bracket (3c5cd79) |
| A known voice never improved its match score: refinement was on, but a take taught Sim only at +0.20 above the threshold (0.70) while the creator's own voice scored 0.55 in his room -- so the voices that most needed practice never gave any | the bar is +0.05 (`[voice] speaker_refine_above`); clear-of-everyone-else (0.15), not-a-"probably", and 0.8s of speech are unchanged (df368fe) |
| `voice enroll saeed` wrote a lowercase person the household table spells "Saeed" | enrolment takes the household's spelling (df368fe) |
| Told his name's pronunciation, Sim said "I've noted it" and wrote nothing -- `voice pronounce` stores it, and no tool the model had could reach it; the spelling he then saw was built into `contracts/household.py` | a reply claiming to have noted a pronunciation with no tool run is rejected, and the correction names the command; `sim_command` (55baa4f) is the way the model can now run it (df368fe) |
| "- I'm sorry." said to someone on a call got "No need to apologize" spoken into it | `i'm`, `im`, `my`, `bad` added to the courtesy list; a turn is an aside only when every word is filler (098f5a8) |

**Sim could not press its own buttons (fixed, 55baa4f).** `restart`, `tv show`, `tasks`, `voice off` existed only as typed lines: asked out loud, Sim described the command and could not run it, and the creator asked for it twice ("it should be able to restart itself or any other cli command I ask it to run"). Now:
- **"Restart" said aloud** is a spoken command beside stop/off/mute (`voice/commands.py`): no model in the path, only for a voice the house knows -- an advert saying it must not take Sim down, the same reason as `unplaced_voice_refusal` -- and refused aloud when the process was not started by `simloader.py`, since nothing would bring Sim back and the person is not at a keyboard.
- **`sim_command`** (Execution) asks Interface to carry out the line exactly as typed (`ui.command.request` -> `parse` + `dispatch`), printed in the room so everyone sees what ran. Irreversible, so Guardian gates every call and an unplaced voice cannot use it; `!` is refused -- shell stays with `run_shell` and its own policy.

This is the [[unconnected-wires]] shape again: `system.restart`, the Kernel handler and the loader hand-off all existed; only the path from Sim to them was missing. Sim itself queued a 40-step task to build the same thing when asked, which the creator cleared.

**Open: the model ignores its own quiet rules.** Six of the eight misfires were fresh remarks or questions from a voice Sim could not place -- "Who did that?", a parent's "try harder, honey", "What is this game?", "You're in my heart.", and two fragments of the creator's call with a colleague, answered aloud into the call. The scaffold already forbids each one. Rewording it has been tried repeatedly (509247a, 4b35681, cd96667). The candidate fix is deterministic and awaits the creator's call: **an unplaced voice gets no reply at all unless it names Sim or answers something Sim just asked** -- it would have prevented all six, at the cost of guests having to say "Sim". A cheap second model call to judge "is this for me?" is the alternative.

- **Still open:** barge-in "stop" does not interrupt speech; the `voice barge aec off` test is waiting on the creator.

---

## 8. Environment notes

- The listings tool's import prints NumPy tracebacks: `pyarrow` 14.0.2, `numexpr` 2.8.7 and `bottleneck` 1.3.7 in the Anaconda base were built for NumPy 1.x, and NumPy is 2.5.3. The import succeeds; it is noise. Upgrading those three packages would silence it (not done).
- Ten `voiceday` observer copies (5.9 GB each) were found on disk during the wave; not created by the benchmark work and not deleted.

---

## 9. Open list

1. Size the benchmark's run-to-run noise (repeat the baseline 3 times on the same slices) before judging any switch. Arm 25 is done; run 7f5d624a109a stays excluded.
2. Re-run the floor-skipped GAIA L2 cases (1 in arm 22, 4 in arm 23).
3. A gentler re-grounding arm (every 10, keep 4) and a higher reasoning-effort arm.
4. Skills step 4 on: `skills list/show/install` with the review and trust tiers, the bundled default set, distillation'"'"'s own skills, and the benchmark arm before the catalog is on by default.
5. Long-run changes D, E remainder, F, G.
6. The post-backoff hang in the benchmark driver; SWE-bench scorer skips; Docker VM memory after SWE-bench slices (check and restart between waves).
7. Barge-in "stop"; `restart` the live Sim to load the fixes and the Ollama fallback.

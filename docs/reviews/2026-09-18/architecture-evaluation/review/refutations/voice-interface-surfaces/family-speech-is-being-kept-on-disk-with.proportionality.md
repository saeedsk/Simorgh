# refute:proportionality:Family speech is being kept on disk with

*Workflow: review · Phase: Refute · Agent id: `aad1f7d3e89da901a` · Tool calls: 3*

## Task given to the agent

```text
You are reviewing the ARCHITECTURE of Simorgh, a self-improving personal AI agent written in Python (stdlib-first) at /Users/saeed/ws/Simorgh. The creator built it from scratch: ~87k lines in simorgh/, 18 subsystems (one package each) composed by a Kernel, talking only via typed messages on an async Bus, all state in an append-only Ledger of events, a Guardian that is the sole approver of every effect (HMAC token re-verified by Execution), worktree-isolated self-patching, a bootloader (simloader.py) that gates the checkout with the unit suite and rolls back. It chats (CLI/TUI/HTTP/Telegram/WhatsApp), talks (voice pipeline), controls the house (Home Assistant, Reolink cameras, Ring, Cast/Android TV), and runs benchmarks (GAIA/BFCL/SWE-bench).
  
  The creator asked: "review its architecture, evaluate it, tell me where I went wrong and how to improve it."
  
  Ground rules for you:
  - Read the CODE, not the docs, to establish what is true today. docs/EVOLUTION.md (5,254 lines) is a HISTORY; a bug it describes has very likely been fixed since. Do not report a historical finding as current state.
  - Previous reviews already exist and you must NOT simply repeat them. Already known (do not re-report unless you have something materially new to add): cameras use local ffmpeg/HLS instead of Home Assistant; self_patch.draft tool is named in learning/pipeline.py but not registered; Self Model capabilities["tools"] is never populated; no in-prompt sliding dialogue buffer for chat turns (orchestration/context.py); Ledger default backend is JSONL and ~1.4 GB; CHAT profile binds 34 tools; STT latency degrades under self-inflicted load; "unconnected wire" (designed slot, one side implemented, nobody writes it) is the project's dominant bug shape; test coverage thin in persona/learning/worldmodel; sim.sh auto-approve flips one boolean. Read docs/architecture-review-2026-09-18.html and docs/architecture-audit-2026.md quickly if you want the full list.
  - Useful orientation docs (read briefly, then go to code): docs/module-map.md, docs/architecture.md, docs/blueprint/02-system-architecture.md, docs/blueprint/03-contracts-and-messaging.md.
  - Every finding MUST cite file:line evidence you actually read, and where feasible a command whose output you quote. If a claim depends on runtime behaviour, try to establish it by a cheap command (python -c import + inspect, grep, wc, reading ~/.simorgh/simorgh.toml, listing ~/.simorgh/ledger). Do NOT boot the full system, do NOT run the full test suite, do NOT run anything that calls a paid model, do NOT modify any file in the repo.
  - Think like a senior systems architect. Distinguish (a) a design decision that is wrong or over-built for this system's real scale (one laptop, one family), (b) a design that is right but the implementation undermines it, (c) a genuine bug. Say which.
  - Your final text is data for an orchestrator, not a message to a human. Return only the structured output.
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "voice-interface-surfaces". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "Family speech is being kept on disk with no retention policy",
    "kind": "missing",
    "severity": "low",
    "claim": "The live config flips `keep_audio` on (code default is off) and every recognised turn's WAV plus transcript JSON is written to workspace/voice/audio with no pruning; only the overheard transcript store purges itself.",
    "evidence": [
      "~/.simorgh/simorgh.toml `[voice] keep_audio = true`; simorgh/voice/config.py:313 `keep_audio: bool = False`",
      "`du -sh workspace/voice/audio` -> 68M; `ls workspace/voice/audio | wc -l` -> 842",
      "session.py:762-792 `_keep_turn` writes `<stamp>-<turn>.wav` and `.json` (text, confidence, speaker scores); no reader of `audio_dir` prunes (grep: only session.py:780 and pipeline.py:589 write)",
      "contracts/overheard.py:29 'Kept 48 hours by default and purged on every write' (transcripts only)"
    ],
    "why_it_matters": "It was switched on for calibration (the docstring says so) and is now a permanent, growing archive of children's voices in a gitignored folder on a laptop; the privacy default in the design doc ('audio is not kept unless keep_audio') is technically honoured but practically inverted.",
    "recommendation": "Give `_keep_turn` the same 48 h purge the overheard store has (or a `keep_audio_max_files`), and have `voice status` say how many turns are on disk so the flag is not forgotten.",
    "confidence": 0.65
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Check keep_audio config, audio dir size, and writers/pruners | 3:keep_audio = true 313: keep_audio: bool = False --- 68M workspace/voice/audio 842 1789696040926-1.json 1789696040926-1.wav 1789696045965-2.json 1789776567973- |
| 2 | Bash | Read the write paths, purge code, gitignore, and date range of kept audio |  if clock is not None: clock.final_at = self._now() clock.text = event.text clock.confidence = event.confidence clock.engine_stt = event.engine clock.language = |
| 3 | Bash | Check toml context, transcript purge, status surface, and when _keep_turn landed | [voice] barge_in = false keep_audio = true vad_sensitivity = "high" barge_in_calibrate_ms = 1200 barge_in_speech_ms = 350 barge_in_ratio = 2.8 min_confidence =  |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every factual element of the claim checks out against the code and the live machine. ~/.simorgh/simorgh.toml line 3 sets `keep_audio = true` (alongside barge-in calibration knobs, consistent with it having been flipped for calibration); simorgh/voice/config.py:313 has the code default `keep_audio: bool = False`. session.py:629-636 calls `_keep_turn` on every final transcript when the flag is on; `_keep_turn` (session.py:762-792) writes `<ms>-<turn>.wav` via `write_wav` and a sibling `.json` carrying text, confidence, engine, language, seconds and the speaker scores. pipeline.py:301/589 is the second writer. A grep of simorgh/voice/ for purge/unlink/rmtree/max_files/retention finds no reader of `audio_dir` that deletes anything; the only unlink calls are enrolment files, temp files and TTS scratch. The overheard transcript store (contracts/overheard.py:49, :136-157) has MAX_AGE_S = 48h and purges on every write, and config.py:329-331 documents that as the creator's explicit "one day, two days ... then purge" wish, so the disparity between transcripts (expiring) and audio (never expiring) is real and is inside the same subsystem. Runtime: workspace/voice/audio holds 842 files (421 WAVs) totalling 68M, all written between 2026-09-17 18:47 and 2026-09-18 17:09, i.e. one day since `_keep_turn` landed in commit 8273d51 (2026-09-17). That is roughly 70 MB/day of family speech with no ceiling. The folder is gitignored (.gitignore:39 `workspace/*`), so it stays on the laptop only. Nothing in voice/settings.py or service.py surfaces the count on disk; settings.py:93 only lists the flag under "Keeping and telling". On the skeptic's lens: at one-laptop scale the disk cost is trivial (70 MB/day, ~25 GB/year), so this is not an architectural problem and severity "low" is correct. But the recommendation is proportionate, not disproportionate: the project already owns a 48h purge for the same kind of data (overheard.py), and the creator's stated wish for that data ("should expire without anyone having to remember to delete it") applies with more force to raw audio of the household than to transcripts. Adding a max-age sweep in `_keep_turn` (or reusing the overheard purge shape) is a few lines. Classification: (b) a right design (off-by-default, documented as debug-only at speakers.py:411) that the live config plus a missing expiry practically inverts. Not a bug in the code-does-what-it-says sense; a missing wire between a stated retention policy and one of the two stores it should cover.

### evidence

- ~/.simorgh/simorgh.toml:3 `keep_audio = true` (under [voice], beside barge_in_calibrate_ms/barge_in_ratio calibration knobs)
- simorgh/voice/config.py:313-314 `keep_audio: bool = False` / `audio_dir: str = "workspace/voice/audio"`
- simorgh/voice/session.py:629-636 gate `if self._config.keep_audio and event.audio: self._keep_turn(turn_id, event)` on every final transcript
- simorgh/voice/session.py:762-792 `_keep_turn` writes `<ms>-<turn>.wav` and `.json` {at, turn, text, confidence, engine, language, seconds, speaker scores}; docstring says it exists for confidence-threshold calibration
- simorgh/voice/pipeline.py:301,589 second writer `_keep` -> `<epoch>.wav`
- `grep -rn 'purge|unlink|rmtree|max_files|retention' simorgh/voice/` -> no deletion touches audio_dir (only speakers.py:311 enrolment, audio.py:266/tts/stt temp files)
- simorgh/contracts/overheard.py:29,49,136-157 MAX_AGE_S = 48*3600, `_purge_locked` on every write; config.py:329-331 records the creator asked for 'one day, two days ... then purge'
- `du -sh workspace/voice/audio` -> 68M; `ls | wc -l` -> 842 (421 .wav); earliest stamp 2026-09-17 18:47:20, latest 2026-09-18 17:09:27
- git log -S'_keep_turn' -> 8273d51 2026-09-17 18:06 (one day of accumulation = 68M)
- .gitignore:39 `workspace/*` (folder never committed)
- simorgh/voice/settings.py:93 lists keep_audio under 'Keeping and telling'; no status surface reports files on disk
- simorgh/voice/speakers.py:411 'that flag is for debugging ordinary talk'

**severity adjustment:** keep

**corrected claim:** The live config sets `keep_audio = true` (code default False, described in-code as a debugging flag for calibrating confidence thresholds). Every recognised turn's WAV plus a transcript/speaker-score JSON is written to workspace/voice/audio by session.py `_keep_turn` (and pipeline.py `_keep`), and nothing in the voice package ever deletes from that folder; the sibling overheard transcript store expires at 48 h on every write per the creator's stated wish. One day after the writer landed the folder holds 421 turns / 68 MB, growing ~70 MB per day of use. Disk impact is negligible at one-laptop scale; the gap is that a stated retention policy covers transcripts but not the raw audio of the same conversations.


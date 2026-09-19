# refute:correctness:Family speech is being kept on disk with

*Workflow: review · Phase: Refute · Agent id: `a854a1199f736ec6a` · Tool calls: 4*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "voice-interface-surfaces". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Check keep_audio config, audio_dir users, and on-disk audio folder | 3:keep_audio = true ---config.py 313: keep_audio: bool = False 314: audio_dir: str = "workspace/voice/audio" ---writers/readers of audio_dir (eval):1: no matche |
| 2 | Bash | Read keep-turn writer, pruning code, overheard purge, config docstring, and status surfaces | ---audio_dir refs simorgh/voice/session.py:780: folder = Path(self._config.audio_dir) simorgh/voice/pipeline.py:589: path = self._repo_root / self._config.audio |
| 3 | Bash | Check gating of the writer, design doc wording, overheard purge, known-findings overlap, kept speakers and file ages | ---callers of _keep_turn/_keep simorgh/contracts/settings.py:134: "keep_audio": (bool, None, "keep raw recordings under workspace/voice/audio (off by default)") |
| 4 | Bash | Read the keep gate comment, README privacy text, kept JSON keys, and the status surface | ---session 622-640 clock.text = event.text clock.confidence = event.confidence clock.engine_stt = event.engine clock.language = event.language or "" if event.wo |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every load-bearing part of the claim checks out against the code and the live machine today. `~/.simorgh/simorgh.toml` line 3 sets `keep_audio = true` while `simorgh/voice/config.py:313` defaults it to False. `simorgh/voice/session.py:629-636` calls `_keep_turn` for every recognised turn when the flag is on, and `_keep_turn` (session.py:762-792) writes `<ms>-<turn>.wav` plus a `.json` beside it into `config.audio_dir`. A repo-wide grep for `audio_dir` finds exactly two users, both writers (session.py:780, pipeline.py:589); a grep of simorgh/voice/ for unlink/rmtree/purge/prune/max_files/retention finds nothing touching that folder (the hits are speaker-book files, TTS temp files and whisper temp files). The only time-based purge in the voice area is the overheard transcript store, `simorgh/contracts/overheard.py:49` `MAX_AGE_S = 48 * 3600.0` and `_purge_locked` at :136, which is called on every write (:114) and covers transcripts only. On disk: 68M, 842 files = 421 wav/json pairs. The finding is not in the known-findings list (no mention of keep_audio, voice/audio or retention in the audit/review docs beyond an unrelated Ledger sentence). Small corrections: (1) the kept JSON does not in practice carry speaker scores, all 421 files have only at/turn/text/confidence/engine/seconds, and the `speaker` field is empty in every one, so the "children's voices" framing is inference, not something the archive itself attributes; (2) the archive is one day old (oldest file 1.0 days, newest 0.09 days), so it is a growing archive with no bound rather than a long-standing one; (3) `keep_audio` is exposed through `voice set` (simorgh/voice/settings.py:93 "Keeping and telling"), so it is not hidden, though nothing reports how many turns are on disk. One extra point in the reader's favour: `simorgh/voice/README.md:127-129` still says "Raw microphone audio is not kept (`keep_audio` is off; the streaming path never writes it)", which session.py:629-636 explicitly contradicts, so the privacy doc is stale in both halves. Classification: a genuine (small) missing-mechanism gap, kind (b): the design's privacy default is right, the calibration switch simply has no expiry. Severity low is appropriate for one laptop, one family, 68 MB after a day, though it will grow at roughly that rate whenever voice is on.

### evidence

- ~/.simorgh/simorgh.toml:3 `keep_audio = true`; simorgh/voice/config.py:313-314 `keep_audio: bool = False` / `audio_dir: str = "workspace/voice/audio"`
- simorgh/voice/session.py:629-636: `if self._config.keep_audio and event.audio:` ... `self._keep_turn(turn_id, event)` with the comment 'The streaming path kept none, so `keep_audio` was a switch that did nothing here'
- simorgh/voice/session.py:762-792 `_keep_turn` writes `folder / f"{stamp}.wav"` and `folder / f"{stamp}.json"`; docstring: 'for calibration'
- `grep -rn audio_dir simorgh/` (excluding config.py) -> only session.py:780 and pipeline.py:589, both writers; `grep -rn 'unlink|rmtree|purge|prune|max_files|retention' simorgh/voice/` -> no hit on the audio folder
- simorgh/contracts/overheard.py:29 'Kept 48 hours by default and purged on every write'; :49 `MAX_AGE_S = 48 * 3600.0`; :114 `_purge_locked(path, now=entry["at"])` -- transcripts only
- `du -sh workspace/voice/audio` -> 68M; `ls workspace/voice/audio | wc -l` -> 842 (421 wav + 421 json); oldest file 1.0 days, newest 0.09 days
- Kept JSON keys across all 421 files: Counter({'at','turn','text','confidence','engine','seconds'}) -- no speaker field populated, so no on-disk attribution to any person
- simorgh/voice/settings.py:93 `("Keeping and telling", ("diagnostics", "keep_audio", "keep_transcripts"))` -- the flag is exposed via `voice set`; no code reports the count of kept turns
- simorgh/voice/README.md:127-129 'Raw microphone audio is not kept (`keep_audio` is off; the streaming path never writes it)' -- stale against session.py:629-636 and the live toml
- Not in the known-findings list: `grep -in 'keep_audio|voice/audio|retention' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md` -> only an unrelated Ledger sentence

**severity adjustment:** keep

**corrected claim:** The live config flips `keep_audio` on (code default is off); with it on, session.py:629-636 files every recognised turn's WAV plus a transcript JSON (text, confidence, engine, seconds; speaker scores only when identification ran, which none of the 421 kept turns has) into workspace/voice/audio, and no code anywhere prunes that folder; the overheard transcript store is the only voice artefact with a 48 h purge. The archive is currently 68 MB / 421 turns from one day of use, and simorgh/voice/README.md:127-129 still states the streaming path never writes audio.


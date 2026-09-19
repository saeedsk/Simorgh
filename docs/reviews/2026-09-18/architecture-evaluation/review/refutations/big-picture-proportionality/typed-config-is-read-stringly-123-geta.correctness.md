# refute:correctness:Typed config is read stringly: 123 `geta

*Workflow: review · Phase: Refute · Agent id: `a17476e2eb695f96d` · Tool calls: 7*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "big-picture-proportionality". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "Typed config is read stringly: 123 `getattr(config, \"x\", default)` sites, 20 with a fallback that contradicts the dataclass default",
    "kind": "right-design-undermined",
    "severity": "medium",
    "claim": "Execution and Voice read their own typed Config dataclasses via getattr with a second, hand-typed default; in 20 sites that default is the opposite of the dataclass's, so behaviour silently flips whenever a test or tool passes a partial config, and the pattern is exactly what lets a 'designed slot nobody reads' hide from kernel/configcheck.py.",
    "evidence": [
      "grep -rnE 'getattr\\((self\\._config|self\\.config|config|cfg|self\\._cfg), *[\"\\']' simorgh --include='*.py' | wc -l -> 123 (execution 83, voice 37)",
      "audit script output: \"getattr reads matched to a dataclass field: 118; getattr default differs from the dataclass default: 20\"",
      "simorgh/execution/config.py:466 `tv_show_on_start: bool = False` vs simorgh/execution/service.py:530 `getattr(self._config, \"tv_show_on_start\", True)`",
      "simorgh/execution/config.py:193 `shell: bool = True` vs simorgh/execution/tools.py:3113 `getattr(config, \"shell\", False)`",
      "simorgh/voice/config.py:192 `conversation_window_s: float = 180.0` vs voice/session.py getattr fallback 0.0; `unplaced_follows_conversation` True vs False",
      "kernel/configcheck.py:55-80 KNOWN_DEAD_FIELDS is a hand-maintained list precisely because data-flow dead fields cannot be discovered from the parsed Config"
    ],
    "why_it_matters": "The dataclass Config was the right design: one typed source of truth per subsystem. getattr-with-default turns it into a stringly-typed dict with two defaults, which is how the project's dominant bug shape (a wire with one end) reproduces at the config level and how tests can pass against behaviour production never has.",
    "recommendation": "Add a boundary-style test that forbids `getattr(<config>, \"...\"` in simorgh/ (the 5 legitimate cases can be allow-listed), then replace the 123 sites with direct attribute reads. It is a mechanical afternoon and it retires a class of bug.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Count getattr-on-config sites per subsystem |  123 --- 1 cognition 83 execution 2 interface 37 voice |
| 2 | Bash | Read the cited config/getattr sites and configcheck |  # startup ... it should only do that if it wants to cast dashboard on # tv"). Set it true to have the dashboard waiting on a TV already on. tv_show_on_start: b |
| 3 | Bash | Audit getattr config fallbacks against dataclass defaults | DIFF simorgh/interface/service.py:493 time_marker_minutes: getattr default=0.0 dataclass default=15.0 DIFF simorgh/interface/service.py:1108 show_speaker_score: |
| 4 | Bash | Check factory defaults, unmatched fields, and whether tests pass partial configs | Exit code 2 58: repo_root: Path = field(default_factory=lambda: find_repo_root()) 398: security_posture_weights: dict = field(default_factory=lambda: { 417: hom |
| 5 | Bash | Check overheard_dir field, test partial-config usage, and existing config tests |  hours = 24.0 items = await asyncio.to_thread( store.recall, since_s=hours * 3600.0, speaker=speaker, kind=kind, folder=getattr(self._config, "overheard_dir", N |
| 6 | Bash | Identify which Config the overheard_dir read uses and the fallback dir | 2944: class OverheardTool: 2962: def __init__(self, config: Config) -> None: ---who-constructs 2944:class OverheardTool: 3015:class OverheardNoteTool: 3066: Ove |
| 7 | Bash | Confirm OverheardTool config type, DEFAULT_DIR value, and whether prior reviews mention getattr | 6: the queries and was imported by nobody. Both lived in Voice, and the 19: def __init__(self, config: Config) -> None: 23: from simorgh.contracts import overhe |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited file:line checks out verbatim against the code today, the site count reproduces exactly (123: execution 83, voice 37, interface 2, cognition 1), and my own audit against the real dataclass fields (importing simorgh.execution.config / voice.config / interface.config and comparing each getattr fallback with dataclasses.fields defaults) finds 22 mismatches — 11 hard scalar contradictions (bool/float/str flipped) plus 11 where the fallback stands in for a default_factory — so the claim's "20" is the right order of magnitude, not inflated. The finding is not in the known-findings list: the three prior review documents contain zero occurrences of "getattr". One caveat on mechanism: in production the Config dataclass is always fully populated, so the hand-typed fallbacks are dead code there; they fire only when a partial object is passed, which the test suite does do (tests/simorgh/voice/test_two_voices_in_one_turn.py:47 sets pipeline._config = SimpleNamespace(keep_transcripts=True)). However, the audit also surfaced a case the claim's mechanism predicts and which is a genuine current bug: simorgh/execution/tools.py:2988 and :3040 read getattr(self._config, "overheard_dir", None) off the EXECUTION Config, but that field exists only on the VOICE Config (voice/config.py:332); the writer side (voice/session.py:200) honours the setting while the execution recall tool always falls back to contracts/overheard.py DEFAULT_DIR — so a customised [voice] overheard_dir makes recall silently read the wrong folder. A direct attribute read would have raised AttributeError at first use. That is materially new evidence that the pattern hides real wires-with-one-end, so severity stays at medium.

### evidence

- grep -rnE 'getattr\((self\._config|self\.config|config|cfg|self\._cfg), *["\']' simorgh --include='*.py' | wc -l -> 123; per subsystem: execution 83, voice 37, interface 2, cognition 1
- own audit (import dataclasses, compare fallback to field default): matched 117, differ 22 (11 scalar contradictions incl. interface/service.py:493 time_marker_minutes 0.0 vs 15.0, interface/service.py:1108 show_speaker_score False vs True, voice/tts/lanes.py:119 tts_voice '' vs 'af_jessica', execution/media/tools.py:48 media_quiet_hours '' vs '22:00-07:00'; 11 default_factory fields such as repo_root read with '.'/None)
- simorgh/execution/config.py:466 `tv_show_on_start: bool = False`; simorgh/execution/service.py:530 `if not getattr(self._config, "tv_show_on_start", True):`
- simorgh/execution/config.py:193 `shell: bool = True`; simorgh/execution/tools.py:3113 `if getattr(config, "shell", False)`
- simorgh/voice/config.py:192 `conversation_window_s: float = 180.0` vs voice/session.py:1223 fallback 0.0; voice/config.py:186 `unplaced_follows_conversation: bool = True` vs voice/session.py:1313 fallback False
- simorgh/kernel/configcheck.py:66-80 KNOWN_DEAD_FIELDS is a hand-maintained dict with per-entry prose justification ('the section-equality probe cannot discover on its own -- it has to be told')
- NEW: simorgh/execution/tools.py:2988 and :3040 `getattr(self._config, "overheard_dir", None) or store.DEFAULT_DIR` where self._config is execution Config (tools.py:2962 `def __init__(self, config: Config)`, tools.py:64 `from .config import Config`); `overheard_dir` is defined only in simorgh/voice/config.py:332 and honoured by voice/session.py:200 — the execution read can never see the setting
- tests/simorgh/voice/test_two_voices_in_one_turn.py:47 and :64 `pipeline._config = types.SimpleNamespace(keep_transcripts=True)` — partial configs are passed in tests, so the fallbacks do fire there
- grep -ci getattr docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md -> 0, 0, 0 (not previously reported)

**severity adjustment:** keep

**corrected claim:** 123 getattr-with-default reads of typed Config dataclasses (execution 83, voice 37, interface 2, cognition 1); 22 carry a fallback that differs from the dataclass default (11 outright contradictions of a scalar default, 11 substitutes for a default_factory). In production the dataclass is fully populated so the fallbacks are dead, but tests do pass partial configs (SimpleNamespace) so they can pass against behaviour production never has, and the pattern already hides one real cross-subsystem bug: execution/tools.py:2988/3040 read `overheard_dir` from the execution Config where it does not exist (it lives on the voice Config), so the recall tool ignores a customised [voice] overheard_dir.


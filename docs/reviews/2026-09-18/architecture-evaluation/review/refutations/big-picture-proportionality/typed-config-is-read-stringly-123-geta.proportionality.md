# refute:proportionality:Typed config is read stringly: 123 `geta

*Workflow: review · Phase: Refute · Agent id: `a7e189976ab3b5ab4` · Tool calls: 5*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "big-picture-proportionality". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Count getattr-on-config sites per subsystem |  1 cognition 83 execution 2 interface 37 voice --- 123 |
| 2 | Bash | Read the cited config/getattr lines and configcheck |  # startup ... it should only do that if it wants to cast dashboard on # tv"). Set it true to have the dashboard waiting on a TV already on. tv_show_on_start: b |
| 3 | Bash | Reproduce the audit of getattr defaults vs dataclass defaults | UNMATCHED interface time_marker_minutes simorgh/interface/service.py 493 UNMATCHED interface show_speaker_score simorgh/interface/service.py 1108 UNMATCHED cogn |
| 4 | Bash | Check who passes partial configs and whether unmatched fields exist | == SimpleNamespace/Mock configs in tests (execution/voice) == 13 2 tests/simorgh/voice/test_two_voices_in_one_turn.py:47: pipeline._config = types.SimpleNamespa |
| 5 | Bash | Check None-config handling and the cross-subsystem getattr sites | 1: def __init__(self, *, config: Config \| None = None, extra_tools: list \| None = None, 3: self._config = config or Config() --- hours = 24.0 items = await asyn |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The pattern is real and the three headline examples verify exactly at the cited lines (tv_show_on_start False vs getattr True; shell True vs getattr False; conversation_window_s 180.0 vs 0.0 and unplaced_follows_conversation True vs False). But the finding overstates both the count and the consequence. (1) Count: re-running the audit against the actual dataclasses yields 9 scalar contradictions, not 20, and only 3 of them flip behaviour (the other 6 are '' string fallbacks that are immediately `or`-ed back to a real value). 113 of 123 sites match a field whose getattr default equals the dataclass default or has no default at all. (2) The fallback is unreachable in production: execution Service does `self._config = config or Config()` (service.py:112) and voice Session takes `config: Config` as a required kwarg (session.py:181), so `self._config` is always the complete dataclass and the second default is dead code, not live behaviour. (3) The claim that "tests pass against behaviour production never has" is not demonstrated: execution tests build real `Config(repo_root=..., shell=True)` objects and use `dataclasses.replace` for tv_show_on_start (test_service.py:581-584); the only SimpleNamespace partial configs in voice tests (test_two_voices_in_one_turn.py:47,64) set the exact field they read. No test was found that exercises a contradicting fallback. (4) The link to kernel/configcheck.py is rhetorical: KNOWN_DEAD_FIELDS lists fields that parse but nothing reads (data-flow dead); getattr-vs-attribute access does not change what configcheck can or cannot discover, and every one of the 118 dataclass-matched getattr names actually exists on its dataclass, so there is no "slot nobody defined" hiding behind getattr today. The 5 unmatched sites are cross-subsystem or sub-config reads (execution reading voice's overheard_dir, cognition reading a provider sub-config's only_purposes) where getattr is a reasonable choice. At this system's scale (one laptop, one developer) this is a code-hygiene inconsistency with three latent contradictions that cannot currently fire, not a design being undermined. The recommended fix (boundary test + mechanical replacement) is cheap and harmless, so it is not disproportionate, but it does not "retire a class of bug" that has ever manifested. Severity should drop from medium to low and the kind is closer to a hygiene nit than "right-design-undermined".

**corrected claim:** Execution and Voice read their typed Config dataclasses via getattr-with-default at 123 sites; in 3 of them (execution/service.py:530 tv_show_on_start, execution/tools.py:3113 shell, voice/session.py:1223/1313 conversation_window_s and unplaced_follows_conversation) the hand-typed default contradicts the dataclass default, and 6 more fall back to '' before being `or`-ed to a value. Because both subsystems always receive the full dataclass in production (`config or Config()` at service.py:112; required `config: Config` at session.py:181) and tests construct real Config objects, the contradicting defaults are dead code today; they are a hygiene inconsistency and a small trap for future partial-config tests, not a live behaviour flip, and they do not affect what kernel/configcheck.py can detect.

### evidence

- grep -rnE 'getattr\((self\._config|self\.config|config|cfg|self\._cfg), *["\']' simorgh --include='*.py' | wc -l -> 123 (cognition 1, execution 83, interface 2, voice 37)
- Audit script comparing getattr literal defaults against dataclasses.fields() of simorgh.execution.config.Config and simorgh.voice.config.Config: 'matched 113 differ 9 unmatched 5'; the 9: voice/session.py:1223 conversation_window_s 180.0 vs 0.0; voice/session.py:1313 unplaced_follows_conversation True vs False; voice/tts/lanes.py:119 tts_voice 'af_jessica' vs ''; voice/tts/miso.py:141,150 miso_repo/miso_tokenizer vs ''; voice/settings.py:139 tts 'auto' vs ''; execution/service.py:530 tv_show_on_start False vs True; execution/tools.py:3113 shell True vs False; execution/media/tools.py:48 media_quiet_hours '22:00-07:00' vs ''
- simorgh/execution/config.py:466 `tv_show_on_start: bool = False`; simorgh/execution/service.py:530 `if not getattr(self._config, "tv_show_on_start", True):` (verified)
- simorgh/execution/config.py:193 `shell: bool = True`; simorgh/execution/tools.py:3113 `*((RunShellTool(config),) if getattr(config, "shell", False) else ())` (verified)
- simorgh/execution/service.py:110-112 `def __init__(self, *, config: Config | None = None, ...)` / `self._config = config or Config()` -- production always holds the full dataclass
- simorgh/voice/session.py:181 `def __init__(self, *, pipeline: Pipeline, config: Config, ...)` -- config is a required full dataclass
- tests/simorgh/execution/test_writewatch.py:87,95,107 `config = Config(repo_root=self.root, shell=True)`; tests/simorgh/execution/test_service.py:581-584 build Config with tv_show_on_start=True then `dataclasses.replace(..., tv_show_on_start=False)` -- tests use the real dataclass, not partial objects
- grep for SimpleNamespace configs in tests/simorgh/{execution,voice}: 2 hits, both tests/simorgh/voice/test_two_voices_in_one_turn.py:47,64 `types.SimpleNamespace(keep_transcripts=True)` setting the one field read
- The 5 unmatched names all exist on some dataclass: interface/config.py:48 time_marker_minutes, :54 show_speaker_score; cognition/config.py:55 only_purposes (provider sub-config read at cognition/service.py:210); voice/config.py:332 overheard_dir (read cross-subsystem at execution/tools.py:2988 `getattr(self._config, "overheard_dir", None) or store.DEFAULT_DIR`)
- simorgh/kernel/configcheck.py:55-80 KNOWN_DEAD_FIELDS comment: it exists for fields that parse but nothing downstream reads (data-flow dead); configcheck.py:340-343 compares written vs baseline Config by field -- getattr access style is orthogonal to what it can detect

**severity adjustment:** lower


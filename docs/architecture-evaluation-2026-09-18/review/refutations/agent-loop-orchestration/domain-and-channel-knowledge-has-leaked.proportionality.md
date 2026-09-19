# refute:proportionality:Domain and channel knowledge has leaked

*Workflow: review · Phase: Refute · Agent id: `a614f9d654204e39e` · Tool calls: 5*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "agent-loop-orchestration". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "Domain and channel knowledge has leaked into the kernel loop (TV, cameras, voice mishearings, pronunciation)",
    "kind": "wrong-design",
    "severity": "medium",
    "claim": "session.py, the harness state machine, hard-codes the TV tool list, TV/dashboard claim regexes, a pronunciation-claim regex, misheard forms of Sim's name and a voice-only refusal rule, and Session carries speaker/room/speaker_before fields, so every new domain or channel means another regex and another branch in the core loop.",
    "evidence": [
      "simorgh/orchestration/session.py:189 `_TV_TOOLS = (\"cast_play\", \"cast_show\", \"tv_charts\", \"tv_app\", \"tv_key\", \"dash_view\", \"cast_stop\")`; :180-186 _TV_CLAIM; :191-197 _TV_ASK; :224-226 _DASH_ON_TV; :329-333 _NOTED_PRONUNCIATION; :553 _NAMES_SIM ('sim|sima|simorgh|sam|seem|seam|seym|syme'); :556 unplaced_voice_refusal",
      "session.py:1100-1195: eleven sequential guard branches in _run, each 'once per session' via marker_corrected/claim_corrected/invented_corrected flags on Session (api.py:118-131)",
      "simorgh/orchestration/api.py:166-175 Session fields speaker, speaker_relation, room, speaker_before",
      "git log: 80 commits to simorgh/orchestration/session.py since 2026-09-01, +2091/-149 lines; the file is 1,942 lines with 527 comment lines",
      "prior reviews (docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html) contain 0 hits for 'marker', 'lease', 'resume', 'cache', 'fsync'"
    ],
    "why_it_matters": "The loop is the one file everything depends on and it is the file with the highest churn; each guard is a reasonable live fix, but their home is wrong, so the fixes accrete where they are hardest to test in isolation and easiest to break each other (several guards share one claim_corrected flag, so only the first that fires in a session ever runs).",
    "recommendation": "Introduce a small reply-guard interface (`guard(text, session) -> Correction | None`) and let voice/, execution/media and the household contracts register their own guards; the loop applies at most one correction per step from an ordered list. Move channel fields into an opaque `session.channel_context` dict rendered by the channel's own scaffold. Most of the guards then disappear entirely once native tool calls land (finding 1).",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Locate the cited symbols in session.py |  1942 simorgh/orchestration/session.py 203 simorgh/orchestration/api.py 2145 total 184:_TV_CLAIM = re.compile( 189:_TV_TOOLS = ("cast_play", "cast_show", "tv_ch |
| 2 | Bash | Read the TV, pronunciation and voice-refusal guard definitions | _MARKER_LINE = re.compile(r"^\s*[A-Z][A-Z0-9_]{2,}:\s", re.M) def _marker_shaped(text: str) -> bool: """Whether a reply is (or opens with) a tool marker line -- |
| 3 | Bash | Read the guard branch block, Session fields, churn stats, and who else knows about TV tools and speaker fields |  # says what was found. answer = await self._wrap_up(session) if answer: step = Step(step_no, "act", "answered from what was found; the lookups had used the bud |
| 4 | Bash | Check who else knows the TV tools and speaker fields, whether guards are tested, and whether a registration seam already exists | ----WHO_ELSE_KNOWS_TV simorgh/interface/dispatch.py simorgh/interface/httpapi.py simorgh/interface/live_status.py simorgh/contracts/toolargs.py simorgh/executio |
| 5 | Bash | Inspect claims.py and how the guards are tested and structured | ----CLAIMS_PY 122 simorgh/orchestration/claims.py """Check what a final answer CLAIMS against what the session DID. The existing guard (`_transcript_echo`) catc |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The factual core holds against the code: session.py does hard-code the TV tool tuple, three TV/dashboard regexes, a pronunciation-claim regex, misheard spellings of Sim's name and a voice-only refusal rule; Session (api.py) carries four voice-specific fields; the churn numbers (80 commits, +2091/-149, 527 comment lines) reproduce exactly; and four of the guard branches (pronunciation, commit, promised-behaviour, TV) really do share one `claim_corrected` flag, so only the first to fire in a session ever corrects. Line numbers in the finding drift by 4-9 lines and it says "eleven" guard branches where the correction chain at 1078-1185 has seven (marker, echo, invented, pronunciation, commit, promised, tv); the substance is unaffected.

Where the finding overreaches: (1) "hardest to test in isolation" is wrong -- every guard is a module-level pure function `f(text, session) -> str` and is tested directly that way (test_pronunciation_claim.py imports `claimed_to_note_a_pronunciation`; test_honesty_claims.py has 11 tests, test_claims.py 17). (2) The TV tool names are not uniquely leaked into the loop: they are already known to profiles.py, scaffolds.py and tools.py inside orchestration and to 6 other files; session.py is one more consumer, gated through `session.profile.tools`. (3) The speaker fields are written only by voice/ and rendered only by scaffolds.py's voice branch; turning four typed strings into an opaque dict for a one-developer project trades type safety for nothing at this scale. (4) "Most guards disappear once native tool calls land" is speculative: the TV and pronunciation guards catch a model *saying* an act happened with no call at all, which native tool-call APIs do not prevent.

Where it is materially right and even understated: orchestration/claims.py already contains a data-driven `_RULES` table of (why, substantiating tools, patterns) for exactly this kind of unsupported-claim check, so the seam the recommendation asks for already exists in the same package -- the newer guards in session.py simply did not use it. The shared `claim_corrected` flag is a genuine small bug. Because the guards are already pure functions, folding them into an ordered list applied at most once per step is a ~50-line local refactor, not an architectural programme -- which also means the severity of leaving it is lower than "medium wrong-design" implies. Net: a right design (loop applies honesty guards) with a mildly sloppy implementation (imperative chain, shared flag, ignoring the existing rules table), plus one real bug; not a wrong design at one-laptop scale.

**corrected claim:** session.py's reply-correction chain (seven branches at simorgh/orchestration/session.py:1078-1185) hard-codes TV, pronunciation and voice-name knowledge as pure guard functions, and four of them share one `claim_corrected` flag so only the first firing guard per session ever corrects; the guards are unit-tested in isolation and gated on the profile's tools, and orchestration/claims.py already has the data-driven rules table they should have joined. This is an implementation tidy-up plus one small bug, not a wrong design; the Session voice fields and the churn are consequences of it being the live-fix site, and the "opaque channel_context dict" and "guards vanish with native tool calls" parts of the recommendation are not supported.

### evidence

- simorgh/orchestration/session.py:184-198 `_TV_CLAIM`, `_TV_TOOLS = ("cast_play", "cast_show", "tv_charts", "tv_app", "tv_key", "dash_view", "cast_stop")`, `_TV_ASK`; :236 `_DASH_ON_TV`; :338 `_NOTED_PRONUNCIATION`; :553 `_NAMES_SIM = re.compile(r"\b(?:sim|sima|simorgh|sam|seem|seam|seym|syme)\b")`; :556 `def unplaced_voice_refusal` -- all present as claimed (line numbers drift 4-9 from the finding's)
- session.py:1125-1126, 1142-1143, 1156-1157, 1170-1171: pronunciation, commit, promised-behaviour and TV guards each test `not session.claim_corrected` then set it True -- shared flag confirmed; marker (:1079) and invented (:1110) have their own flags. Seven correction branches total in 1078-1185, not eleven
- simorgh/orchestration/api.py:166-175: `channel`, `speaker`, `speaker_relation`, `room`, `speaker_before` on Session; grep shows writers only in voice/session.py:1096, voice/pipeline.py:351-364, orchestration/service.py:278, worker.py:388-405, and the sole renderer scaffolds.py:642-662 (`if channel == "voice"`)
- `git log --since=2026-09-01 --oneline -- simorgh/orchestration/session.py | wc -l` -> 80; numstat sum -> +2091 -149; `grep -cE '^\s*#'` -> 527; `wc -l` -> 1942 (all reproduce)
- Guards are tested in isolation: tests/simorgh/orchestration/test_pronunciation_claim.py:10 `from simorgh.orchestration.session import claimed_to_note_a_pronunciation` (3 tests); test_honesty_claims.py 11 tests; test_claims.py 17 tests
- `grep -rln 'cast_play\|tv_charts' simorgh --include='*.py'` -> 10 files incl. orchestration/profiles.py, scaffolds.py, tools.py -- TV names are not confined to, nor first leaked by, session.py; claimed_tv_act gates on `session.profile.tools` (session.py:314)
- simorgh/orchestration/claims.py:1-60: `_RULES: tuple[tuple[str, tuple[str, ...], tuple[re.Pattern, ...]], ...]` -- an existing data-driven (why, tools, patterns) table for unsupported-claim checks, imported at session.py:31 and used at :693-709; the newer session.py guards duplicate this shape imperatively instead of extending it

**severity adjustment:** lower


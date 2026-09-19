# refute:correctness:Domain and channel knowledge has leaked

*Workflow: review · Phase: Refute · Agent id: `a0af96e0bfe5fdb43` · Tool calls: 5*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "agent-loop-orchestration". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Locate cited symbols in session.py |  1942 simorgh/orchestration/session.py 203 simorgh/orchestration/api.py 2145 total 184:_TV_CLAIM = re.compile( 189:_TV_TOOLS = ("cast_play", "cast_show", "tv_ch |
| 2 | Bash | Read the cited regions of session.py and api.py | _MARKER_LINE = re.compile(r"^\s*[A-Z][A-Z0-9_]{2,}:\s", re.M) def _marker_shaped(text: str) -> bool: """Whether a reply is (or opens with) a tool marker line -- |
| 3 | Bash | Count guards, git churn, comments, prior-review coverage, importers | == guard branches in _run (continue after correction): 79: if tool_calls and not is_last: 180: if stray and not is_last and not session.marker_corrected: 196: i |
| 4 | Bash | Count corrections in _run and check prior reviews for overlap | == correction pushes (role user) inside _run 875-1198: 1043: "role": "user", 1087: session.messages.append({"role": "user", "content": ( 1102: session.messages. |
| 5 | Bash | Read prior-review sections that mention session.py | **Mitigating context:** Home Assistant is not configured in this environment (no host, no token). The direct NVR path is currently the *only* path that works. T |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The substance of the claim is true of the code today and is not in the known-findings list. simorgh/orchestration/session.py (1,942 lines) hard-codes the TV tool tuple, three TV/dashboard claim regexes, a pronunciation-claim regex, a mishearing-of-Sim's-name regex, and a voice-only refusal rule; api.py's Session dataclass carries speaker/speaker_relation/room/speaker_before and three once-per-session correction flags. Four guards (pronunciation, commit, promise, TV claim) all check-and-set the single `session.claim_corrected` flag, so only the first to fire in a session ever sends a correction -- exactly as the finding says. Git churn (80 commits, +2091/-149 since 2026-09-01) and the 527 comment lines reproduce exactly. The three prior reviews mention session.py only for steer-injection and compaction; none mention domain/channel leakage, markers, regex guards or claim_corrected, so this is materially new. Two inaccuracies: (1) the cited line numbers drift by 4-12 lines (e.g. _TV_CLAIM is 184-188 not 180-186, _DASH_ON_TV 236-238 not 224-226, _NOTED_PRONUNCIATION 338-342 not 329-333, Session speaker fields at api.py:174-180 not 166-175); (2) "eleven sequential guard branches" overcounts -- the reply-text path of _run has seven correction branches (mid-sentence marker, transcript echo, invented marker, pronunciation claim, commit claim, promised behaviour, TV claim), plus the voice refusal applied in _run_batch at :1614. The design diagnosis (channel/domain knowledge accreting in the core loop, guards hard to test in isolation, guards masking each other via a shared flag) stands; severity medium is right for a one-laptop system where this is a maintainability cost, not a safety hole.

### evidence

- simorgh/orchestration/session.py:184-189 -- `_TV_CLAIM = re.compile(...tv|dashboard|chart|screen|video|song|youtube...)` and `_TV_TOOLS = ("cast_play", "cast_show", "tv_charts", "tv_app", "tv_key", "dash_view", "cast_stop")`
- simorgh/orchestration/session.py:193-199 -- `_TV_ASK` regex naming camera|cameras|chart|charts|video|youtube|news|markets|wallpaper; :236-238 `_DASH_ON_TV`; :338-342 `_NOTED_PRONUNCIATION`
- simorgh/orchestration/session.py:553 -- `_NAMES_SIM = re.compile(r"\b(?:sim|sima|simorgh|sam|seem|seam|seym|syme)\b", re.IGNORECASE)`; :556-581 `unplaced_voice_refusal` branches on `session.channel != "voice"` and `session.speaker`
- simorgh/orchestration/session.py:1079-1182 -- seven `if <guard> and not is_last` correction branches in `_run` (grep of `and not is_last` between lines 875-1198 lists them at 1079, 1095, 1110, 1125, 1142, 1156, 1170); lines 1125-1126, 1142-1143, 1156-1157, 1170-1171 each read `... and not session.claim_corrected:` then `session.claim_corrected = True` -- four guards on one flag
- simorgh/orchestration/session.py:1614 -- `refused = unplaced_voice_refusal(session, str(call.get("tool") or ""))` inside `_run_batch`
- simorgh/orchestration/api.py:118-124 -- `marker_corrected`, `claim_corrected`, `invented_corrected` flags on Session; :170-180 -- `channel`, `speaker`, `speaker_relation`, `room`, `speaker_before` fields
- `git log --since=2026-09-01 --oneline -- simorgh/orchestration/session.py | wc -l` -> 80; numstat sum -> +2091 -149; `wc -l` -> 1942; `grep -cE '^\s*#'` -> 527
- grep -il over docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html, docs/architecture-third-opinion-2026-09-18.md: 0 files for marker, lease, resume, cache, fsync, pronunc, claim_corrected; third-opinion doc names session.py only under 4.5 (steer injection) and 4.6 (compaction)
- session.py is imported by simorgh/planning/service.py, execution/tools.py, execution/config.py, execution/writewatch.py, verification/verdict.py, verification/checks/_files.py, verification/checks/fullsuiteran.py, contracts/pytestfailures.py -- supporting 'the one file everything depends on'

**severity adjustment:** keep

**corrected claim:** session.py, the harness state machine, hard-codes the TV tool list (:189), three TV/dashboard claim regexes (:184, :193, :236), a pronunciation-claim regex (:338), misheard forms of Sim's name (:553) and a voice-only refusal rule (:556); Session (api.py:170-180) carries channel/speaker/speaker_relation/room/speaker_before. `_run` applies seven sequential reply-text guards (:1079-1182), four of which (pronunciation, commit, promise, TV claim) gate on the single `claim_corrected` flag so only the first to fire per session ever corrects; an eighth guard (voice refusal) sits in `_run_batch` (:1614). Every new domain or channel therefore means another regex and another branch in the core loop.


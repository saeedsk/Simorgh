# refute:proportionality:Cognition's 'no real provider' health ti

*Workflow: review · Phase: Refute · Agent id: `a127eb8cae29ca7dc` · Tool calls: 8*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "cognition-memory-selfmodel". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "Cognition's 'no real provider' health timer is inverted",
    "kind": "bug",
    "severity": "low",
    "claim": "`_no_real_provider_since` is set to `now` on every floor reply, so `health()` reports degraded only when more than 300 s have passed since the LAST floor reply -- i.e. only once the system has stopped asking, never while it is actively falling to the floor.",
    "evidence": [
      "simorgh/cognition/service.py:374 `self._no_real_provider_since = self._ctx.clock.now() if floor else None`",
      "simorgh/cognition/service.py:242-247 `elapsed = now - self._no_real_provider_since; if elapsed > 300: return Health.degraded(...)`"
    ],
    "why_it_matters": "Has not bitten (0 floor replies on the ledger) but it is the one health signal for the subsystem the whole system depends on, and it is wired backwards; if the floor is kept, this is what would tell the operator.",
    "recommendation": "Set the timestamp only when it is None (`self._no_real_provider_since = self._no_real_provider_since or now` on floor, `None` on a real reply), or drop it with the floor.",
    "confidence": 0.95
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Find references to the health timer and floor in cognition service | 114: self._no_real_provider_since: float \| None = None 136: # `SIMORGH_COGNITION_PROVIDER_ORDER=floor` (comma-separated names) 145: self._floor = FloorProvider( |
| 2 | Bash | Read health() and think() around the cited lines, and find who consumes health |  async def stop(self) -> None: for sub in (self._sub_think, self._sub_compact, self._sub_state, self._sub_tick, getattr(self, "_sub_started", None)): if sub is  |
| 3 | Bash | Check floor default order, provider-change notice, health consumers, config, and tests |  if self._config_from_caller is None and ctx.config: self._config = Config.from_mapping(dict(ctx.config)) for problem in self._config.problems: # A malformed en |
| 4 | Bash | Check supervisor health polling, router floor behaviour, test intent, and ledger floor replies | 70- raise BootTimeout(f"{supervised.name} did not start within {self._boot_timeout_s}s") from exc 71- except Exception as exc: # noqa: BLE001 -- a boot failure  |
| 5 | Bash | Check router floor fallthrough, require_real default, ledger floor counts, and health publication |  continue if provider_budget is not None: await provider_budget.record(response) return response, False if budget.require_real: if last_error is None and any_av |
| 6 | Bash | Count floor replies in the cognition calls stream and check require_real defaults | cognition%3Abudget%3Aclaude_code_cli.jsonl cognition%3Abudget%3Agemini.jsonl cognition%3Abudget%3Aollama.jsonl cognition%3Abudget%3Atogether.jsonl cognition%3Ac |
| 7 | Bash | Count floor and provider values in the cognition calls stream with either JSON spacing |  9379 /Users/saeed/.simorgh/ledger/streams/cognition%3Acalls.jsonl 9379 "floor":false 1034 "provider":"claude_code_cli" 2 "provider":"gemini" 1360 "provider":"o |
| 8 | Bash | Confirm floor provider name and the think_direct path that bypasses the timer | 2:simorgh/cognition/providers/base.py-31- name = "floor" async def _summarize_for_compaction(self, text: str) -> str: """Layer 5's model call (04 section 5's "A |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** The claim is exactly what the code does. simorgh/cognition/service.py:374 assigns `self._no_real_provider_since = self._ctx.clock.now() if floor else None` after every routed reply, so the timestamp is overwritten with `now` on each floor reply rather than pinned at the first one. health() at :242-247 then reports degraded only when `now - _no_real_provider_since > 300`, i.e. only after at least five minutes with NO further floor reply (and no real reply, which would reset it to None). While the system is actively answering from the floor every few minutes, health stays ok; it flips to degraded only once traffic stops. That is inverted relative to its evident intent ("no real provider available for Ns"). It is a genuine bug (category c), not a design choice, and the one-line fix the finding proposes is proportionate.

Skeptic lens on impact at this scale: the practical consequence is smaller than the finding's "the one health signal the whole system depends on" framing. (1) The floor has never been reached in production: the cognition:calls ledger stream holds 9,379 think.completed events, all `"floor":false` (together 6983, ollama 1360, claude_code_cli 1034, gemini 2). (2) A separate, working operator signal already exists: `_notice_if_provider_changed` (service.py:508-533) prints "thinking moved from X to floor" on screen the moment the provider changes, because FloorProvider.name is "floor" (providers/base.py:31) and flows through response.provider. (3) Health "degraded" triggers no recovery: supervisor.poll_once (kernel/supervisor.py:81-97) restarts a service only on "down"; "degraded" merely updates status and is published on system.health. So the bug hides a status line, not a restart. (4) Ollama is configured as a local last resort before the floor (service.py:189-201), making a floor reply rarer still.

Materially new detail the finding missed: the signal is narrower than "on every floor reply". The task path sets `require_real_provider: True` (orchestration/session.py:1535), so in that path the router raises NoRealProvider (router.py:244-267) and service.py:361-363 replies with an error without ever touching `_no_real_provider_since`. `_summarize_for_compaction` (service.py:418) discards the floor flag (`_floor`) and never sets the timer either. So even with the timestamp fixed, health() would only ever observe floor replies on the `require_real=False` chat path; a system whose every provider is dead but that is only running tasks would report Health.ok() indefinitely. The recommendation should include setting the timer in the NoRealProvider branch too, or the fix is half a fix.

Severity: keep at low. Real, cheap to fix, never bitten, and redundantly covered by the provider-change notice.

### evidence

- simorgh/cognition/service.py:374 `self._no_real_provider_since = self._ctx.clock.now() if floor else None` -- overwritten with now on every floor reply, never pinned to the first
- simorgh/cognition/service.py:242-247 health(): `elapsed = self._ctx.clock.now() - self._no_real_provider_since; if elapsed > 300: return Health.degraded(...)` -- degraded only when >300s since the LAST floor reply
- simorgh/cognition/service.py:361-363 NoRealProvider branch replies with error code no_real_provider and returns before line 374; timer never set on the require_real path
- simorgh/orchestration/session.py:1535 `"require_real_provider": True` (task path) vs :1275 `"require_real_provider": False` (chat path)
- simorgh/cognition/router.py:244-268: with require_real the router raises NoRealProvider; without it returns `self._floor.respond_for_purpose(purpose), True`
- simorgh/cognition/service.py:418 `response, _floor = await self._router.complete(...)` in _summarize_for_compaction discards the floor flag; timer untouched
- simorgh/cognition/service.py:508-533 _notice_if_provider_changed prints 'thinking moved from X to Y' on any provider change; simorgh/cognition/providers/base.py:31 `name = "floor"` so a floor reply triggers it
- simorgh/kernel/supervisor.py:87-96 poll_once: restart only when health.status == "down"; degraded just updates status
- Command: `grep -o '"floor":[a-z]*' ~/.simorgh/ledger/streams/cognition%3Acalls.jsonl | sort | uniq -c` -> `9379 "floor":false` (wc -l: 9379 lines); providers: together 6983, ollama 1360, claude_code_cli 1034, gemini 2 -- the floor has never answered in production
- simorgh/cognition/config.py:73 default provider_order = (together, claude_code_cli, gemini, floor); service.py:189-201 inserts ollama before floor when configured
- Command: `grep -rn "no_real_provider_since" tests/` -> no matches; health() timer is untested

**severity adjustment:** keep

**corrected claim:** `_no_real_provider_since` is reset to `now` on every floor reply (service.py:374), so health() (service.py:242-247) reports degraded only once more than 300 s have passed since the last floor reply, never while floor replies are actively flowing. Additionally the timer is only touched on the require_real=False chat path: the task path (require_real_provider=True, session.py:1535) raises NoRealProvider and replies with an error at service.py:361-363 without setting it, and _summarize_for_compaction (service.py:418) discards the floor flag. Impact is limited: 0 of 9,379 recorded calls ever hit the floor, `_notice_if_provider_changed` (service.py:508) already tells the operator on screen when thinking moves to the floor, and a degraded health status triggers no supervisor action (supervisor.py:93-96 restarts only on down).


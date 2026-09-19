# refute:correctness:Cognition's 'no real provider' health ti

*Workflow: review · Phase: Refute · Agent id: `a8a15fed20b93bb26` · Tool calls: 3*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "cognition-memory-selfmodel". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Locate the health timer and floor references in cognition service | 114: self._no_real_provider_since: float \| None = None 136: # `SIMORGH_COGNITION_PROVIDER_ORDER=floor` (comma-separated names) 145: self._floor = FloorProvider( |
| 2 | Bash | Read health() and think() around the cited lines; check for other references and known findings | Exit code 1 async def stop(self) -> None: for sub in (self._sub_think, self._sub_compact, self._sub_state, self._sub_tick, getattr(self, "_sub_started", None)): |
| 3 | Bash | Check other references, known-findings docs, ledger floor counts, router floor semantics | --- known docs: --- floor replies on ledger: blobs heads idem (eval):1: no matches found: /Users/saeed/.simorgh/ledger/*.jsonl --- router raise NoRealProvider:  |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** The cited code reads exactly as claimed. simorgh/cognition/service.py:374 unconditionally reassigns `self._no_real_provider_since = self._ctx.clock.now() if floor else None` after every successful router call, so on a run of consecutive floor replies the timestamp is reset to `now` each time. health() at lines 242-247 computes `elapsed = now - self._no_real_provider_since` and returns degraded only when `elapsed > 300`. Therefore while the system is actively answering from the floor more often than every 5 minutes, elapsed never exceeds 300 and health() stays ok; it flips to degraded only after 5 minutes of silence following a floor reply, which is the opposite of the intended "no real provider available for Ns" semantics the message text describes. Two further points strengthen it: (1) the `NoRealProvider` exception path at lines 360-362 returns early and never touches the timestamp at all, so the require-real-provider failure mode is also invisible to health(); (2) no other module or test references `_no_real_provider_since` (grep across simorgh/ and tests/ finds only service.py), so nothing exercises or corrects the behaviour. The finding does not appear in docs/architecture-review-2026-09-18.html, docs/architecture-audit-2026.md, or the third-opinion doc (grep for no_real_provider / "no real provider" returns nothing), so it is not already known. This is a genuine bug (category c), low severity as stated: correct design (a floor-duration health signal), wrong implementation of the timer. The secondary "0 floor replies on the ledger" assertion was not re-verified (ledger is blob-based, not JSONL grep-able cheaply), but it is not load-bearing for the code claim.

### evidence

- simorgh/cognition/service.py:374 `self._no_real_provider_since = self._ctx.clock.now() if floor else None` -- reassigned to now on every floor reply, not only on the first
- simorgh/cognition/service.py:242-247 `if self._no_real_provider_since is not None: elapsed = self._ctx.clock.now() - self._no_real_provider_since; if elapsed > 300: return Health.degraded(f"no real provider available for {elapsed:.0f}s")` -- measures time since LAST floor reply, not time in floor mode
- simorgh/cognition/service.py:360-362 `except NoRealProvider as exc: await self._error_reply(...); return` -- the hard-failure path returns before line 374 and never sets the timestamp
- simorgh/cognition/router.py:268 `return self._floor.respond_for_purpose(purpose), True` -- the router's floor path returns floor=True per call, confirming line 374 fires on every floor answer
- grep -rn _no_real_provider_since simorgh tests | grep -v cognition/service.py -> no output (no reader, no test)
- grep -in 'no_real_provider|no real provider' docs/architecture-review-2026-09-18.html docs/architecture-audit-2026.md docs/architecture-third-opinion-2026-09-18.md -> no output (not in known findings)

**severity adjustment:** keep


# refute:proportionality:Persona is observable but its cost is ou

*Workflow: review · Phase: Refute · Agent id: `a20a01ef23dacc284` · Tool calls: 7*

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
    "title": "Persona is observable but its cost is out of proportion to what it adds",
    "kind": "over-engineering",
    "severity": "medium",
    "claim": "Persona writes a ledger event and a bus message every 5 s of mood decay (93% of its 47,784 events, 17.8 MB), adds a bus round-trip with a 2 s timeout to every prompt assembly to inject one sentence ('Right now you're feeling <phrase>.') derived from a ~30-word lexicon, and its user model has extracted one facet in the system's lifetime.",
    "evidence": [
      "Measured from ~/.simorgh/ledger/streams/persona%3Astate.jsonl: `persona:state events 47784 size MB 17.8` / sources `[('decay', 44444), ('task.completed', 2516), ('task.blocked', 328), ('percept.text', 288), ('health.reset', 141), ('task.failed', 67)]`",
      "simorgh/persona/config.py:16 `decay_interval_s: float = 5.0`; persona/service.py:226-236 `_on_tick_second` publishes `PERSONA_STATE_CHANGED` and persists on every significant decay",
      "simorgh/persona/emotion.py:14-24: 12 positive, 12 negative, 7 arousal words; user_model.py:16-17 two regexes (`I prefer`, `call me`); measured `persona:user_model events 1 {'preferred_name': 1}`",
      "simorgh/cognition/assembler.py:54 `voice = await self._try_request(topics.PERSONA_VOICE, ...)` on every `assemble`; cognition/config.py:136 `assembly_request_timeout: float = 2.0`",
      "Observable outputs: persona/voice.py:40-41 mood sentence in a protected prompt block; interface/vitals.py:159 mood bar; voice/service.py:687-692 mood -> delivery; curiosity/service.py:155 and reflection/service.py:184 subscribe"
    ],
    "why_it_matters": "For one laptop and one family a mood engine is a fine flourish, but it is currently the noisiest writer in this concern (17.8 MB of the ledger is decay ticks) and it sits in the latency path of every model call. Meanwhile the one thing a persona layer should do for a household, model each person, is absent (finding on identity).",
    "recommendation": "Persist mood only on non-decay changes and compute decay lazily on read (store `(value, ts)` and decay in `current()`), which removes ~93% of the stream; have Persona publish `persona.voice.changed` and let Cognition cache the style block instead of requesting it per prompt; key the user model by `person` once the identity contract exists. Keep the lexicon floor; it is cheap and honest.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read persona config and tick handler | """`simorgh.toml [persona]` (spec section 3.5).""" from __future__ import annotations from dataclasses import dataclass from pathlib import Path @dataclass(froz |
| 2 | Bash | Measure persona ledger streams | -rw-r--r-- 1 saeed staff 273 Sep 15 21:18 persona%3Ashares.jsonl -rw-r--r--@ 1 saeed staff 17819390 Sep 18 17:14 persona%3Astate.jsonl -rw-r--r-- 1 saeed staff  |
| 3 | Bash | Read decay tick, lexicon, user model, assembler and subscribers | 29:_SIGNIFICANT_DELTA = 1e-4 123: await ctx.bus.subscribe(topics.SYSTEM_TICK_SECOND, self._on_tick_second), 199: if (abs(new.valence - previous.valence) < _SIGN |
| 4 | Bash | Read decay tick, subscribers, bus request path, ledger size ranking |  source="health.reset", ) await self._publish_state_changed(previous, new, "health.reset") async def _on_tick_second(self, message: Message) -> None: now = self |
| 5 | Bash | Measure event span, ledger fsync policy, assemble callers, bus request path | first ts 1789014580.909865 last ts 1789776856.405876 span days 8.822633055683088 sample {"causation_id": null, "idempotency_key": null, "payload": {"arousal": 4 |
| 6 | Bash | Check which assembler chat uses and ledger append fsync cost | 2:session transcript for one `cognition.think` call. The persona voice and 133: Deliberately *not* the persona voice or the self summary. Both ---- cognition se |
| 7 | Bash | Check JSONL append fsync and orchestration context note about persona | __init__.py __pycache__ api.py backends blobs.py client.py compaction.py config.py factory.py idempotency.py migrate_v1.py projection.py README.md service.py st |

## Structured reply

**refuted:** False

**verdict:** partly-true

**corrected claim:** Persona's mood decay is chatty: with decay_interval_s=5.0 and a significance floor of 1e-4, every 5 s tick that moves valence/arousal by >=1e-4 publishes PERSONA_STATE_CHANGED (fanned out to interface, voice, curiosity and reflection) and appends an fsync'd ledger event; measured 44,444 of 47,784 persona:state events (93%, 17.8 MB) over 8.8 days are decay ticks, i.e. ~2 MB/day and ~5,000 fsync'd appends/day. Cognition's assembler does request persona.voice on every think call with a 2 s ceiling, but the handler is a local compose over in-memory state on an in-process asyncio bus, so the real added latency is negligible and the creator already measured and de-duplicated this round-trip (orchestration/context.py:133-140). The lexicon (12/12/7 words) and the user model (two regexes, one facet ever extracted) are as described. This is a tuning-level cost (2.6% of the 696 MB streams dir; metrics:history at 119 MB and curiosity:ticks at 45 MB are far larger), not an architectural fault; a one-line change to the significance floor or decay interval, or lazy decay-on-read (already half-built in _restore_mood), removes most of it.

**reasoning:** Every factual element of the finding checks out against the code and the live ledger, so it cannot be refuted on facts. What does not hold up is the weight put on those facts. (1) Cost in absolute terms is small: 17.8 MB across 8.8 days is ~2 MB/day and about one fsync'd append every 17 s on average; on one laptop that is invisible, and persona:state is only the third-largest stream, dwarfed by metrics:history (119 MB) and curiosity:ticks (45 MB), so "noisiest writer" is true only under the concern's narrow scoping. (2) The "2 s timeout on every prompt assembly" is a ceiling, not a cost: bus.request is an in-process asyncio future (bus/client.py:261-286) and _on_voice_request (persona/service.py:280-284) does a pure in-memory compose, so the round-trip is sub-millisecond against a multi-second model call; the orchestration/context.py:133-140 docstring shows the creator already measured this path and removed the duplicate request, i.e. it is a considered design, not an oversight. (3) The proposed restructuring (lazy decay + publish-on-voice-change + Cognition caching) would remove the push that four subscribers (interface vitals mood bar, voice delivery mood, curiosity, reflection) currently rely on, so it trades a trivial write cost for new polling/staleness logic; a far cheaper fix exists (raise _SIGNIFICANT_DELTA from 1e-4 to ~5e-3, or raise decay_interval_s), since with half-life 900 s a 5 s tick moves value by only 0.38% and the 1e-4 floor keeps writing until |v| < 0.026, roughly 290 events per task-completion nudge. (4) The user-model observation is real but is already covered by the separate identity finding. Net: category (a) minor tuning of a flourish, not an over-engineering problem at this scale; severity should drop to low.

### evidence

- simorgh/persona/config.py:15-16 `decay_half_life_s: float = 900.0` / `decay_interval_s: float = 5.0`; simorgh/persona/service.py:29 `_SIGNIFICANT_DELTA = 1e-4`
- simorgh/persona/service.py:266-275 `_on_tick_second`: returns if elapsed < decay_interval_s, else decays and calls `_publish_state_changed(previous, new, "decay")` when |delta| >= 1e-4; lines 206-217 `_publish_state_changed` does `bus.publish(PERSONA_STATE_CHANGED)` then `_persist("persona:state", ...)` -> `ledger.append`
- Measured: `persona:state events 47784 size MB 17.8`, sources `[('decay', 44444), ('task.completed', 2516), ('task.blocked', 328), ('percept.text', 288), ('health.reset', 141), ('task.failed', 67)]`; first ts 1789014580.9, last ts 1789776856.4 -> span 8.82 days (~2 MB/day, ~5.4k events/day). Last event sample: valence 0.08687 -> 0.08653 (delta 3.3e-4, above the 1e-4 floor) with source `decay`
- simorgh/ledger/backends/jsonl.py:410-413 `fh.write(line); fh.flush(); if self._fsync: os.fsync(...)`; ledger/config.py:20 `fsync: bool = True`; ~/.simorgh/simorgh.toml has no `[ledger]` fsync/backend override -> every decay event is an fsync'd append
- `du -sh ~/.simorgh/ledger/streams/` = 696M; largest files: metrics%3Ahistory.jsonl 119,099,341 B, curiosity%3Aticks.jsonl 45,068,994 B, persona%3Astate.jsonl 17,819,390 B (third; 2.6% of streams)
- simorgh/cognition/assembler.py:54 `voice = await self._try_request(topics.PERSONA_VOICE, {...})` inside `assemble`; :114-124 `_try_request` uses `self._bus.request(message, timeout=self._timeout)` and omits on exception; cognition/config.py:136 `assembly_request_timeout: float = 2.0  # persona.voice / self.summary -- omitted on timeout, not fatal`
- simorgh/bus/client.py:261-286 `request` = publish + `asyncio.wait_for(fut, timeout)` on an in-process Future; simorgh/persona/service.py:280-284 `_on_voice_request` composes from `self._mood.current()` with no I/O -> round-trip cost is sub-ms, 2 s is only a ceiling
- simorgh/orchestration/context.py:133-140: 'Deliberately *not* the persona voice or the self summary... Measured 2026-09-07: every think call carried both twice ... and paid for two extra bus round trips' -> the creator already measured and pruned this path
- simorgh/persona/emotion.py:14-24: 12 positive, 12 negative, 7 high-arousal words (counted); simorgh/persona/user_model.py:16-17 `_PREFER_RE`, `_CALL_ME_RE`; `persona%3Auser_model.jsonl` = 260 bytes, 1 line
- PERSONA_STATE_CHANGED subscribers that would lose their push under lazy decay: simorgh/interface/service.py:234, simorgh/voice/service.py:182 (`_on_mood` sets pipeline.mood, :687-692), simorgh/curiosity/service.py:155, simorgh/reflection/service.py:184
- simorgh/persona/service.py:176-178 `_restore_mood` already applies `decay_toward_baseline(elapsed, ...)` on restart from the last persisted (value, ts) -> lazy decay-on-read is half-implemented, making the cheap fix cheap

**severity adjustment:** lower


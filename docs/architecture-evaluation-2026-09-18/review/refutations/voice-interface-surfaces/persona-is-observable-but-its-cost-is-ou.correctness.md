# refute:correctness:Persona is observable but its cost is ou

*Workflow: review · Phase: Refute · Agent id: `ab6dcec061a79bede` · Tool calls: 4*

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
| 2 | Bash | Read remaining cited persona and cognition code | 29:_SIGNIFICANT_DELTA = 1e-4 75: topics.REFLECT_HEALTH_FINDING, topics.SYSTEM_TICK_SECOND, topics.SYSTEM_STATE_CHANGED, 88: self._last_decay_ts = 0.0 114: self. |
| 3 | Bash | Measure persona ledger streams and check known-findings docs | -rw-r--r-- 1 saeed staff 273 Sep 15 21:18 persona%3Ashares.jsonl -rw-r--r--@ 1 saeed staff 17819390 Sep 18 17:14 persona%3Astate.jsonl -rw-r--r-- 1 saeed staff  |
| 4 | Bash | Check decay maths, stream time span, voice handler, and stream rankings | 100: def decay_toward_baseline(self, elapsed_s: float, *, half_life_s: float = 900.0) -> tuple[EmotionalState, EmotionalState]: 101- if elapsed_s <= 0 or half_l |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited file:line and every measured number checks out today. simorgh/persona/config.py:16 sets decay_interval_s=5.0; service.py:266-275 (_on_tick_second) runs decay each tick once 5 s have elapsed and calls _publish_state_changed whenever |delta| >= _SIGNIFICANT_DELTA (1e-4, service.py:29), which at service.py:206-215 does both a bus publish and a ledger append. Re-counting ~/.simorgh/ledger/streams/persona%3Astate.jsonl gives exactly 47,784 events / 17.8 MB with 44,444 'decay' sources (93%), median decay gap 5.007 s and 98.3% of gaps <= 6 s. It is the third-largest of the 118k stream files (behind metrics:history 119 MB and curiosity:ticks 45 MB). cognition/assembler.py:54 issues a PERSONA_VOICE bus request on every assemble() with request_timeout from cognition/config.py:136 (2.0), no caching; persona/voice.py:55 renders 'Right now you're feeling {phrase}.'; emotion.py:13-23 has 12/12/7 words; user_model.py:16-17 has exactly two regexes; persona%3Auser_model.jsonl holds one event. Neither docs/architecture-review-2026-09-18.html nor docs/architecture-audit-2026.md mentions decay or mood, so this is not a repeat (the ledger-is-1.4GB finding is known, but persona's share of it is new). Three refinements, none of which weaken the finding: (1) 'system's lifetime' overstates: the stream starts 2026-09-09 21:29 (after the 09-07 ledger cleanup), so it is one facet in ~212 h; (2) decay publishing is gated by the 1e-4 significance check, so in code it is not unconditionally every 5 s, but because 2,516 task.completed nudges of +0.08 keep valence (~0.087 at the tail) far above the ~0.026 stop threshold it fires at 5 s in practice; (3) the single extracted facet is itself a mis-parse: preferred_name='for' (a 'call me for ...' phrase matched _CALL_ME_RE), so the user model has produced zero correct facts. The 2 s figure is a worst-case cap on a cheap in-process handler (service.py:280-284 just composes a string), so the per-prompt latency cost is small; the ledger/bus noise is the substantive cost. Category: design that is defensible (mood floor, observable) but whose persistence/request pattern is over-built for one laptop; severity medium is right: 17.8 MB is ~1.3% of the 1.4 GB ledger, real but not the main driver.

**corrected claim:** Persona persists a ledger event and publishes a bus message on nearly every 5 s decay tick (gated only by a 1e-4 significance check that constant task.completed nudges keep it above): 44,444 of the 47,784 persona:state events since the 2026-09-09 ledger reset (93%, 17.8 MB, third-largest stream) are decay ticks. Every prompt assembly makes an uncached PERSONA_VOICE bus request (2 s timeout cap, cheap in practice) to inject one sentence from a ~31-word lexicon. The regex user model has extracted a single facet in ~212 hours, and that one is wrong (preferred_name='for').

### evidence

- simorgh/persona/config.py:16 `decay_interval_s: float = 5.0`; :15 `decay_half_life_s: float = 900.0`
- simorgh/persona/service.py:29 `_SIGNIFICANT_DELTA = 1e-4`; :266-275 `_on_tick_second` decays when elapsed >= decay_interval_s and calls `_publish_state_changed(previous, new, "decay")` if |delta| >= 1e-4; :206-215 `_publish_state_changed` does `bus.publish(PERSONA_STATE_CHANGED)` then `_persist("persona:state", ...)` -> `ledger.append`
- Measured: `events 47784 size MB 17.8` sources `[('decay', 44444), ('task.completed', 2516), ('task.blocked', 328), ('percept.text', 288), ('health.reset', 141), ('task.failed', 67)]`; first ts 2026-09-09 21:29, last 2026-09-18 17:14, span 211.7 h; decay gaps median 5.007 s, 98.3% <= 6 s; avg 373 bytes/event; tail valences 0.088/0.087 (above the ~0.026 threshold where a 5 s step would fall below 1e-4)
- `ls -lS ~/.simorgh/ledger/streams | head`: metrics%3Ahistory.jsonl 119,099,341; curiosity%3Aticks.jsonl 45,068,994; persona%3Astate.jsonl 17,819,390 (3rd of 118,215 files; `du -sh ~/.simorgh/ledger` = 1.4G)
- simorgh/cognition/assembler.py:54 `voice = await self._try_request(topics.PERSONA_VOICE, {...})` inside `assemble()` with no cache; cognition/config.py:136 `assembly_request_timeout: float = 2.0`; cognition/service.py:213 passes it as request_timeout
- simorgh/persona/service.py:280-284 `_on_voice_request` just calls `self._voice.compose(self._mood.current(), ...)` and replies (cheap handler; 2 s is a cap not a cost)
- simorgh/persona/voice.py:55 `mood_sentence = f"Right now you're feeling {phrase}."`
- simorgh/persona/emotion.py:13-23: 12 positive, 12 negative, 7 high-arousal words; user_model.py:16-17 `_PREFER_RE`, `_CALL_ME_RE` only
- persona%3Auser_model.jsonl: 1 event, payload `{"confidence":0.7,"facet":"preferred_name","value":"for"}`
- Subscribers/consumers confirmed: interface/vitals.py:80 reads valence; voice/service.py:687-692 `_on_mood` sets pipeline.mood; curiosity/service.py:155 and reflection/service.py:184 subscribe to PERSONA_STATE_CHANGED
- `grep -n -i 'decay\|mood' docs/architecture-review-2026-09-18.html docs/architecture-audit-2026.md` returns nothing: not in the known-findings list

**severity adjustment:** keep


# refute:proportionality:25 of 137 non-reply topics have only one

*Workflow: review · Phase: Refute · Agent id: `a91ce9a73d070cebf` · Tool calls: 6*

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
    "title": "25 of 137 non-reply topics have only one side (or none), each with a schema file, a declaration and tests",
    "kind": "over-engineering",
    "severity": "medium",
    "claim": "The catalogue is 174 types; after excluding the 37 `.reply` types, 10 are published and never consumed, 9 are subscribed and never published, 5 are declared and never referenced, and 1 is referenced only in a comment -- the 'unconnected wire' shape exists at the contract level and nothing fails on it.",
    "evidence": [
      "topics_audit2.py over simorgh/ (excluding contracts/): \"{'both': 111, 'unreferenced': 5, 'pub-only': 10, 'reply': 37, 'ref-only': 1, 'sub-only': 10}\" (memory.forget was a false positive via an aliased import, so sub-only is 9)",
      "pub-only: benchmark.run.completed, curiosity.interest.updated, plan.approved, reflect.alert.cleared, reflect.alert.raised, self.model.updated, system.schedule.added, task.dependency.satisfied, tool.invoked, world.env.observed",
      "sub-only: cognition.compact.request, curiosity.discover.request, curiosity.interest.follow_up.request, curiosity.share.request, learn.pipeline.run, learn.strategy.suggest, reflect.review.request, research.finding.recorded (plus task.progress, which is a ledger-only event read by orchestration/resume.py:58 -- not a bus defect)",
      "unreferenced: learn.experiment.result, percept.file.changed, plan.reground, plan.reground.reply, system.reload, ui.rendered",
      "ls simorgh/contracts/schema | wc -l -> 174; contracts/topics.py:1-8 \"CATALOG is the authoritative list ... messages/ must define exactly this set (tests/simorgh/contracts/test_catalog.py proves it)\" -- the test proves the catalogue matches itself, not that it is used"
    ],
    "why_it_matters": "A catalogue that is 18% one-sided teaches the model (and the next reader) that a topic existing means a capability exists. Three of the sub-only requests are the whole public surface of Curiosity and Reflection review, so those subsystems are partly unreachable by design rather than by bug.",
    "recommendation": "Turn the audit script into a test: fail on any CATALOG type that is neither published nor consumed in simorgh/, with a short allow-list of externally-triggered types. Delete the 6 unreferenced types and the dead-pipeline types (learn.pipeline.run, learn.strategy.suggest, learn.experiment.result) with finding 1; decide per remaining item whether to wire or remove.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Count schema files and read the topics catalogue header |  174 """The topic catalog: every domain, every message type (as a constant), subscription-pattern matching, reply naming, and the reserved-topology table the Ke |
| 2 | Bash | Rough pub/sub audit of catalogue topics across simorgh/ excluding contracts | catalog 174 sub-only action.approved refs=14 pub=0 sub=4 sub-only action.needs_human refs=9 pub=0 sub=1 pub-only benchmark.history.reply refs=4 pub=3 sub=0 pub- |
| 3 | Bash | Grep the ten claimed pub-only topics by value and constant name | === benchmark.run.completed === BENCHMARK_RUN_COMPLETED simorgh/benchmark/service.py:40: topics.BENCHMARK_PROGRESS, topics.BENCHMARK_RUN_COMPLETED, topics.TASK_ |
| 4 | Bash | Find wildcard subscriptions and the topic pattern matcher | ### wildcard subscriptions simorgh/bus/api.py:62: pattern: str # "task.*", "action.#", "#", or an exact "_inbox.<source>.<uuid>" simorgh/execution/pim/connector |
| 5 | Bash | Check wildcard subscribers, world.env.observed publish, and publishers of claimed sub-only requests | ### '#' / '*' pattern subscribers simorgh/interface/render.py:294: return "#" * filled + "-" * (width - filled) simorgh/interface/render.py:555: return "#" * fi |
| 6 | Bash | Read learning self-diagnosis, kernel topology checks, wildcard tap subscribers, and curiosity/reflection entry points | ### learning/service.py 92-120 self._subs.clear() #: Why this subsystem cannot currently do the thing it exists for. #: Two independent reasons, both verified 2 |

## Structured reply

_No result recorded (agent still running, skipped, or failed)._

## Final text

You've hit your session limit · resets 11:10pm (America/Los_Angeles)
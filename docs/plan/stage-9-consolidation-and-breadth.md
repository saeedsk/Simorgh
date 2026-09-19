# Stage 9 -- Consolidation and breadth (ongoing)

Status: not started · Depends on: every earlier stage landed through the gate · Estimated: 4 weeks then ongoing · Modules touched: orchestration, cognition, interface, execution, ledger, voice; new packages `agent`, `llm`, `perception`, `channels`, `admin`, `domains`

## Outcome

The loop lives in one place (`agent/`), the model gateway in another (`llm/`), the surfaces are two small packages (`channels/`, `admin/`), perception is its own module, the product domains sit behind Execution's `extra_tools` seam rather than inside the most trusted package, and the decision log's default backend is SQLite. Breadth arrives as the creator decides: Home Assistant as the hub, Frigate/go2rtc for the cameras, MCP-first for new capability, the browser agent, the household end-to-end suite.

## Why

Evaluation W10 (Execution is a 21.6k-line package holding six product domains next to the HMAC verifier), section 4.9 (boundaries drifted), the judges' "second rewrite" and "half-migration" risks, which is why these moves are last and one at a time. The creator's 2026-09-19 decision: home-automation heavy lifting moves to Home Assistant; camera monitoring may move to an external system.

## Before you start

Every move is a pure file move with shims, gated by the evals suite, old path deleted before the next move begins. Never combine a move with a behaviour change in one commit.

## Action items

1. **Domains out of Execution.** *Lock `execution`, `domains` (new).* `simorgh/execution/{knowledge,pim,security,home,energy,media}/` → `simorgh/domains/<name>/`, registered through `extra_tools`; Execution keeps registry, verifier, sandboxes, worktrees, path/net safety; only that is Guardian-protected. Acceptance: tool count unchanged; the boundary test knows `domains`; Guardian's protected list names `simorgh/execution/` only for what remains.
2. **`agent/` and `llm/`.** *Lock `orchestration`, `cognition`, `agent`, `llm`.* `orchestration/` + the ContextBuilder + agents loader → `simorgh/agent/`; `cognition/{providers,router,budget,tokens}` → `simorgh/llm/`; the marker fallback dialect and compaction layers move with them; shims for one bless cycle; LAYERS and AGENTS.md updated. Acceptance: every module tier green; trial suite and benchmarks unchanged within CI.
3. **`channels/` and `admin/`.** *Lock `interface`.* `interface/{cli,tui,render,telegram,whatsapp,httpapi (chat and TV routes)}` → `channels/`; `interface/dispatch.py` (operator commands, shrunk to the operator-only set with a declared command registry) → `admin/`; every operator command the model needs is a tool with a schema; `sim_command` restricted to restart/pause/mode. Acceptance: `dispatch.py` under 600 lines; no model-reachable operator function without a schema.
4. **`perception/`.** *Lock `execution`, `perception` (new).* `execution/vision.py` and the camera/Ring watchers → `simorgh/perception/`, publishing `percept.home.*` events; the ffmpeg HLS relay is deleted when Frigate/go2rtc is in place (item 8). Acceptance: camera announcements judged "described the event, not the scene" > 90% (with tracked-object events).
5. **SQLite as the decision log's default.** *Lock `ledger`.* `[ledger] backend = "sqlite"` default; a migration script from JSONL (export/import both ways); JSONL stays available. Its own eval: boot time, append latency, resume-after-kill on the long-task suite. Acceptance: the eval passes on a copy of the live data dir before the default flips.
6. **Engines out of process, only if spans show a stall.** *Lock `voice`.* STT/TTS in a subprocess with a pipe protocol, triggered only if stage-3 spans show an engine stalling the event loop. Otherwise skip.
7. **Home Assistant as the hub (creator's hardware decision).** *Lock `domains`, `perception`, `guardian`.* HA websocket bridge (`percept.home.state_changed`); `home_automation_create/enable/disable` and `home_scene_apply` as tier-3 tools; the registry seeded from HA's area/device registry; device-direct code (Reolink, Ring, Cast, Android TV, Music) retired one integration at a time as HA covers it. Acceptance: the household end-to-end suite (lights, TV, reminders, mail lookup, camera snapshot) passes through HA.
8. **Frigate/go2rtc for the cameras (creator's decision).** *Lock `perception`, `channels`.* Tracked-object events replace whole-scene description; live view served by go2rtc, not by Sim's HTTP server; `workspace/cameras` no longer written. Acceptance: no ffmpeg child processes; the dashboard's camera tiles come from go2rtc URLs with the token.
9. **MCP-first for new capability.** *Lock `execution`, `docs`.* A one-page `docs/adding-capability.md`: an MCP server with schemas, human-configured, Guardian-gated; no new tool classes for external services. Acceptance: the next integration arrives as a server.
10. **The browser agent.** *Lock `agent`, `execution`.* `browse_page` grows into a snapshot-act loop (accessibility-tree snapshot, act by element id, bounded steps) used by `agents/browser.md`. Acceptance: a scripted three-page form task completes.
11. **The household end-to-end suite** in `simorgh/evals/household/` grows with every integration; "more general" is its coverage number (evaluation section 11).

## Measurements after

| Number | Target |
|---|---|
| Lines in `simorgh/execution/` | under 8,000 |
| `dispatch.py` lines | under 600 |
| Household suite coverage (goals completed end to end) | rising per release |
| Camera announcements about the event, not the scene | > 90% |

## Risks and mitigations

- Half-migration: one move per commit, shims deleted before the next, evals after each.
- Hardware dependencies (HA box, Frigate) are the creator's call; nothing in stages 0-8 waits on them.

## Definition of done

- [ ] Items 1-5 landed with shims removed; every CONTRACT.md moved with its module.
- [ ] Items 7-11 as the creator's hardware decisions allow, each with a findings entry.

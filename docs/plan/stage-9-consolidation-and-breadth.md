# Stage 9 -- Consolidation and breadth (ongoing)

Status: **in progress** (2026-09-21: items 1 and 9 done; item 5's tooling done but the default REVERTED after the first live boot spun -- see below; the ledger default is JSONL again (`ledger/config.py`: `backend = "jsonl"`), SQLite by opt-in; `simorgh/execution/` 22.3k -> 11.0k lines; item 11 started -- breadth scenarios for the house and, from 2026-09-21, the typed console (`stage9/the-console-answers`, `stage9/a-mistyped-command-is-answered-kindly`); items 2-4 and 6-8 not started; item 10 has its agent definition (`agents/browser.md`, stage 7 item 2) over `browse_page`'s action list, and no accessibility-tree snapshot or act-by-element-id yet) · Depends on: every earlier stage landed through the gate · Estimated: 4 weeks then ongoing · Modules touched: orchestration, cognition, interface, execution, ledger, voice; new packages `agent`, `llm`, `perception`, `channels`, `admin`, `domains`

## Outcome

The loop lives in one place (`agent/`), the model gateway in another (`llm/`), the surfaces are two small packages (`channels/`, `admin/`), perception is its own module, the product domains sit behind Execution's `extra_tools` seam rather than inside the most trusted package, and the decision log's default backend is SQLite. Breadth arrives as the creator decides: Home Assistant as the hub, Frigate/go2rtc for the cameras, MCP-first for new capability, the browser agent, the household end-to-end suite.

## Why

Evaluation W10 (Execution is a 21.6k-line package holding six product domains next to the HMAC verifier), section 4.9 (boundaries drifted), the judges' "second rewrite" and "half-migration" risks, which is why these moves are last and one at a time. The creator's 2026-09-19 decision: home-automation heavy lifting moves to Home Assistant; camera monitoring may move to an external system.

## Before you start

Every move is a pure file move with shims, gated by the evals suite, old path deleted before the next move begins. Never combine a move with a behaviour change in one commit.

## Action items

Item 5, 2026-09-20, **default reverted**: the migration, the CLI and the eval stand; the default does not. The first live boot on SQLite migrated cleanly (9.1 MB, 12,460 events), wrote for four minutes and then spun its main thread at 100% CPU with no I/O, ignoring SIGTERM. Whether SQLite caused the spin or merely exposed one is not established. Before trying again the eval needs a case that RUNS a session rather than booting and exiting. The original note follows.

Done 2026-09-20 (item 5): `[ledger] backend = "sqlite"` is the default. Its eval is `python -m simorgh.evals run ledger` (free): migration round trip on a copy of the live ledger, boot time both backends, append latency, resume after SIGKILL. On the live copy: 1,717 streams / 12,460 events / 411 blobs with nothing lost, boot 0.39 s vs 0.37 s, append p95 0.08 ms, 50 acked before the kill and all 50 present after. `simorgh/ledger/migrate.py` + `tools/ledger_migrate.py` go both ways with seqs preserved (a corrupt line stays a gap; `append` would have renumbered). The flip carries its own safety net: the live `simorgh.toml` names no backend, so `make_backend` imports a JSONL ledger once when it opens SQLite where only JSONL exists -- without that the new default would have booted Sim against an empty database. Not migrated: snapshots (caches, rebuilt). Known gap: the SQLite blob table has no sweep yet.

Done 2026-09-20 (item 1): `simorgh/execution/{knowledge,pim,security,home,energy,media}/` -> `simorgh/domains/`, registered through `extra_tools` (an entry may be a `(config, secrets=) -> list` factory, since the scoped secrets only exist at `start()`). Tool set unchanged (pinned together in `test_registers_exactly_the_scoped_set`); the boundary test holds because the two things the domains needed from Execution -- `looks_like_credential_path` and the pdf/doc/html converters -- moved to `contracts/pathnames.py` and `contracts/text/`; `simorgh/domains/` is not Guardian-protected and `simorgh/execution/` still is (pinned in `test_protected_subjects.py`). Execution: 22,265 -> 10,973 lines. Not done in this item: `execution/vision.py` and the camera watchers stay until item 4.

Done 2026-09-19 (item 9): `docs/adding-capability.md` -- a new capability arrives as an MCP server with its own schemas, configured by a person and gated by Guardian; a tool class is for the machine itself, the safety mechanism, and things with no external service behind them. The next integration is the acceptance test.

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
Started 2026-09-20 (item 11): `stage9/the-house-does-an-ordinary-thing` -- an owner asks for the kitchen light, the lamp is on, and then it goes back off through the same path. The first breadth scenario that could exist, because the fake house was only wired into the sandbox that day; before it, a tool that quietly refused and a tool that worked produced the same green. Verified by unwiring the house and watching it go red. Grown 2026-09-20: `stage9/a-lamp-is-not-a-decision` and `stage9/a-siren-is-a-decision` -- the same generic `homeassistant.turn_*` service, parting company at the gate. They exist because the creator typed `home off family room` and was asked to approve turning a lamp off: the shorthand commands use the generic service precisely because it works on anything, which left the policy unable to tell a lamp from a lock. Cautious is not free -- a gate that fires on lamps is a gate people learn to click through, and then the gate on the front door does not work either -- so the suite now pins BOTH directions, with `nobody_was_asked()` as the half that had no expectation at all. Falsified by unresolving the generic domain: 1/3. The rest of the item (the TV, a reminder, mail, a camera snapshot) grows the same way, one integration at a time. Grown 2026-09-21 (`793687d`): the first scenarios that TYPE -- `stage9/the-console-answers` (the commands a person uses all day) and `stage9/a-mistyped-command-is-answered-kindly` (usage, not a stack trace) -- because every house bug the creator found on 2026-09-20 he found by typing, and none of the pack's 51 direct-address beats typed anything.

11. **The household end-to-end suite** in `simorgh/evals/household/` grows with every integration; "more general" is its coverage number (evaluation section 11).

## Measurements after

| Number | Target | Measured 2026-09-20 |
|---|---|---|
| Lines in `simorgh/execution/` | under 8,000 | **11,093** (was 22,265 before item 1; the remaining overshoot is `vision.py` and the camera watchers, which item 4 moves to `perception/`) |
| `dispatch.py` lines | under 600 | **2,496** -- item 3 has not started, and `home`/`light`/`people` added to it on 2026-09-20 |
| Household suite coverage (goals completed end to end) | rising per release | 13 scenarios, 3 of them stage 9 (the ordinary thing, the lamp, the siren) |
| Camera announcements about the event, not the scene | > 90% | not measured; needs item 8's tracked-object events |

Taken rather than estimated, because two of these move in the wrong direction when nobody looks: `dispatch.py` grew by three command families the same week its target was written, and `execution/` reads as nearly done at 11k when half the remaining overshoot is one file item 4 has not moved yet.

## Risks and mitigations

- Half-migration: one move per commit, shims deleted before the next, evals after each.
- Hardware dependencies (HA box, Frigate) are the creator's call; nothing in stages 0-8 waits on them.

## Definition of done

- [ ] Items 1-5 landed with shims removed; every CONTRACT.md moved with its module.
- [ ] Items 7-11 as the creator's hardware decisions allow, each with a findings entry.

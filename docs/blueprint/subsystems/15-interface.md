# 15 — Interface (`simorgh/interface/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md` (principles), `02-system-architecture.md`
> (position and flows), `03-contracts-and-messaging.md` (envelope, topics,
> delivery semantics, protocols). A spec may refine those documents; it
> may not contradict them. If you find a contradiction, fix the governing
> document and note it in `00-README.md`'s changelog.

**Layer:** 4 Self & surfaces
**Owner (build):** built (Phase 1 Track C)
**Status:** partial -- see §12 for what did not land this session
**Depends on (contracts only):** `ui.notice`, `ui.prompt`, `ui.rendered`, `system.*`, `task.*`, `plan.*`, `action.needs_human`, `action.denied`, `persona.state.changed`, `memory.stored`, `learn.*`, `cognition.provider.status`, `turn.completed` (see §12 Q1), `research.finding.recorded`, `curiosity.interest.updated`
**v1 code that migrates here:** `src/main.py` (`run_cli`, `_run_cli_loop`, banner, `_COMMANDS_HELP`, `autocorrect_command`, `strip_command_slash`, `extract_*_args`, `_print_tasks`, `_print_pending`, `_print_vitals`/`_vitals_snapshot`, `VitalsMonitor`, `_print_autonomous_digest`, `_run_shell_passthrough`, readline history), `src/orchestrator/console_style.py`, `src/orchestrator/activity_log.py` (viewing side), `src/orchestrator/autonomy.py` (`ActionDigest` rendering)

## 1. Purpose and responsibilities

Interface is every surface a human touches: the terminal REPL, the
HTTP/WebSocket API, notifications, and the read-only views (vitals,
tasks, digest, log, trace). It speaks *only* the bus. It is where several
subsystems' outputs are reconciled into one coherent, honest response
(`AGI-04` §11): the floor is reported as the floor, insufficient evidence
as insufficient evidence, a guessed command as a guess. It is also the
human's hand on the wheel — interrupt, steer, approve, pause, stop —
which `harness-01` names as the first human need (decision authority).

**Responsibilities (owns):**
- The CLI REPL and its command grammar (every v1 command preserved or explicitly mapped).
- Rendering: colors, code/diff blocks, checklists, live tickers, vitals, digests — as scrolling blocks only.
- Human-in-the-loop prompts (`ui.prompt` → answer), with timeouts and defaults.
- Interrupt and steer (Esc / Ctrl-C / typed correction) → `system.pause` (scoped) or `task.paused` or `steer=true` percepts.
- The HTTP/WebSocket API (Phase 5) mirroring the CLI, with an auth token.
- Read-only views over Ledger projections: `tasks`, `pending`, `log`, `trace`, `digest`, `history`, `budget`, `skills`, `interests`.
- The `!<command>` shell passthrough — the human's own shell authority, run by Interface itself, never via the action path (v1 design, kept).

**Explicit non-responsibilities (belongs elsewhere):**
- Deciding anything: no command is executed here; each becomes a message. The only local execution is `!shell` (human authority) and rendering.
- Persona state or voice (Persona), turn logic (Orchestration), task state (Planning), approvals (Guardian).

**Principles this subsystem is the primary enforcer of:** 4.12 transparency (every autonomous action is announced; guesses are announced); 4.5 honest floors in what the human reads; `harness-01` "human decision authority" (interrupt, approve, audit).

## 2. Position in the architecture

Layer 4. Participates in Flows 1 (percept in, render out), 2/3 (progress notices, approval prompts, plan display), 4 (growth notices), 5 (pause/stop originate here), 7 (status after restart), 9 (announcing discovered candidates). Interface is the only subsystem besides Kernel allowed to publish `system.pause/resume/stop` (`03` §3). Imports: contracts, bus/ledger clients, stdlib (`readline`, `asyncio`, `http.server`/`asyncio` streams for the API — no third-party web framework in the core).

## 3. Interfaces

### 3.1 Messages consumed
| Type | Pattern | Semantics | What this subsystem does with it |
|---|---|---|---|
| `ui.notice` | event | Render as a block, colored by `level`; queue while the user is mid-line, flush at the next prompt |
| `ui.prompt` | command (group `interface`) | Show question + options; collect answer or apply default on timeout; emit `ui.prompt.answered` |
| `ui.rendered` | event | (API) stream to connected clients |
| `action.needs_human` | event | Same as a prompt, prefixed with the action summary; answer → `ui.prompt.answered{prompt_id=action_id}` |
| `action.denied` | event | Render a one-line 🚫 with `layer` and reasons (transparency) |
| `task.*`, `plan.*`, `project.*` | events | Progress lines (`🏗️ [autonomous] …`), plan checklists, rollups; feed the `tasks` view |
| `system.state.changed`, `system.health`, `system.metrics` | events | Status line; vitals gauges |
| `persona.state.changed` | event | Vitals gauges |
| `memory.stored`, `learn.*`, `curiosity.interest.updated`, `cognition.provider.status` | events | Vitals counters; `budget` view |
| `research.finding.recorded` | event | Render the finding summary |
| `system.status.reply`, `*.reply` | replies | For view commands |

### 3.2 Messages produced
| Type | Semantics | Payload | Consumers |
|---|---|---|---|
| `percept.text.received` | event | `{channel, text, user_id?, session_id, steer: bool}` | orchestration, persona, memory |
| `intent.goal.stated` | event | `{goal, origin: human, priority, constraints?, wants_project}` | planning |
| `task.created` (via request `task.create`) | request | for `research`, `plan`, `work`-style commands — see §3.3 | planning |
| `action.proposed` | event | for `fetch`, `run`, `use`, `remind`, `patch`, `propose` (see command table) | guardian |
| `system.pause` / `system.resume` / `system.stop` | command (priority 9) | `{reason, requested_by: "cli:<session>", scope: all|autonomous}` | kernel |
| `ui.prompt.answered` | event | `{prompt_id, answer, answered_by, timed_out: bool}` | the prompt's source |
| `ui.rendered` | event | `{channel, text}` (API mirror of what the terminal showed) | api clients |
| `system.status.request`, `memory.retrieve` (for `history`), ledger reads | requests | views | kernel, memory |

### 3.3 Command table (every v1 command → v2 message)

| v1 command | v2 message(s) | Notes |
|---|---|---|
| `<free text>` | `percept.text.received{channel:cli}` | Flow 1; Orchestration opens a turn |
| `reflect` | `reflect.review.request` → `.reply` (Reflection) | rendered as the v1 proposal list |
| `propose <topic>` / `improve <topic>` | `task.create{kind:skill, description, origin:human, mode:execute}` then `task.available` is worked immediately by a Worker (Interface passes `immediate:true`) | same gates as v1 `propose_skill` |
| `patch <path> <desc>` | `task.create{kind:patch, subject, mode:execute, immediate:true}` | Flow 4 via Learning/Orchestration; relaunch handled by Execution tool |
| `batch <n> <theme>` | `intent.goal.stated{goal, wants_project:false, constraints:{count:n, kind:skill}}` | Planning creates n skill tasks; Interface renders the checklist from `task.*` events |
| `plan <n> <goal>` | `task.create{kind:project, mode:plan, immediate:true}` | Flow 3: plan artifact, then children; replaces v1's parent-`SKILL_TASK` shape |
| `evolve <n> <goal>` | `intent.goal.stated{goal, wants_project:true, constraints:{count:n, kind:patch, batch_revert:true}}` | Planning + Learning; one revert-range on batch self-check failure |
| `research <topic>` | `task.create{kind:research, immediate:true}` | Flow 6 |
| `project <goal>` | `task.create{kind:project, mode:plan, immediate:true}` | Flow 3 |
| `discover` | `curiosity.discover.request` → reply | renders new tasks |
| `tasks` | Ledger projection read (`task:*` via Planning `task.list.request`) | project rows show rollup + indented children |
| `work` | `task.work_next.request` (Planning picks; Worker runs) | |
| `autonomous on\|off\|status` | `system.resume{scope:autonomous}` / `system.pause{scope:autonomous}` / `system.status.request` | status shows gate, streak, trust posture |
| `digest` | Ledger read of `learn.outcome.recorded` + `task.*` over 24 h | port `ActionDigest` rendering |
| `news` / `growth` | `curiosity.share.request{kind}` → Persona pacing bypassed (explicit ask) → `ui.notice` | |
| `pending [path] [--full]` | Ledger read of `learn.self_patch.applied`/`learn.skill.acquired` + blob refs; diff rendering | |
| `skills` / `use <name>` | `world.env.query{what:tools, filter:skill}` / `action.proposed{tool:"skill.run", args:{name}}` | `use` goes through Guardian like any action |
| `log [last]` / `trace <id>` | Ledger `activity`/`trace:*` reads | new: `trace` prints the causal tree |
| `fetch <url>` | `action.proposed{tool:web_fetch, reversibility:read_only, scope:{network:true}}` | |
| `interest <topic>` / `interests` / `curious` | `curiosity.interest.add` / `.list.request` / `.follow_up.request` | |
| `sleep` | `system.tick.sleep{window_seconds}` (Kernel-forwarded on request) | Flow 8 |
| `history` | `memory.retrieve{kinds:[working], k}` | |
| `run <code>` | `action.proposed{tool:run_python_sandboxed, args:{code}, reversibility:read_only}` | sandboxed; Guardian may still deny |
| `budget` | `cognition.provider.status` cache + `guardian.posture.request` | |
| `vitals` / `vitals on\|off` | local projection; `on` reprints while idle (no cursor control) | milestone 94 rule |
| `remind <dur> <msg>` | `percept.time.schedule.request` (Kernel scheduler) | fires `percept.time.scheduled` → notice |
| `!<shell>` | executed locally by Interface with inherited stdio | human's own authority; logged as `activity` |
| `exit` / `quit` | `system.stop{reason:"user exit"}` | |

Argument extraction (`extract_*_args`) and usage messages port unchanged. A leading `/` is optional. `autocorrect_command` ports as-is: near-miss first words are corrected *and announced* (`[guessing 'porpose' -> 'propose']`), never silently.

### 3.4 Python protocol (`api.py`)
```python
class Renderer(Protocol):
    def notice(self, level: str, text: str, source: str) -> str
    def code_block(self, code: str, *, label: str, max_lines: int = 30) -> str
    def diff_block(self, lines: list[str], *, label: str, max_lines: int = 60) -> str
    def checklist(self, items: list[tuple[str, str]], title: str = "") -> str
    def vitals(self, snapshot: VitalsSnapshot) -> str
    def tasks(self, rows: list[TaskRow]) -> str

class CommandParser(Protocol):
    def parse(self, line: str) -> Command | None      # Command(name, args, raw, guessed_from: str | None)

class Surface(Protocol):                                # CLI and API implement this
    async def run(self) -> None
    async def show(self, text: str) -> None
    async def ask(self, prompt: Prompt) -> Answer       # Prompt(id, question, options, default, timeout_s)

@dataclass(frozen=True)
class VitalsSnapshot:
    mood: float; energy: float; load: float; memory_records: int; skills: int; interests: int
    backlog: int; posture: str; budget: dict[str, dict]; mood_phrase: str
```

### 3.5 Configuration
`simorgh.toml [interface]`

| Key | Type | Default | Controls |
|---|---|---|---|
| `history_path` | path | `~/.simorgh/cli_history` | readline history (v1) |
| `history_length` | int | 1000 | |
| `color` | auto\|on\|off | auto | `NO_COLOR` honored |
| `prompt_timeout_s` | float | 120 | default for `ui.prompt` without its own timeout |
| `vitals.idle_reprint_s` | float | 3.0 | v1 `DEFAULT_VITALS_IDLE_SECONDS` |
| `vitals.interval_s` | float | 15.0 | reprint cadence when `vitals on` |
| `notice.queue_max` | int | 200 | notices held while user is typing |
| `shell.timeout_s` | float | 120 | `!` passthrough |
| `api.enabled` / `api.host` / `api.port` | bool/str/int | false / 127.0.0.1 / 8765 | Phase 5 |
| `api.token_env` | str | `SIMORGH_API_TOKEN` | bearer token source |
| `api.stream_topics` | list | `["ui.*", "task.*", "plan.*", "system.state.changed"]` | what the WebSocket streams |

## 4. Data model and Ledger streams

Interface appends: `activity` stream events `command.entered{raw, parsed, guessed_from}`, `shell.run{command, exit}`, `prompt.shown{prompt_id, question}`, `prompt.answered`. It owns no other truth. Views are projections computed on demand from Planning/Ledger reads; the vitals snapshot is an in-memory cache updated from events (rebuilt on start from the latest `persona:state` snapshot and a `system.status.request`). Readline history is a plain file (not Ledger) by design — it is the terminal's, not the system's.

## 5. Internal design

```
service.py
 ├─ cli/
 │   ├─ repl.py        readline loop in a thread (blocking input) ↔ asyncio via a queue; prompt "> "
 │   ├─ parser.py      strip slash, autocorrect, extract_*_args (ported), command table dispatch → messages
 │   ├─ render.py      console_style port: style(), code/diff blocks, checklist, LiveTicker (new-line ticks only)
 │   ├─ views.py       tasks, pending, log, trace, digest, history, budget, skills, interests
 │   ├─ vitals.py      snapshot cache + render; idle reprint loop (scrolling block, never cursor control)
 │   └─ prompts.py     ui.prompt handling, timeouts, defaults, needs_human rendering
 ├─ api/ (Phase 5)
 │   ├─ http.py        stdlib http.server on asyncio: POST /message, /command, GET /status, /tasks, /trace/{id}
 │   └─ ws.py          websocket (stdlib-only minimal RFC6455 impl) streaming ui.*/task.*/plan.*
 └─ notify.py          desktop/terminal bell hooks; API push
```

Input/output arbitration: notices arriving while the user is mid-line are queued and flushed *before* the next prompt is printed (v1 "print a fresh block between `input()` calls" rule). The REPL thread only ever calls `print` between inputs; `LiveTicker` prints new lines at intervals, never `\r` redraws (milestone 53/94).

Interrupt/steer state machine:
```
idle ─(Ctrl-C at prompt)───────▶ confirm exit? (no → idle; yes → system.stop)
busy ─(Esc or Ctrl-C)──────────▶ system.pause{scope:all, reason:"user interrupt"} → show "paused; type to steer, 'resume' to continue"
paused ─(typed text)───────────▶ percept.text.received{steer:true} + system.resume
paused ─('resume')─────────────▶ system.resume
busy ─(typed text, no interrupt)▶ percept.text.received{steer:true}   (queued; Orchestration reads it at its next step)
```

## 6. Key behaviors — worked scenarios

**S1 — A typo'd command.** User types `porpose a unit converter`. Parser: first word not exact, ≥4 chars, `difflib` cutoff 0.75 matches `propose` → prints `[guessing 'porpose' -> 'propose']` → `task.create{kind:skill, description:"a unit converter", immediate:true}` → Planning replies with `task_id` → Worker runs Flow 2 → Interface renders `🔎 drafting… ✅ tests… ✨ [APPLIED]` from `task.step`/`task.completed` events → `📦 committed -- push whenever you're ready`.

**S2 — An approval prompt during a project (Flow 3).** `plan.proposed{risk:high}` → Planning emits `ui.prompt{prompt_id, question:"Approve this 4-step plan?", options:[approve, revise, reject], default:reject, timeout_s:600}`. Interface renders the checklist, waits; user answers `approve` → `ui.prompt.answered`. On timeout → `answered{answer:reject, timed_out:true}` and a notice explaining the default (never silently proceed).

**S3 — Interrupt and steer (Flow 5).** During an autonomous patch the user presses Esc → `system.pause{scope:all}` → Kernel `system.state.changed(paused)` → Interface shows the paused banner. User types "focus on the memory module instead" → `percept.text.received{steer:true}` + `system.resume`. Orchestration reads the steer at its next step and Planning records `plan.revised{reason:"user steer"}`.

**S4 — Failure: the bus is slow / Planning is down.** `tasks` → `task.list.request` times out (2 s) → Interface falls back to a direct Ledger projection read of `task:*` streams and prints it with a dim `(from ledger; planning not responding)` line — never a stack trace, never silence.

**S5 — Vitals while idle.** `vitals on` → every 15 s while idle ≥ 3 s, a fresh vitals block prints (mood/energy/load bars, memory records, skills, interests, backlog, trust posture, budget). Typing suppresses reprints. `vitals off` stops them; bare `vitals` prints once.

## 7. Design considerations and tradeoffs

- **Scrolling blocks, never cursor control.** Milestone 94 (revert of the pinned panel) is a hard rule: raw DECSTBM/cursor sequences fight `readline`. Cost: no fixed dashboard in the terminal. The API/WebSocket surface is where a live dashboard belongs.
- **Commands become messages; `!shell` does not.** `harness-01` reversibility-weighted oversight and human decision authority: a human's own shell command is their authority, not the system's action, so it bypasses Guardian by design (v1 design preserved). Everything the *system* would do goes through the action path.
- **Prompts with defaults and timeouts.** `harness-04`: silence must not become success; a timed-out approval defaults to the safe option and says so.
- **Interrupt at the harness level.** `harness-03` §5 (interrupt/steer is a cheap always-on circuit breaker) and `harness-01` Esc/steer. Implemented via `system.pause` (structural: Guardian denies) rather than a flag the model is asked to respect.
- **stdlib HTTP/WS.** `01` §4.14 stdlib core. Cost: a minimal WebSocket implementation is real work; it is Phase 5 and optional (`api.enabled=false` by default).
- **Views read projections, not subsystem internals.** Keeps Interface swappable and lets the API and CLI share one view layer.

## 8. Safety, degradation, and failure modes

- Provider down: Interface shows `[cognition: floor]` notices; nothing else changes.
- Malformed inbound events: dropped with a dim `[render error]` line; never crash the REPL.
- Handler crash: the REPL thread survives; Kernel restarts the async side; queued notices flush.
- Restart: history file reloads; vitals rebuild from status request; unanswered prompts are re-shown if their `ui.prompt` is still within timeout (Ledger `prompt.shown` without `prompt.answered`).
- Duplicates: `ui.prompt` with a known `prompt_id` is not re-shown.
- Ledger unavailable: views say so; commands still publish.
- Corrigibility: `system.stop` is honored immediately even mid-render; Interface is the human's channel for pause/stop and must never be the thing that blocks it — the REPL thread handles Ctrl-C synchronously.
- API: bearer token required; binds to loopback by default; no command bypasses Guardian.

## 9. Testing strategy

- Contract tests for every produced type; handler tests for `ui.prompt` (valid/invalid/timeout), `action.needs_human`, `task.*` rendering.
- Unit: parser (every command in §3.3 maps to the right message; usage on bad args; autocorrect announces; `/` optional; `!` passthrough); renderer (color off under `NO_COLOR`, block truncation, diff coloring, checklist icons); vitals snapshot math; prompt timeout/default; interrupt state machine.
- Integration: `test_flow_1_cli_turn.py` (text in → render out via memory bus with a fake Orchestration); `test_flow_5_interrupt_and_steer.py`; `test_prompt_timeout_defaults_safe.py`; `test_views_fall_back_to_ledger.py`.
- E2E: port `tests/test_e2e_cli.py` — spawn `python -m simorgh run` with piped stdin against an isolated data dir; assert banner, every command runs cleanly on the deterministic floor, `exit` returns 0.
- Never cursor-control: a test greps rendered output for `\x1b[` sequences other than SGR colors.

## 10. Build steps (an agent picks this up here)

1. Skeleton; `Surface`/`Renderer` protocols; `render.py` ported from `console_style.py` with tests. *(S)*
2. `repl.py` thread↔asyncio bridge; `percept.text.received`; `ui.notice` queue/flush; E2E banner test. *(S)*
3. `parser.py`: port autocorrect/extractors; command table → messages; one test per command. *(M)*
4. `prompts.py`: `ui.prompt`/`action.needs_human`, timeouts, defaults; interrupt/steer state machine → `system.pause/resume`. *(S)*
5. `views.py` + `vitals.py`: projections and fallbacks; `vitals on/off` idle reprint; digest port. *(M)*
6. Failure modes; E2E suite port; README; `EVOLUTION.md` milestone. *(S)*
7. Phase 5: `api/http.py`, `api/ws.py`, token auth, streaming; API tests. *(M)*

Parallelizable: 3, 4, 5 after 2. Size: **M** (+M for Phase 5).

## 11. Migration notes

- `run_cli`/`_run_cli_loop` dissolve into `repl.py` + `parser.py`; every `if lowered == X:` branch becomes a table row. `src/main.py` keeps a `run_cli()` adapter that starts the Kernel with the Interface until cutover.
- `console_style.py` → `render.py` (unchanged semantics; `LiveTicker` kept).
- `VitalsMonitor` → `vitals.py` (the milestone-88 one-shot + `on/off` reprint; no pin).
- `ActionDigest` rendering → `views.py`; the counting moves to a Ledger projection.
- `activity_log.py` viewing (`log`, `log last`) → `views.py`; writing is Ledger `activity`.
- E2E tests port with new spawn command.

## 12. Open questions

1. `turn.completed` is used in `02` Flow 1 but absent from the `03` §4 catalog. **Default:** add `turn.completed{session_id, task_id, text, floor: bool, verification_ref?}` under `task.*` (contracts change per `05` §6). **Resolved by build:** `turn.completed` is in the live catalog (`simorgh/contracts/messages/task.py`) as of this session and is wired for real (§6 plain-chat flow, tested end-to-end in `tests/simorgh/integration/test_worldmodel_persona_interface_flow.py`).
2. `task.create` request and `*.request` view types (`task.list.request`, `curiosity.discover.request`, `reflect.review.request`, `percept.time.schedule.request`) are not in the catalog. **Default:** add them as request/reply pairs; until then Interface may publish `task.created` directly for `immediate` commands. **Resolved by build, except one:** `task.create`, `task.list.request`, `curiosity.discover.request`, and `reflect.review.request` are all in the live catalog and wired in `dispatch.py`. **Genuine remaining gap:** `percept.time.schedule.request` is still absent from the catalog -- `remind` has no message to send and this build says so honestly (`not yet available in this build`) rather than inventing one.
3. Should `!shell` output be captured into the Ledger? **Default:** command line and exit code only (stdout is the human's). **Not built this session:** `!shell` runs for real (human authority, local `subprocess.run`) but neither the command line nor its exit code is appended to the `activity` Ledger stream yet -- this build's `dispatch.run_shell` returns output to the terminal only.

4. **The REPL's shape is now a decision, not an accident (post-cutover review, 2026-09-06 — `07-post-cutover-review.md` §3.6).** The loop needed four separate live-caught fixes in one day of real use (`EVOLUTION.md` 104, 124, 126, 127: unthreaded timeout default; fire-and-forget dispatch; subprocesses inheriting the terminal's stdin; no `readline`). Each fix was correct; the pattern says the loop shipped without ever being driven from a real terminal. **Accepted design:** a blocking `input()` on a dedicated thread, bridged into asyncio with `run_coroutine_threadsafe(...).result()` so the next prompt can never race ahead of the reply it belongs after; `readline` imported for line editing and history at `<data_dir>/interface/cli_history`. **Known limitation, named:** Ctrl-C during a pending reply is caught only around `input()`; it reaches the main thread's `asyncio.run` in `kernel/cli.py` with no handler and most likely exits abruptly instead of publishing `system.stop`. `pause`/`exit` are the supported interrupts. *Follow-up:* catch `KeyboardInterrupt` around `asyncio.run`, publish `system.stop`, exit 0. **Test requirement (new):** a pty-driven REPL test (`pty` module, no new dependency) for prompt/reply ordering, arrow keys, Ctrl-C mid-turn, and the banner's unicode modes — pipes are never terminals, and four of the four bugs above only exist on a terminal.

5. **Command surface: consolidate 38 inherited names down to ~11 (creator's decision, 2026-09-06 — `07-post-cutover-review.md` §3.8).** `COMMAND_NAMES` is v1's whole history, not a design: many near-duplicates, five honest `_NOT_YET` stubs, and several that the dashboard or the model's own Guardian-gated tools now cover better. **Keep** (verbs a human actually needs at the prompt): `status` (health + vitals + posture + provider budget in one panel — absorbs `vitals`, `budget`, `skills`), `tasks` (list; `tasks work` advances the next — absorbs `work`), `improve` (one self-change entry: `improve <path> <description>` → patch task; `improve <topic>` → skill task — absorbs `propose`, `patch`, `batch`, `evolve`), `plan <goal>` (a goal into tracked steps, plan mode — absorbs `project`, `plan <n>`), `research <topic>`, `interests [<topic>]` (list, or add — absorbs `interest`, `curious`), `auto [on|off|now]` (the idle loop; `now` runs one tick — absorbs `autonomous`, `discover`, `news`, `growth`), `pause`, `resume`, `exit` (stops the Kernel and leaves — absorbs `stop`, `quit`), `help`. Plain text stays the primary way to talk; `/` stays optional; `!<shell>` stays. **Remove:** `reflect`, `digest`, `pending`, `log`, `trace` (dashboard/`python -m simorgh trace` cover these; four were stubs), `remind` (no contract), `history` (readline has it), `run`, `use`, `fetch` (the model reaches sandbox/skills/web through Guardian-gated tools; a human forcing them is a dev path, not a user one — `!<shell>` remains for the human's own authority). Autocorrect keeps working against the smaller set. Acceptance: `help` lists ≤ 12 names; every kept name does something real; `tests/simorgh/interface/test_parser.py` and `test_service.py` updated; the banner's "where to start" list is a subset of `help`.

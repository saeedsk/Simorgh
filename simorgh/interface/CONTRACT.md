# interface -- contract

One-line status: layer 5 · 10,788 lines · 31 test files · lock: `interface` in docs/modules/locks.toml

## Purpose

Interface owns every typed or remote surface a person uses: the terminal REPL/TUI and its rendering, the operator command grammar and dispatch (`status`, `tasks`, `tool`, `voice ...`, `mcp`, `skills`, `restart`, ...), the local HTTP server (chat, dashboard, TV page, phone remote, webhooks), and the Telegram and WhatsApp channels. A conversational line becomes `percept.text.received` and the reply comes back as `turn.completed` keyed by `session_id`; Interface never calls a model and never runs a tool except by publishing `action.proposed` for Guardian to decide (`dispatch.py::_run_tool`). It is one of the few publishers allowed to pause, stop, resume, restart and reload the system (`PUBLISH_ONLY_BY`), so everything that reaches `dispatch` from outside a person's keyboard (the model's `sim_command` via `ui.command.request`, the HTTP routes, the channels) is a trust boundary. The shaping decision: one `dispatch()` function serves every surface, so a command is implemented once and reached from the REPL, `sim_command`, the dashboard and voice alike (S13 is the cost of that reach).

## Files

| File | For |
|---|---|
| `simorgh/interface/__init__.py` | Empty package marker |
| `simorgh/interface/api.py` | Re-exports `Command`, `parse`, `VitalsCache`, `VitalsSnapshot` |
| `simorgh/interface/service.py` | The `Service`: subscriptions, REPL/TUI loop, chat turns, prompts, narration, HTTP and channel startup, `ui.command.request` |
| `simorgh/interface/dispatch.py` | Every operator command: task, system, benchmark, voice, tool, mcp, skills, schedule, config, alerts |
| `simorgh/interface/parser.py` | Command grammar, the one command table, autocorrect |
| `simorgh/interface/httpapi.py` | Stdlib HTTP server: routes, token boundary, chat, TV and dashboard APIs, webhooks, camera media |
| `simorgh/interface/dashfeeds.py` | Dashboard collector: polls weather, markets, news and other web feeds; lists camera stills and relays |
| `simorgh/interface/telegram.py` | Telegram long-poll channel with an allow-list |
| `simorgh/interface/whatsapp.py` | WhatsApp Cloud API webhook channel: signature check and allow-list |
| `simorgh/interface/tui.py` | prompt_toolkit prompt, completion, key bindings |
| `simorgh/interface/panel.py` | The Claude-Code-shaped screen layout (footer, live line, status rows) |
| `simorgh/interface/render.py` | Console styling, width-aware lines, status and domain panels |
| `simorgh/interface/live_status.py` | Redraw-in-place status line |
| `simorgh/interface/activity.py` | Task book and activity feed built from task events |
| `simorgh/interface/vitals.py` | Local projection of mood and metrics for the footer |
| `simorgh/interface/voiceview.py` | Rendering of `voice ...` replies |
| `simorgh/interface/benchmarkview.py` | `benchmark` command parsing and rendering |
| `simorgh/interface/benchmarkchart.py` | Unicode benchmark charts |
| `simorgh/interface/splash_art.py` | Generated splash screens (do not edit by hand) |
| `simorgh/interface/config.py` | `[interface]` dataclass |
| `simorgh/interface/static/` | `dashboard.html`, `dash.html`, `tv.html`, `remote.html`, logo |

## Consumes

Subscriptions are exactly `Service.consumes` (`service.py:111-131`, pinned by `tests/simorgh/test_manifests_match_the_code.py`), except where noted.

| Topic | Schema | Where | Does |
|---|---|---|---|
| `turn.completed` | `messages/task.py::TurnCompleted` | service.py:1511; httpapi.py:680; telegram.py:117; whatsapp.py:116 | Resolves the pending REPL, HTTP, Telegram or WhatsApp turn by `session_id`; feeds the activity view |
| `task.created`, `task.started`, `task.step`, `task.completed`, `task.failed`, `task.blocked` | `messages/task.py` | service.py:1294; httpapi.py:695 | Narration, task book, footer; the dashboard's activity feed |
| `task.cleared` | `messages/task.py::TaskCleared` | service.py:1026 | Drops cleared tasks from the book |
| `ui.notice` | `messages/ui.py::UiNotice` | service.py:1165 | Prints a notice |
| `ui.prompt` | `messages/ui.py::UiPrompt` | service.py `_on_prompt` | Under the TUI it opens an approval picker in the prompt section (`picker.py`, `tui.ask`): the question and its options as bullets, arrows to move, space to mark, Enter to a confirm step that names the ANSWER, Enter again to send. Without the TUI (a pipe, the HTTP API) the banner and a typed matching option still work exactly as before, and the watchdog answers the default at `timeout_s` either way |
| `ui.command.request` | `messages/ui.py::UiCommandRequest` | service.py:780 | Runs one operator command for Sim (`sim_command`, spoken restart) through `parse` + `dispatch`; refuses `!` |
| `action.needs_human` | `messages/action.py::ActionNeedsHuman` | service.py:1236 | Prints the escalation |
| `action.denied`, `action.result` | `messages/action.py` | service.py:1246; httpapi.py:695; dispatch.py:1330 | Prints denials; dashboard activity; transient wait for a `tool` command's own action |
| `persona.state.changed` | `messages/persona.py::PersonaStateChanged` | service.py:1250 | Mood into vitals |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | service.py:1253 | Tracks paused/stopping so chat is refused instead of hanging |
| `system.metrics` | `messages/system.py::SystemMetrics` | service.py:1269 | Vitals |
| `system.health` | `messages/system.py::SystemHealth` | declared only | Nothing subscribes (see Known issues) |
| `guardian.posture.changed` | `messages/guardian.py::GuardianPostureChanged` | service.py:1272 | Posture in the footer |
| `cognition.provider.status` | `messages/cognition.py::CognitionProviderStatus` | service.py:1263 | Provider line |
| `percept.time.scheduled` | `messages/percept.py::PerceptTimeScheduled` | service.py:1184 | Prints a fired reminder |
| `benchmark.progress` | `messages/benchmark.py::BenchmarkProgress` | service.py:1178 | Narrates scored cases |
| `voice.transcript`, `voice.spoken`, `voice.listening` | `messages/voice.py` | service.py:1038, 1135, 1158 | Shows what was heard (one line rewritten in place), said, and the floor state |
| `ui.tv.state`, `ui.tv.speech` | `messages/ui.py` | httpapi.py:681-682 | Serves the TV page's state and speech queue |
| `ui.dash.state`, `ui.dash.key` | `messages/ui.py` | httpapi.py:683-684 | Dashboard state and remote keys for the page |
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | httpapi.py:695-698 | Dashboard activity feed. Subscribed in a loop when HTTP starts; declared in `Service.consumes` since 618191e |

Replies received by request/reply: `task.list.reply`, `task.create.reply`, `system.status.reply`, `guardian.posture.reply`, `benchmark.*.reply`, `voice.*.reply`, `world.env.query.reply`, `curiosity.interest.list.reply`.

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | service.py:967; httpapi.py:1153; telegram.py:207; whatsapp.py:203 | A chat line: `channel` `cli`, `http`, `telegram` or `whatsapp`; a fresh uuid per CLI line, client-chosen over HTTP, one per chat in memory for Telegram and WhatsApp |
| `system.pause`, `system.stop`, `system.resume`, `system.restart` | `messages/system.py` | dispatch.py:193-235, 345-349; service.py:669-695 | Operator commands, Ctrl-C (pause), REPL exit (stop), `restart` (typed, `sim_command` or spoken) |
| `action.proposed` | `messages/action.py::ActionProposed` | dispatch.py:1333 | The `tool` command and dashboard page actions (`cam_stream`, `cast_play`, `ring_live`) via `_run_tool`; `proposed_by = interface:<session>` |
| `task.create`, `task.cancel`, `task.list.request`, `task.clear.request`, `task.work_next.request` | `messages/task.py` | dispatch.py | Task commands (`research`, `patch`, `plan`, `cancel`, `tasks`, `clear`, `next`) |
| `ui.command.reply` | `messages/ui.py::UiCommandReply` | service.py:799-803 | Reply to every `ui.command.request` |
| `ui.prompt.answered` | `messages/ui.py::UiPromptAnswered` | service.py:1231 | A prompt answered by the person or by the watchdog default |
| `ui.dash.state` | `messages/ui.py::DashState` | httpapi.py:341 | `POST /api/dash/state` (phone remote) |
| `ui.hook.received` | `messages/ui.py::UiHookReceived` | httpapi.py:504 | `POST /api/hooks/<name>` |
| `guardian.posture.request` | `messages/guardian.py` | service.py:1288 | Seeding the footer at start |
| `system.status.request` | `messages/system.py` | dispatch.py; httpapi.py:1028 | `status` and `/api/status` |
| `system.schedule.add`, `system.schedule.cancel`, `system.tick.idle` | `messages/system.py` | dispatch.py:749, 814, 353 | `schedule`, `remind`, `idle` commands |
| `benchmark.run.request`, `.history`, `.suites`, `.load`, `.stop` | `messages/benchmark.py` | dispatch.py; httpapi.py:1013 | `benchmark` command and `/api/benchmarks` |
| `voice.status|control|speak|listen|voices|devices|models|bench.request` | `messages/voice.py` | dispatch.py | `voice ...` commands. `voice calibrate [name] [aloud] [short] [en|fa] [room=..] [distance=..]` and `voice calibrate status|stop|keep|accept|skip|apply [name]` send `voice.control.request{action: "calibrate", value: "<verb> [options]", name?}` (its own action since 2026-09-22) |
| `curiosity.interest.add`, `curiosity.interest.list.request` | `messages/curiosity.py` | dispatch.py:366-368 | `interest` command |
| `world.env.query` | `messages/world.py::WorldEnvQuery` | dispatch.py:664, 1652 | `status` and tool listing |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `mcp:proposals` | dispatch.py:57 (read, append on approve/reject) | execution (writes proposals) | forever |
| `skills:installs` | dispatch.py:60 (append) | - | forever |
| `capabilities` | dispatch.py:63 (read) | execution, voice write it | forever |
| `schedule` | dispatch.py:65 (read) | kernel scheduler writes it | forever |
| `execution:tools` | dispatch.py:68 (read for `tool`) | execution writes it | 30d |
| `reflection:alerts` | dispatch.py:69 (read for `alerts`) | growth's monitors part writes it (the stream kept its pre-merge name) | 90d |
| `config:effective` | dispatch.py:71 (read for `config`) | kernel writes it | forever |
| `metrics:history` | config.py `history_stream`; httpapi `/api/history` (read) | kernel writes it | 7d |
| any stream | httpapi `/api/logs`, `/api/streams` (read, token-gated) | - | per stream |

The generated `class:*`, `budget:`, `caldav:`, `imap:`, `cli:`, `interface:`, `connector:`, `hearing:`, `im:*` and `task:{client_session_id}` rows were style classes, prompt text, secret names and validation strings, not streams. Files: camera stills and HLS under `workspace/cameras` (read only), the readline history under `data_dir/cli_history`, and `~/.simorgh/skills` (written by `skills install`).

## Config

`[interface]` in simorgh.toml; dataclass in `simorgh/interface/config.py`. Secrets read from `ctx.secrets`, not config: `SIM_API_TOKEN`, `SIM_TELEGRAM_TOKEN`, `SIM_WHATSAPP_TOKEN`, `SIM_WHATSAPP_PHONE_ID`, `SIM_WHATSAPP_VERIFY_TOKEN`, `SIM_WHATSAPP_APP_SECRET` (service.py:295-370). `kernel/configcheck.py` `KNOWN_DEAD_FIELDS` lists the four unread keys below (`prompt_timeout_s`, `vitals_idle_reprint_s`, `vitals_interval_s`, `notice_queue_max`).

| Key | Default | Read in the package |
|---|---|---|
| `history_path` | `None` | yes (via `resolved_history_path`, service.py:517) |
| `history_length` | `1000` | yes |
| `color` | `'auto'` | yes |
| `unicode` | `'auto'` | yes |
| `narrate` | `True` | yes |
| `narrate_autonomous` | `True` | yes |
| `tidy_input` | `True` | yes |
| `narrate_steps` | `True` | yes |
| `narrate_heartbeat_s` | `10.0` | yes |
| `time_marker_minutes` | `15.0` | yes |
| `show_speaker_score` | `True` | yes |
| `boot_wait_s` | `20.0` | yes |
| `rich_prompt` | `True` | yes |
| `live_status` | `'auto'` | yes |
| `prompt_timeout_s` | `120.0` | NO (declared, never read) |
| `vitals_idle_reprint_s` | `3.0` | NO (declared, never read) |
| `vitals_interval_s` | `15.0` | NO (declared, never read) |
| `notice_queue_max` | `200` | NO (declared, never read) |
| `shell_timeout_s` | `120.0` | yes (bounds a typed `!<command>`; `service.py` passes it to `dispatch`. `[execution] shell_timeout_s` is the model's `run_shell`, a different path) |
| `chat_reply_timeout_s` | `420.0` | yes |
| `http_host` | `'127.0.0.1'` | yes (live config: `0.0.0.0`) |
| `http_port` | `8765` | yes |
| `http_status_timeout_s` | `3.0` | yes |
| `http_chat_timeout_s` | `130.0` | yes |
| `api_max_body_bytes` | `1000000` | yes |
| `telegram_allowed` | `()` | yes; a handle the People store links to a person is admitted too (stage 6 item 4) -- a link, never a handle that merely spells a household name |
| `telegram_poll_s` | `25.0` | yes |
| `whatsapp_allowed` | `()` | yes; a number the People store links to a person is admitted too (stage 6 item 4) |
| `whatsapp_api_version` | `'v21.0'` | yes |
| `history_stream` | `'metrics:history'` | yes |
| `history_default_minutes` | `10.0` | yes |
| `history_max_points` | `500` | yes |
| `logs_default_limit` | `100` | yes |
| `logs_max_limit` | `500` | yes |
| `dash_feeds` | `True` | yes |
| `dash_place` | `'San Jose, CA'` | yes |
| `dash_latitude` | `37.34` | yes |
| `dash_longitude` | `-121.89` | yes |
| `dash_watchlist` | `()` | yes |
| `dash_majors` | `()` | yes |
| `dash_cameras_live` | `True` | yes |

## Public Python surface

- `simorgh.interface.service.Service` (`service.py:108`): the Subsystem, built by the Kernel. Constructor flags `run_repl`, `http_enabled`, `wait_for_boot` let tests run it headless.
- `simorgh.interface.api`: `Command`, `parse`, `VitalsCache`, `VitalsSnapshot`, used by the Kernel CLI and tests. `dispatch.dispatch`, `dispatch.Outcome` and `httpapi.HttpApi` are imported by tests; nothing in another package imports this one except the Kernel (the module-boundary test forbids it).
- `HttpApi.register_route(method, path, handler, auth=True, max_body, rate)` is the only way to add a route; `auth=False` is reviewed per route.
- `GET /api/status` and `config.Config.from_mapping` (`http_host`, `http_port`) are also read from outside the process: `simorgh status` (kernel/statusread.py) finds the running instance there, sending `SIM_API_TOKEN` as a bearer token so a gated server answers with the full snapshot, not only `_PUBLIC_STATUS_KEYS`. A reply must stay a JSON object with a `state` key, or the CLI falls back to the ledger. Changing the route, the port keys or that shape changes `simorgh status`.
- Types from `simorgh.contracts`: `topics`, `envelope.Message/Event`, `protocols.Context/Health`, `registry.error_reply_payload`, `settings.config_path` (for `mcp approve`), `channels` (channel names), stream-name validation.
- Module-level mutable state: none beyond constants. Per-instance state that matters: `Service._pending_turns` and `_pending_prompts` (futures keyed by session and prompt id), `TelegramChannel._sessions/_chats` and the WhatsApp equivalents (in memory only, lost on restart), `HttpApi` rate-limit deques and the single in-flight chat.

## Invariants

`people` shows who Sim knows, what they said yes to and what they care about, and is asymmetric on purpose: reading is a `world.env.query`, every CHANGE goes through the `people` TOOL, which is tier 3 and stops for a person. Writing to the store from the terminal would be a back door around the one gate that makes consent mean anything. A person with no permissions renders as `said yes to: nothing` rather than a blank, because nothing is the default a fresh install starts from and an empty space reads as an oversight (stage 10 item 4).

`home` and `light` are sugar over the four `home_*` tools and nothing else: every verb becomes one tool call through `_run_tool`, so it is an `action.proposed` Guardian sees, exactly like the model's own call. `home on|off` uses `homeassistant.turn_on|off` rather than a domain-specific service, because whether Home Assistant filed the kettle under `switch` or `light` is the entity's business and not the typist's -- and `contracts/home/policy.py` resolves that generic domain from the entity, without which every lamp asked for approval (live, 2026-09-20). A bare `home` asks the World Model's `home` facet, not Home Assistant: the first version looked up an entity called "on". `light` is deliberately redundant with `home` (the creator, 2026-09-20): `light on kitchen` and `light kitchen on` both work, a trailing number is brightness, and a bare name is a QUESTION answered with `home_state` -- guessing a toggle there would be the worst possible reading of `light kitchen`.

`panel.tree_end` wraps a long detail under the completion line instead of cutting it: the detail is usually Sim's own answer, and a four-sentence reply came out as one truncated line ending `as she li…` (live, 2026-09-20). A short detail still sits inline, where it reads best. Every physical line is fitted to the terminal.


- Every chat turn is named in the activity feed from its own percept (`_on_percept`), whatever channel it arrived on. The console names its own turn and `voice.transcript` names a spoken one; a Telegram, WhatsApp or HTTP turn had neither and rendered as `⏺ • ? · ? · (no description)` -- for every message the creator had ever sent from his phone, until 2026-09-20. The percept handler only fills a gap: a turn something better already named is left alone.
- A Telegram or WhatsApp turn carries `speaker` when the sender resolves to a household member, so what is said there is remembered under that person. Resolution asks the People store first (`world.env.query{what: "people", args: {identity: "telegram:<handle>"}}`, stage 6 item 4) and falls back to `contracts.channels.person_for` -- so a handle somebody LINKED to Ira shares her one memory namespace, and a handle that simply is a household name still works on a fresh install with no links. An address that matches nobody yields no `speaker`: a handle or phone number must never reach the bus.
1. HTTP token boundary: with `SIM_API_TOKEN` set, every route except the reviewed open list (`_OPEN_ROUTES`: `/`, `/api/status`, `/tv`, `/dash`, `/remote`, `/api/wallpapers`, `/api/dash/data`, `/api/dash/state` GET, `/api/dash/keys`, `/api/dash/banner`, logo, favicon; prefix `/wallpapers/`) needs `Authorization: Bearer <token>` or `?token=`, compared in constant time (`httpapi.py:84-87, 604-620`).
2. Camera routes are never open: `/api/dash/streams`, `/cameras/snap/` and `/tv/hls/` (and `/tv/media/`) require the token like any gated route (`httpapi.py:482, 548-589`).

That poll also calls `contracts/home/live.watching()`: the page being up IS the liveness signal for any open Ring session, so the per-camera keep-alive that used to be a gated action every twenty seconds is gone (2026-09-20).
3. With no token configured, a gated route is served only on a loopback bind; a non-loopback bind serves only the open routes, and the Service logs `http_api_unauthenticated` at start (`httpapi.py:610-616`; `service.py:305-316`).
4. The WhatsApp webhook is `auth=False` because Meta cannot send the bearer token; every POST must carry a valid `X-Hub-Signature-256`, and the allow-list decides who is answered. Telegram starts only with `SIM_TELEGRAM_TOKEN` and WhatsApp only with its token, phone id and verify token plus the HTTP server; both answer only senders on their allow-list (`contracts/channels.allowed()`), and ignore everyone else in silence.
5. Only Interface, the Kernel (and for restart/reload, Execution) may publish `system.pause|stop|resume|restart|reload` (`contracts/topics.py:293-303`); Voice's spoken restart and the model's `sim_command` reach them only through `ui.command.request`.
6. `ui.command.request` refuses a `!` shell line; shell belongs to `run_shell`, which Guardian gates (`service.py:780-833`).
7. `cameras show <name> full` and `ring live <name>` mean the same thing for both brands of camera. A Ring camera has no RTSP, so `cam_stream` cannot relay it and says so; the COMMAND turns that refusal into the other route -- `dash_view{camera}`, which zooms that tile on the dashboard over WebRTC (the page's own `navCamOpen`, what pressing `ok` does). The tool stays truthful and the routing lives in the command, where calling another tool is ordinary; `ring live off` goes back to the wall.
7. `POST /api/command` runs ONE typed line through `_handle_line` -- the keyboard's own path, so Guardian gates every effect behind it exactly as it does at the terminal. It answers only COMMANDS: a line that parses to chat is refused with `not_a_command` and pointed at `/api/chat`, so it never becomes a second, quieter way to talk to Sim. A `!` shell line is refused (`shell_refused`) exactly as `ui.command.request` refuses it: `!` is a raw shell with no Guardian in it, which is fine for hands at a keyboard and is a remote shell over HTTP. It is token-gated like any other `/api` route and echoes `[remote] <line>` on Sim's screen before running, because a command appearing with no visible cause is how a household stops trusting it. `[interface] remote_commands = false` removes the route. It exists because there was no way to reach `restart` or `benchmark run ...` from outside the house (the creator, away, 2026-09-22).
7. Interface never runs a tool directly: the `tool` command and the dashboard's page actions publish `action.proposed` and wait for `action.result|denied` (`dispatch.py:1301-1350`); secret-looking arguments are refused before they reach the ledger.
8. A chat turn is resolved by the `turn.completed` with its own `session_id`; each CLI line gets a fresh id so concurrent turns cannot cross-wire (`service.py:955-969`); a paused or stopping system refuses a chat line instead of waiting `chat_reply_timeout_s`.
9. A pending `ui.prompt` is answered by a typed matching option before any command parsing or chat, and always resolves (the watchdog answers the default at `timeout_s`). Under the TUI it is a picker instead (`interface/picker.py`, the creator 2026-09-20): nothing is preselected, because a picker that opens on "yes" turns a stray Enter into an approval; the confirm step names the answer rather than its position; Escape backs out but never answers and never closes it, since an approval a stray key can dismiss is one that times out to its default with nobody deciding; and `something else…` is always offered, because an approval whose only answers are the ones Guardian thought of is how somebody ends up approving what they half-agree with. The arrows and space are captured only while a picker is up, and a line typed for `something else` is consumed as the answer rather than run as a command.
10. `mcp approve` appends to the config the Kernel reads (`contracts.settings.config_path()`), never to a cwd-relative `simorgh.toml` (B11).

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract interface`.

- `tests/simorgh/interface/test_httpapi_token_boundary.py` -- cameras need the token; a non-loopback bind without a token serves only open routes.
- `tests/simorgh/interface/test_a_command_can_come_from_elsewhere.py` -- `POST /api/command`: the keyboard's own path, chat refused, token required, echoed on screen.
- `tests/simorgh/interface/test_httpapi.py` -- the HTTP server over real sockets: routes, auth, body caps, `/api/chat` and its `turn.completed` wait.
- `tests/simorgh/interface/test_service.py` -- the Service over a real memory bus: subscriptions, chat percept and reply, prompts, narration.
- `tests/simorgh/interface/test_command_request.py` -- `ui.command.request` runs a command and replies; `!` and unknown commands are refused.
- `tests/simorgh/interface/test_tool_command.py` -- the `tool` command goes through `action.proposed` and Guardian.
- `tests/simorgh/interface/test_telegram_channel.py` -- Telegram: allow-list, one session per chat, replies routed back.
- `tests/simorgh/interface/test_whatsapp_channel.py` -- WhatsApp: signature gate, allow-list, replies routed back.
- `tests/simorgh/interface/test_command_table.py` -- one command table feeds the parser, completion and the splash.

## Known issues (2026-09-18 evaluation)

- S15 / V2: camera stills and live HLS served without the token on a `0.0.0.0` bind. Fixed 2026-09-18 for `/api/dash/streams`, `/cameras/snap/`, `/tv/hls|media/` (commit 62318d3); and on 2026-09-19 for `/api/dash/data`, which stays open for the news tiles but withholds cameras, streams, Ring cameras and events without the token (commit 618191e).
- S13 / V9: `sim_command` lets the model run any parsed CLI verb; Guardian sees only the wrapper; `skills install/update/approve/remove` mutate `~/.simorgh/skills` and `git clone` outside the action path. Open (stage 9 item 3). `apply_skill` itself always asks since 2026-09-18 (8fb3d21, Guardian side).
- S14 / V5: `dashfeeds.py` fetches ~14 web endpoints from its own threads, outside Execution and Guardian. Open.
- V3: four session models (CLI uuid per line, HTTP client-chosen, Telegram/WhatsApp in-memory per chat); Telegram and WhatsApp drop the sender after the allow-list. Open (stage 4 item 3, stage 5 item 7).
- V4: manifest disagreed with the code. Fixed 2026-09-18 (b5c2671); two residues remain, see below.
- C8: no conversation across CLI turns. Partly fixed 2026-09-18 (1e486f1): Memory's working window per `conversation_key`; a persistent session is stage 4.
- L7 / W8: the synchronous 420 s chat wait (`chat_reply_timeout_s`) over a 72-tool CHAT profile. Open (Orchestration side).
- T1: the `tool` command labels every proposal `reversible` on the stated assumption that Guardian recomputes the class (`dispatch.py:1336-1338`); per S6 Guardian trusts the label. Open.
- T4 / W3: dashboard WebRTC signalling (`/api/dash/ring/live`) is a Guardian action per keepalive: 85% of action streams. Open (stage 1 item 6).
- B11: `mcp approve` wrote a cwd-relative `simorgh.toml`. Fixed 2026-09-18 (3beb2a5).
- B18: the REPL `!` and `skills` git clone run `subprocess.run` on the loop thread (`dispatch.py:187, 1837-1849`). Open.
- P6: per-turn chat timings exist (`service.py:946-968`) and are never compared run to run. Open.
- Residue of V4: `system.health` is in both `consumes` and `produces` (`service.py:114, 134`) and is neither subscribed nor published; `percept.text.received` is subscribed in `httpapi.py:695-698` and not declared.

## Planned changes (roadmap)

- Stage 1: trace ids kept from the percept through the turn; Ring signalling off the approval path (one `ring_live offer` proposal mints a session token, keepalive and close become HTTP handlers); (`simorgh status` reading `/api/status` instead of booting was done 2026-09-19, kernel/statusread.py.)
- Stage 3: the TUI and `/api/chat` render `session.delta` as it arrives.
- Stage 4: one persistent session per (channel, person); the reply-correlation key stays per message.
- Stage 5: Telegram and WhatsApp resolve the sender and put `speaker` on the percept; typed CLI turns are the owner.
- Stage 6: the People model resolves identity at every edge.
- Stage 9: `cli`, `tui`, `render`, `telegram`, `whatsapp` and the chat/TV routes of `httpapi` move to `channels/`; `dispatch.py` shrinks to an operator-only `admin/` with a declared command registry; commands the model needs become tools with schemas and `sim_command` is limited to restart/pause/mode; camera live view moves to go2rtc.

## Working on this module

Lock it first (`python tools/modlock.py claim interface --by <you> --task "..."`), commit the lock, edit only `simorgh/interface/`, `tests/simorgh/interface/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py interface` before committing; commit subject `interface: <what changed>`.

- Stage 1 item 3 (2026-09-19): `/api/history` reads the telemetry series `metrics.history` from `ctx.telemetry` and falls back to the `metrics:history` ledger stream (older data, or telemetry off). `HttpApi(telemetry=...)`.

- TUI (2026-09-19): every bottom-of-screen row is fitted as a whole to one column less than the terminal (`panel.fit_row` in `flatten`); fitting each fragment on its own made running rows 10-15 columns too wide, and the wrap left trails on every redraw. `narrate_steps` now defaults to false: background tasks print their start and outcome, their steps show only in the live rows.

- `help` lists one line per command, with `· help <name>: N ways` where a command has several; `help all` is the full manual with every word (the default until 2026-09-19, when it had grown to 120 lines).

- `capabilities` and `skills list` render as panels (`render.capabilities_panel`, `render.skills_panel`): a count, sections (Ready / Not available; Installed / Written by Sim), one aligned row each with a coloured dot, cut to the terminal at a word.

- `voice calibrate` (2026-09-22): a script read once and kept forever (voice/calibration.py). The verb is in `dispatch._voice`, `help voice` (`parser.SUBCOMMANDS`), the did-you-mean list and the unknown-verb line (`tests/simorgh/interface/test_voice_calibrate_verb.py`). Nothing new is rendered here: each line to read and each verdict arrive as `ui.notice` (source `voice calibrate`) and each take as `voice.transcript{enrolling}`, both already shown.

- A voice turn's reply is printed at `turn.completed` (channel `voice`), while it is still being spoken; the later `voice.spoken` adds only an interruption note. It used to appear only when playback ended.

- Consumes `session.delta` (stage 3 item 3): the newest reply being written shows as up to four lines above the prompt (`_streaming_rows`), cleared by `reset` and by `turn.completed`; the transcript still gets the finished answer whole.
- `approvals` / `approvals revoke <n>|all` (2026-09-22) send `guardian.standing.request` and render the reply; a pending approval prompt now also accepts `always` / `a` when Guardian offers it.

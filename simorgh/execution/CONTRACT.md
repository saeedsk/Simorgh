# execution -- contract

One-line status: layer 3 · 21,657 lines · 60 test files · lock: `execution` in docs/modules/locks.toml

## Purpose

Execution is the only place a side effect happens: it owns the tool registry (about 100 tools: 42 core tools, six domain subpackages, worktree tools, on-demand `skill:<name>` tools, MCP proxies and external adapters) and runs a tool only in answer to an `action.approved` from Guardian, reporting `action.result` (`service.py:755-938`). It must never run a tool whose approval it has not verified itself: before any dispatch it recomputes the canonical args hash from the proposal Guardian recorded on `action:<id>` and re-checks Guardian's HMAC token, expiry and replay (`verifier.py`, `service.py:759-773`); a failure publishes `action.denied` with `layer="token"` and nothing runs. The shaping decision is "Guardian sees every call": every capability, including device control, video signalling and self-landing, is a Tool behind one approval path, which buys one audit trail at the cost of per-call ceremony (L4, T4). Code tasks edit a per-task git worktree and land on main only through `worktree_land`: rebase, a whole-suite gate re-judged by `simloader.unit_verdict`, then `git merge --ff-only` (`worktree.py:178-251`, `tools.py:1297-1323`). The package is Guardian-protected: Sim's own tasks cannot edit it.

## Files

Core (the part that stays in Execution after stage 9):

| File | For |
|---|---|
| `simorgh/execution/__init__.py` | re-exports `Service` |
| `simorgh/execution/service.py` | `Service`: registry, `_on_approved` dispatch, results, inflight replay, skills, MCP, probes, boot autostarts |
| `simorgh/execution/verifier.py` | `ApprovalVerifier`: args hash, expiry, HMAC, replay check on every approval |
| `simorgh/execution/config.py` | `[execution]` dataclass, `find_repo_root` |
| `simorgh/execution/tools.py` | the core tools (read/search/list, sandboxes, `run_tests` and its landing gate, patch/replace/commit/revert/discard, tasks, skills, web_fetch, sim_command, memory_forget) and `builtin_tools()` |
| `simorgh/execution/worktree.py` | `WorktreeManager` and `worktree_open` / `worktree_land` / `worktree_close` |
| `simorgh/execution/pathsafety.py` | the read/write path boundary: readable roots, root files, credential names, traversal |
| `simorgh/execution/netsafety.py` | SSRF guard for outbound URLs (`web_fetch`, `render_page`) |
| `simorgh/execution/shell.py` | `run_shell` (on by default) and its refusal table, including credential reads |
| `simorgh/execution/script.py` | `run_script`: Python with the repo importable and network on |
| `simorgh/execution/container.py` | `run_container`: a command in a Docker image with a scratch mount |
| `simorgh/execution/remote.py` | `run_remote`: a command over SSH (off unless `remote = true`) |
| `simorgh/execution/writewatch.py` | discovers what a shell/script command wrote, for `session.wrote` |
| `simorgh/execution/capabilities.py` | boot probes (node, puppeteer, docker, bandit, homeharvest, connectors) and the `capabilities` stream |
| `simorgh/execution/domainstatus.py` | per-domain configured/working connectors for the probes |
| `simorgh/execution/mcp.py` | stdio MCP client and `McpToolProxy` for human-configured servers |
| `simorgh/execution/external.py` | adapters for LangChain / pydantic_ai / Composio / callables behind the Tool protocol |
| `simorgh/execution/packages.py` | `find_package`, `install_package` (age floor, daily cap, denylist) |
| `simorgh/execution/websearch.py` | `web_search` with spacing and a call budget |
| `simorgh/execution/htmltext.py` | HTML to readable text for `web_fetch` |
| `simorgh/execution/pdftext.py` | PDF to text |
| `simorgh/execution/doctext.py` | DOCX, spreadsheet, CSV, image to text for `read_file` |
| `simorgh/execution/render.py` | `render_page` / `browse_page` via Node + Puppeteer |
| `simorgh/execution/notify.py` | `notify`: push a message to a person (irreversible) |
| `simorgh/execution/geocode.py` | `geocode` via Nominatim |
| `simorgh/execution/realestate.py` | `search_listings` |
| `simorgh/execution/listingsources.py` | the listing data sources behind `search_listings` |
| `simorgh/execution/vision.py` | `CameraVision` (describes `world.camera.event`, speaks it) and `camera_describe` |

Domain subpackages (stage 9 moves each to `simorgh/domains/<name>/`):

| Subpackage | For |
|---|---|
| `simorgh/execution/knowledge/` (api, chunk, embed, index, parse, retrieve, sources, tools) | the creator's documents: sqlite FTS5 + vector index; `kb_status`, `kb_sources`, `kb_search`, `kb_open`, `kb_ask` |
| `simorgh/execution/pim/` (api, accounts, ics, nlp, tools, connectors/caldav, imap, fakes) | calendar and mail, read-only, credentials from the vault; `cal_list`, `mail_search`, `mail_read`, `remind` (publishes `system.schedule.add`) |
| `simorgh/execution/security/` (api, findings, selfcheck, tools) | Sim's own security posture, local and advisory; `sec_self`, `sec_posture`, `sec_findings`, `sec_show`, `sec_accept` |
| `simorgh/execution/home/` (registry, tools, cameras, ring) | Home Assistant `home_find/state/describe/call/undo`; Reolink NVR `cam_*` (11 tools); Ring `ring_*` (8 tools) |
| `simorgh/execution/energy/` (api, meters, tools) | meters and tariffs through Home Assistant; `energy_status`, `energy_report`, `energy_tariff` |
| `simorgh/execution/media/` (tools, cast, androidtv, musicapp, tvmedia) | HA `media_*`, Chromecast `cast_*`, dashboard `dash_view`/`dash_key`, Android TV `tv_*`, macOS Music `music_*` |

Each subpackage exports one `<name>_tools(config, secrets=...)` factory that `builtin_tools()` splices in (`tools.py:3105-3163`); device integrations take optional SDKs and refuse by name when absent.

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `action.approved` | `messages/action.py::ActionApproved` | simorgh/execution/service.py | verifies the token, runs the tool (group `execution`, no bus handler timeout), publishes the result |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/execution/service.py | `paused`/`stopping` makes every later approval answer `error="paused"` |
| `learn.skill.acquired` | `messages/learn.py::LearnSkillAcquired` | simorgh/execution/service.py | loads that one skill as `skill:<name>` (Execution is also its only publisher) |
| `world.camera.event` | `messages/world.py::CameraEvent` | simorgh/execution/service.py (`vision.py`) | stills plus a vision model call; announces the description |
| `ui.dash.state` | `messages/ui.py::DashState` | simorgh/execution/service.py | a `charts` view from anyone but Execution autoplays `tv_charts` (a direct tool run, S12) |
| `ui.hook.received` | `messages/ui.py::UiHookReceived` | simorgh/execution/home/cameras.py | while `cam_watch` is on, turns the NVR's push into `world.camera.event` |
| replies | `memory.retrieve`, `cognition.think`, `world.env.query`, `task.create`, `task.list.request`, `ui.command.request`, `memory.forget`, `voice.voices.request`, `voice.control.request` | service.py, vision.py, tools.py | replies to Execution's own `bus.request`s (not subscriptions) |

The generated rows for `action.denied`, `action.result`, `cognition.think`, `percept.web.fetched`, `system.metrics`, `tool.*`, `ui.notice` and `voice.speak.request` as consumed topics were wrong (Execution publishes them) and are deleted.

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `action.result` | `messages/action.py::ActionResult` | simorgh/execution/service.py | once per verified approval (ok, error, timeout, paused, unknown tool); also at boot for each inflight action with `error="interrupted by restart"` |
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/execution/service.py | token verification failed; always `layer="token"` |
| `tool.registered` | `messages/tool.py::ToolRegistered` | simorgh/execution/service.py | at boot per tool, per MCP tool, per skill on disk (announced, not loaded), on each skill load; `schema_ref=""` (T2) |
| `tool.invoked` | `messages/tool.py::ToolInvoked` | simorgh/execution/service.py | after each tool run that returned (not on timeout or crash) |
| `tool.probed` / `tool.unavailable` | `messages/tool.py` | simorgh/execution/service.py | after each probe pass (boot, and after a successful `install_package`); unavailable only for failed free probes |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/execution/service.py | at boot, the `skills` gauge |
| `percept.web.fetched` | `messages/percept.py::PerceptWebFetched` | simorgh/execution/service.py | after a successful `web_fetch` (no consumer; allow-listed one-sided) |
| `learn.skill.acquired` | `messages/learn.py::LearnSkillAcquired` | simorgh/execution/service.py | after a successful `apply_skill` of a `.py` subject |
| `ui.notice` | `messages/ui.py::UiNotice` | service.py, vision.py, home/cameras.py, home/ring.py | a proposed MCP server; a camera description; watcher notices |
| `voice.speak.request` | `messages/voice.py::VoiceSpeakRequest` | simorgh/execution/vision.py | a camera description, when `camera_vision_speak` |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/execution/vision.py | request with images and `require_real_provider=True` |
| `memory.retrieve` | `messages/memory.py::MemoryRetrieve` | simorgh/execution/service.py | request for a skill's procedural description on load |
| `world.camera.event` | `messages/world.py::CameraEvent` | home/cameras.py, home/ring.py | NVR push or Ring poll saw motion/person/ring |
| `ui.tv.state` / `ui.dash.state` / `ui.dash.key` | `messages/ui.py` | media/cast.py, home/cameras.py | the TV page's mode, the dashboard view, a remote key |
| `system.schedule.add` | `messages/system.py::SystemScheduleAdd` | simorgh/execution/pim/tools.py | `remind` |
| tool-driven requests | `task.create`, `task.list.request`, `task.cancel`, `ui.command.request`, `memory.forget`, `voice.voices.request`, `voice.control.request`, `world.env.query` | simorgh/execution/tools.py | `start_task`, `list_tasks`, `cancel_task`, `sim_command`, `memory_forget`, `voice_setting`, `self_map` |

The Service's `produces` tuple lists exactly these 26 topics (since 2026-09-19; it listed ten before). `tests/simorgh/execution/test_produces_manifest.py` pins it both ways against every `Message.new(topics.X` / `.caused(topics.X` / `_publish(ctx, topics.X` in the package, so a new publish without a manifest entry fails.

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `action:{action_id}` | simorgh/execution/service.py (reads Guardian's `received`, appends `verified`) | written first by guardian; read by verification, voice, interface | 30d (`action:`) |
| `execution:inflight` | simorgh/execution/service.py (`started`/`finished`) | - | 7d |
| `execution:tools` | simorgh/execution/service.py (`registered`) | simorgh/interface/dispatch.py, simorgh/orchestration/service.py | 30d |
| `capabilities` | simorgh/execution/capabilities.py (`probed`) | - | forever (no entry) |
| `mcp:proposals` | simorgh/execution/tools.py (`propose_mcp_server`) | simorgh/interface/dispatch.py | forever (no entry) |

Blobs: large outputs, tool metadata and `web_fetch` content via `put_blob`; oversized proposal args are read back with `get_blob`. Large row sets go to `results/<action_id>.json`, not the Ledger. Deleted rows: every `name:{x}` string the generator matched in a tool (`file_write:`, `git_discard:`, `cam_*:`, `ring_*:`, `cast_*:`, `tv_*:`, `media:`, `music:`, `home:{service}:{entity_id}`, `worktree_land:{sha}`, `run_shell:`, `skill:`) is a `ToolResult.side_effects` label or a tool name, not a stream; `vault:...` are secret refs; `python:`, `node:`, `alpine:`, `fe80:`, `javascript:`, `urn:...`, `d:href` and the rest are string literals; `task:{task_id}` appears only in comments.

## Config


`[execution]` in simorgh.toml; dataclass in `simorgh/execution/config.py`. `Config.from_mapping` passes flat keys straight through (unknown keys dropped); a `repo_root` key also sets `repo_root_named = True` (`config.py:598-626`), which is what turns worktrees on. `sim.sh` supplies it through `SIMORGH_EXECUTION_REPO_ROOT`. Domain keys (`knowledge_*`, `pim_*`, `security_*`, `home_*`, `energy_*`, `media_*`, `cast_*`, `ring_*`, `cam_*`, `camera_vision_*`) are read only by their subpackage. Several keys are also read with `getattr(config, "x", default)` (B15), e.g. `service.py:249-251, 474, 510, 534`.

| Key | Default | Read in the package |
|---|---|---|
| `max_concurrent_actions` | `4` | yes |
| `default_timeout_s` | `60.0` | yes |
| `max_output_bytes` | `65536` | yes |
| `blob_inline_threshold_bytes` | `4096` | yes |
| `approval_max_age_s` | `120.0` | NO (declared, never read; expiry is Guardian's `expires_at`, see `kernel/configcheck.py:103-115`) |
| `repo_root` | `field(default_factory=lambda: find_repo_root())` | yes |
| `repo_root_named` | `False` | yes |
| `readable_roots` | `('src', 'docs', 'tests', 'simorgh', 'simorgh_skills', 'paper` | yes |
| `readable_root_files` | `('README.md', 'CLAUDE.md', 'requirements.txt', 'simorgh.toml` | yes (every `pathsafety` call passes it as `root_files`; `pathsafety.ROOT_FILES` is only the default for direct callers) |
| `write_scopes_source` | `('simorgh/', 'simorgh_skills/', 'tests/', 'tools/', 'docs/',` | yes |
| `worktrees` | `True` | yes |
| `worktree_dir` | `''` | yes |
| `landing_gate` | `True` | yes |
| `worktree_max_age_days` | `7.0` | yes |
| `sandbox_cpu_seconds` | `5` | yes |
| `sandbox_memory_mb` | `256` | yes |
| `sandbox_timeout_s` | `10.0` | yes |
| `search_max_files_scanned` | `2000` | yes |
| `search_max_matches` | `200` | yes |
| `search_max_file_bytes` | `1000000` | yes |
| `test_timeout_s` | `300.0` | yes |
| `test_cpu_seconds` | `240` | yes |
| `test_memory_mb` | `1024` | yes |
| `test_output_max_chars` | `8000` | yes |
| `skill_dir` | `'simorgh_skills'` | yes |
| `write_scopes_skills` | `('simorgh_skills/',)` | yes |
| `skill_lookup_timeout_s` | `2.0` | yes |
| `web_fetch_timeout_s` | `10.0` | yes |
| `web_fetch_bearers` | `(('huggingface.co', 'HF_TOKEN'), ('cdn-lfs.huggingface.co', ` | yes |
| `shell` | `True` | yes |
| `remote` | `False` | yes |
| `remote_timeout_s` | `300.0` | yes |
| `remote_connect_timeout_s` | `15.0` | yes |
| `remote_output_max_chars` | `8000` | yes |
| `remote_strict_host_key` | `True` | yes |
| `remote_working_dir` | `''` | yes |
| `shell_timeout_s` | `120.0` | yes |
| `shell_refusals` | `field(default_factory=lambda: dict(DEFAULT_SHELL_REFUSALS))` | yes |
| `web_search_provider` | `'auto'` | yes |
| `web_search_max_results` | `8` | yes |
| `web_search_timeout_s` | `15.0` | yes |
| `web_search_max_bytes` | `400000` | yes |
| `web_search_min_interval_s` | `2.0` | yes |
| `web_search_attempts` | `3` | yes |
| `web_search_max_calls` | `60` | yes |
| `web_search_window_s` | `3600.0` | yes |
| `web_fetch_extract_text` | `True` | yes |
| `web_fetch_max_bytes` | `200000` | yes |
| `web_fetch_max_calls` | `30` | yes |
| `web_fetch_max_total_calls` | `240` | yes |
| `web_fetch_window_s` | `3600.0` | yes |
| `web_fetch_allow_private_networks` | `False` | yes |
| `web_fetch_user_agent` | `'Simorgh/2.0 (personal AI assistant; +https://github.com/sae` | yes |
| `results_dir` | `'results'` | yes |
| `results_max_rows` | `500` | yes |
| `results_keep_files` | `50` | yes |
| `package_lookup_timeout_s` | `10.0` | yes |
| `package_install_timeout_s` | `300.0` | yes |
| `package_min_age_days` | `30` | yes |
| `max_installs_per_day` | `10` | yes |
| `package_log` | `'simorgh_packages.txt'` | yes |
| `package_denylist` | `('(?i)^sudo', '(?i)^setuptools$', '(?i)^pip$')` | yes |
| `script_dir` | `'.simorgh_scripts'` | yes |
| `script_timeout_s` | `180.0` | yes |
| `script_cpu_seconds` | `120` | yes |
| `script_memory_mb` | `1024` | yes |
| `script_output_max_chars` | `8000` | yes |
| `script_keep_files` | `50` | yes |
| `script_env_passthrough` | `('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'HTTP_PROXY', '` | yes |
| `notify_provider` | `'auto'` | yes |
| `notify_timeout_s` | `15.0` | yes |
| `notify_max_chars` | `4000` | yes |
| `notify_max_calls` | `20` | yes |
| `notify_window_s` | `3600.0` | yes |
| `knowledge_index_path` | `'workspace/knowledge/index.db'` | yes |
| `knowledge_embedder` | `'auto'` | yes |
| `knowledge_chunk_tokens` | `400` | yes |
| `knowledge_chunk_overlap` | `0.15` | yes |
| `knowledge_max_file_mb` | `100` | yes |
| `knowledge_max_results` | `25` | yes |
| `knowledge_max_chars` | `6000` | yes |
| `knowledge_cloud_llm_may_see` | `('public', 'personal')` | yes |
| `pim_accounts` | `()` | yes |
| `pim_timeout_s` | `20.0` | yes |
| `pim_max_results` | `50` | yes |
| `pim_body_max_chars` | `20000` | yes |
| `pim_max_reminder_days` | `365` | yes |
| `pim_cloud_llm_may_see` | `('public', 'personal')` | yes |
| `security_findings_path` | `'workspace/security/findings.db'` | yes |
| `security_secrets_paths` | `('workspace', 'results')` | yes |
| `security_config_path` | `''` | yes |
| `security_posture_weights` | `field(default_factory=lambda: {'critical': 25, 'high': 10, '` | yes |
| `home_timeout_s` | `10.0` | yes |
| `home_dry_run` | `False` | yes |
| `home_settle_s` | `1.0` | yes |
| `home_max_entities_per_call` | `20` | yes |
| `home_aliases` | `field(default_factory=dict)` | yes |
| `home_always_human_services` | `()` | yes |
| `energy_meters` | `field(default_factory=dict)` | yes |
| `energy_tariff_path` | `'workspace/energy/tariff.json'` | yes |
| `energy_tariff` | `field(default_factory=dict)` | yes |
| `energy_currency` | `'USD'` | yes |
| `energy_cycle_days` | `30` | yes |
| `media_max_volume_unattended` | `60` | yes |
| `media_quiet_hours` | `'22:00-07:00'` | yes |
| `media_quiet_hours_max_volume` | `20` | yes |
| `cast_device` | `''` | yes |
| `cast_page_url` | `''` | yes |
| `cast_page_port` | `8765` | yes |
| `cast_discovery_s` | `5.0` | yes |
| `tv_show_on_start` | `False` | yes |
| `ring_poll_s` | `120.0` | yes |
| `ring_watch_on_start` | `True` | yes |
| `cam_watch_on_start` | `True` | yes |
| `ring_snapshot_every_s` | `300.0` | yes |
| `camera_vision` | `True` | yes |
| `camera_vision_stills` | `2` | yes |
| `camera_vision_concurrency` | `1` | yes |
| `camera_vision_baseline_samples` | `3` | yes |
| `camera_vision_baseline_sweep` | `True` | yes |
| `camera_vision_baseline_every_s` | `300.0` | yes |
| `camera_vision_baseline_first_s` | `30.0` | yes |
| `camera_vision_gap_s` | `1.5` | yes |
| `camera_vision_cooldown_s` | `90.0` | yes |
| `camera_vision_timeout_s` | `60.0` | yes |
| `camera_vision_speak` | `True` | yes |
| `render_page_timeout_s` | `20.0` | yes |
| `render_page_max_chars` | `20000` | yes |
| `render_page_allow_private_networks` | `False` | yes |
| `render_page_node_path` | `''` | yes |
| `render_screenshot_dir` | `'results/screenshots'` | yes |
| `container_docker_path` | `''` | yes |
| `container_image_prefixes` | `('python:', 'node:', 'ubuntu:', 'debian:', 'alpine:', 'golan` | yes |
| `container_scratch_dir` | `'results/containers'` | yes |
| `container_timeout_s` | `300.0` | yes |
| `container_memory_mb` | `1024` | yes |
| `container_cpus` | `1.0` | yes |
| `container_output_max_chars` | `8000` | yes |
| `geocode_timeout_s` | `10.0` | yes |
| `geocode_min_interval_s` | `1.0` | yes |
| `geocode_user_agent` | `'Simorgh/2.0 (personal AI assistant; +https://github.com/sae` | yes |
| `real_estate_provider` | `'auto'` | yes |
| `real_estate_max_results` | `20` | yes |
| `real_estate_timeout_s` | `30.0` | yes |
| `real_estate_max_calls` | `20` | yes |
| `real_estate_window_s` | `3600.0` | yes |
| `mcp_servers` | `()` | yes |
| `external_tools` | `()` | yes |

## Public Python surface

- `simorgh.execution.service.Service` (`name = "execution"`, layer 3): `Service(config=None, extra_tools=None, connectors=None)`; `start(ctx)` refuses to start without `ctx.secrets["__hmac__"]`; `stop()`; `health()` (degraded on the last token failure, an MCP start failure, or a failed free probe). `register_connector()`, `skill_files()`. `consumes` is exact for subscriptions (pinned by `tests/simorgh/test_manifests_match_the_code.py`).
- The Tool protocol and `ToolResult`, `ToolContext` live in `simorgh/contracts/protocols.py:167-202`: a tool has `name`, `description`, `read_only`, `reversibility` (`read_only | reversible | irreversible`), `args_schema`, `async run(args, *, ctx) -> ToolResult`; an optional `timeout_s` is honoured by `service.py::timeout_for`. `ToolResult` is `ok`, `output`, `output_ref`, `error` (free text; `refused: ...` by convention, T9), `side_effects` (labels), `metadata` (`rows` go to `results/`, `stderr` is appended to `error`). `ToolContext.root` is the task's worktree, set from the proposal's `task_id`, never from arguments.
- `extra_tools` and `external_tools` are the seams for tools defined elsewhere; every such tool still runs only through `_on_approved`.
- Module-level state (risks): `media/androidtv.py:54` `_PENDING` (a pairing in progress, per process); `verifier.py`'s `ReplayGuard` is in memory, so after a restart replay protection rests on token expiry alone; `vision.py:274` `_NO_LOCK`. `media/tvmedia.py:35` resolves its directory from `Path.cwd()`.

## Invariants

- No tool runs for an `action.approved` whose args (fetched from Guardian's `received` event on `action:<id>`, blob refs resolved) do not hash to `args_sha256`, whose `expires_at` has passed, whose HMAC does not verify with the Kernel's secret, or whose `action_id` was already consumed; each failure publishes `action.denied{layer: "token"}` and appends `verified{outcome: false}` (`service.py:759-773`, `test_verifier.py`).
- Only Execution subscribes to `action.approved`; it never subscribes to `action.proposed` (`contracts/topics.py` `SUBSCRIBE_ONLY_BY`).
- Execution may publish `action.denied` only with `layer="token"` (`PUBLISH_PAYLOAD_CONSTRAINTS[(action.denied, "execution")]`); it never publishes `action.approved` (`PUBLISH_ONLY_BY`: guardian, kernel). `PUBLISH_ONLY_BY` also allows it `system.restart` and `system.reload`; no code in the package publishes either today.
- Every verified approval yields exactly one `action.result` (success, error, timeout, crash, `paused`, `unknown tool`); an approval started but unfinished at shutdown yields `error="interrupted by restart"` at the next boot.
- A tool call's deadline is `constraints.timeout_s`, else the tool's `timeout_s`, else `default_timeout_s` (60 s); the bus handler itself is unbounded so a long gate is not cut from outside.
- File tools resolve paths inside `repo_root` (or the task's worktree) under `readable_roots`, the single root files in `readable_root_files`, and write scopes; absolute paths, `..`, and credential-shaped names are refused (`test_pathsafety.py`, `test_readable_root_files.py`). `run_shell` refuses reads of `~/.simorgh/secrets.toml`, the vault, `.ssh`, `.aws`, `.gnupg` and keychain dumps (`test_shell.py`).
- `worktree_land` fast-forwards main only after a clean rebase and a green whole-suite gate that `simloader.unit_verdict` (loaded from the main checkout) also accepts: exit 0, no failure in the summary, tests ran, count within 10% of the loader baseline; a missing loader means no second opinion, not a refusal (`test_worktree_land_gate.py`). Worktrees are made only for a named `repo_root`.
- Execution imports only `simorgh.contracts`, `simorgh.bus.client` (for `UNBOUNDED`, `service.py:37`) and the standard library plus optional third-party SDKs imported lazily (`tests/simorgh/test_module_boundaries.py`).

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract execution`.

- `tests/simorgh/execution/test_verifier.py` -- the six token outcomes: ok, missing args, hash mismatch, expired, bad signature, replay.
- `tests/simorgh/integration/test_guardian_execution_action_path.py` -- real Guardian + Execution through the Kernel: an approved tool runs, a forged approval is refused before any tool runs, pause and protected paths deny.
- `tests/simorgh/execution/test_worktree_land_gate.py` -- the landing gate refuses nothing-collected, a gutted suite and a forged exit code; no loader means no second opinion.
- `tests/simorgh/execution/test_worktree.py` -- open from HEAD, edits and commits stay on the task branch, rebase, gate, fast-forward, close.
- `tests/simorgh/execution/test_pathsafety.py` -- the path boundary never raises and refuses every escape.
- `tests/simorgh/execution/test_readable_root_files.py` -- `[execution] readable_root_files` decides which root files the read tools open.
- `tests/simorgh/execution/test_produces_manifest.py` -- `Service.produces` equals the set of topics the package publishes or requests.
- `tests/simorgh/execution/test_shell.py` -- `run_shell` refuses credential reads.
- `tests/simorgh/execution/test_tool_unavailable_is_announced.py` -- `tool.unavailable` / `tool.probed` payloads and ordering.
- `tests/simorgh/execution/test_result_handback.py` -- `action.result` carries `metadata_ref` and stderr; rows go to `results/` capped.

## Known issues (2026-09-18 evaluation)

- S2 (critical): the vault, ledger and machine were outside every protected list. Fixed 2026-09-18 (commit `19f69ce`): Guardian protects them and `run_shell` refuses to read them.
- S3 (high): protected paths are checked on the proposal's text, and `worktree.py::_land` never diffs the branch against protected subjects before fast-forwarding. Open; stage 2 item 7 (typed args in Guardian).
- S4 (high): skills. Partly fixed 2026-09-18 (commit `8fb3d21`): `apply_skill` is `irreversible` and always goes to a human (`HumanOnlyRule`). Open: skill-call arguments are not scanned; `SkillTool` runs rlimited with an empty env but with `cwd=repo_root` (`tools.py:2845-2866`).
- S5 (high): the landing gate was weaker than the boot gate. Fixed 2026-09-18 (commit `c009699`).
- S7 (low): the in-process HMAC is ceremony today; keep it.
- S8 (medium): physical tools gated like code. Partly addressed in Guardian (`PhysicalRule`, commit `8916e82`); every device tool still declares its own label here.
- S11 (medium): `shell.py` refusals are a hint, not a boundary. Open; stage 6 tiers.
- S12 / T3 (high): six direct `tool.run()` calls with synthetic action ids and no proposal, token or `action:` stream: `service.py:488, 521, 547, 565` (Ring/NVR watch and TV autostart, charts autoplay) and `vision.py` list/snapshot calls. Open; stage 1 item 7.
- S13 / V9 (medium): `sim_command` (`tools.py:1993`) lets the model run any parsed CLI verb; Guardian sees only the wrapper. Open.
- T2 (high): `tool.registered` ships `schema_ref=""` and no schema. Open; stage 2 item 1.
- T4 / W3 (high): `ring_live` offer, keepalive and close are each an approved action. Open; stage 1 item 6.
- T6 (medium): about a third of tools never proposed; knowledge, energy and the HA-backed tools cannot work today. Open; stage 9.
- T7 (medium): one 60 s default timeout; `install_package` and knowledge scans report timeout while the thread keeps running; nothing writes `constraints.timeout_s`. Open; stage 1 item 5, stage 7 item 8.
- T8 (medium): five parallel device SDK wrappers sharing state through `workspace/`. Open.
- T9 (low): errors are free text (`refused:` prefix). Open; stage 2 item 8.
- T10 (low): sandboxes declare `read_only=True` with `reversibility="reversible"`; Guardian ignores `read_only`. Open.
- T11 (low): probes skip the device SDKs and ffmpeg. Open.
- L4 (medium): ~13 bus messages and ~20 appends per tool call, plus the `action:` read-back in `_fetch_proposal`. Open; stage 1.
- B12 (medium): `_land` runs `git merge --ff-only` in the live checkout, advancing whatever HEAD is, not `main` by name (`worktree.py:243`). Open.
- B15 (medium): `getattr(config, ...)` reads with defaults (e.g. `service.py:249-251`); `tools.py:3159` reads `getattr(config, "shell", False)` against a dataclass default of `True`. Open; stage 0 item 26.
- B18 (low): blocking `subprocess.run` in tools, threaded but not cancellable. Open; stage 7 item 8.
- P7 (low): an unpatched 30 s constant in `media/cast.py` slows the suite. Open.
- W10 (low): 21.6k lines holding six product domains next to the verifier. Open; stage 9 item 1.
- Not in the catalogue: `stop()` reads `self._vision`, which is only set late in `start()` (`service.py:226, 396`), so a `start()` that fails early makes `stop()` raise.

## Planned changes (roadmap)

- Stage 1 (`docs/plan/stage-1-telemetry-out-of-the-decision-log.md`): trace ids threaded through Execution's `Message.new` sites (item 2); tool-run spans (item 4); a `deadline` in the envelope that shrinks tool timeouts (item 5); Ring signalling off the approval path, one `ring_live offer` per session (item 6); the six direct tool runs go through `action.proposed` with `proposed_by="execution"` (item 7).
- Stage 2 (`docs/plan/stage-2-native-tool-use.md`): `tool.registered` carries the full ToolSpec with `input_schema` (item 1, `_announce_tool`, MCP `inputSchema` unflattened); `ToolResult.error_kind` (item 8).
- Stage 5 item 6: an effect-free `memory_search` built-in.
- Stage 6 (`docs/plan/stage-6-self-world-people-tiers-initiative.md`): safety tiers 0-3 computed from the ToolSpec (item 5); `vision.py`'s announce step moves into `initiative/` (item 6); people-aware identity (item 4).
- Stage 7 item 8 (`docs/plan/stage-7-long-horizon.md`): `run_tests`, `run_container` and the landing gate as subprocesses killed on deadline.
- Stage 8 items 5 and 9: `policy_adopt` landing through the gate; HA routine mining.
- Stage 9 (`docs/plan/stage-9-consolidation-and-breadth.md`): the six domains move to `simorgh/domains/<name>/` behind `extra_tools`, leaving registry, verifier, sandboxes, worktrees and path/net safety here, the only part Guardian-protected (item 1, target under 8,000 lines); `vision.py` and the watchers move to `perception/` (item 4); MCP-first for new capability (item 9); `browse_page` becomes a snapshot-act loop (item 10).

## Working on this module

Lock it first (`python tools/modlock.py claim execution --by <you> --task "..."`), commit the lock, edit only `simorgh/execution/`, `tests/simorgh/execution/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py execution` before committing; commit subject `execution: <what changed>`.

This package is Guardian-protected: Sim's own tasks cannot edit it. A human-run agent may, with the lock, because a person is accountable for the commit.

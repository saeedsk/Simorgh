# execution -- contract

One-line status: layer 3 · 21,657 lines · 60 test files · lock: `execution` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/execution/__init__.py` | TODO |
| `simorgh/execution/capabilities.py` | TODO |
| `simorgh/execution/config.py` | TODO |
| `simorgh/execution/container.py` | TODO |
| `simorgh/execution/doctext.py` | TODO |
| `simorgh/execution/domainstatus.py` | TODO |
| `simorgh/execution/energy/__init__.py` | TODO |
| `simorgh/execution/energy/api.py` | TODO |
| `simorgh/execution/energy/meters.py` | TODO |
| `simorgh/execution/energy/tools.py` | TODO |
| `simorgh/execution/external.py` | TODO |
| `simorgh/execution/geocode.py` | TODO |
| `simorgh/execution/home/__init__.py` | TODO |
| `simorgh/execution/home/cameras.py` | TODO |
| `simorgh/execution/home/registry.py` | TODO |
| `simorgh/execution/home/ring.py` | TODO |
| `simorgh/execution/home/tools.py` | TODO |
| `simorgh/execution/htmltext.py` | TODO |
| `simorgh/execution/knowledge/__init__.py` | TODO |
| `simorgh/execution/knowledge/api.py` | TODO |
| `simorgh/execution/knowledge/chunk.py` | TODO |
| `simorgh/execution/knowledge/embed.py` | TODO |
| `simorgh/execution/knowledge/index.py` | TODO |
| `simorgh/execution/knowledge/parse.py` | TODO |
| `simorgh/execution/knowledge/retrieve.py` | TODO |
| `simorgh/execution/knowledge/sources.py` | TODO |
| `simorgh/execution/knowledge/tools.py` | TODO |
| `simorgh/execution/listingsources.py` | TODO |
| `simorgh/execution/mcp.py` | TODO |
| `simorgh/execution/media/__init__.py` | TODO |
| `simorgh/execution/media/androidtv.py` | TODO |
| `simorgh/execution/media/cast.py` | TODO |
| `simorgh/execution/media/musicapp.py` | TODO |
| `simorgh/execution/media/tools.py` | TODO |
| `simorgh/execution/media/tvmedia.py` | TODO |
| `simorgh/execution/netsafety.py` | TODO |
| `simorgh/execution/notify.py` | TODO |
| `simorgh/execution/packages.py` | TODO |
| `simorgh/execution/pathsafety.py` | TODO |
| `simorgh/execution/pdftext.py` | TODO |
| `simorgh/execution/pim/__init__.py` | TODO |
| `simorgh/execution/pim/accounts.py` | TODO |
| `simorgh/execution/pim/api.py` | TODO |
| `simorgh/execution/pim/connectors/__init__.py` | TODO |
| `simorgh/execution/pim/connectors/caldav.py` | TODO |
| `simorgh/execution/pim/connectors/fakes.py` | TODO |
| `simorgh/execution/pim/connectors/imap.py` | TODO |
| `simorgh/execution/pim/ics.py` | TODO |
| `simorgh/execution/pim/nlp.py` | TODO |
| `simorgh/execution/pim/tools.py` | TODO |
| `simorgh/execution/realestate.py` | TODO |
| `simorgh/execution/remote.py` | TODO |
| `simorgh/execution/render.py` | TODO |
| `simorgh/execution/script.py` | TODO |
| `simorgh/execution/security/__init__.py` | TODO |
| `simorgh/execution/security/api.py` | TODO |
| `simorgh/execution/security/findings.py` | TODO |
| `simorgh/execution/security/selfcheck.py` | TODO |
| `simorgh/execution/security/tools.py` | TODO |
| `simorgh/execution/service.py` | TODO |
| `simorgh/execution/shell.py` | TODO |
| `simorgh/execution/tools.py` | TODO |
| `simorgh/execution/verifier.py` | TODO |
| `simorgh/execution/vision.py` | TODO |
| `simorgh/execution/websearch.py` | TODO |
| `simorgh/execution/worktree.py` | TODO |
| `simorgh/execution/writewatch.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `action.approved` | `messages/action.py::ActionApproved` | simorgh/execution/service.py | TODO |
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/execution/service.py | TODO |
| `action.result` | `messages/action.py::ActionResult` | simorgh/execution/service.py | TODO |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/execution/service.py | TODO |
| `learn.skill.acquired` | `messages/learn.py::LearnSkillAcquired` | simorgh/execution/service.py | TODO |
| `percept.web.fetched` | `messages/percept.py::PerceptWebFetched` | simorgh/execution/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/execution/service.py | TODO |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/execution/service.py | TODO |
| `tool.probed` | `messages/tool.py::ToolProbed` | simorgh/execution/service.py | TODO |
| `tool.registered` | `messages/tool.py::ToolRegistered` | simorgh/execution/service.py | TODO |
| `tool.unavailable` | `messages/tool.py::ToolUnavailable` | simorgh/execution/service.py | TODO |
| `ui.dash.state` | `messages/ui.py::DashState` | simorgh/execution/service.py | TODO |
| `ui.hook.received` | `messages/ui.py::UiHookReceived` | simorgh/execution/home/cameras.py | TODO |
| `ui.notice` | `messages/ui.py::UiNotice` | simorgh/execution/home/cameras.py, simorgh/execution/service.py | TODO |
| `voice.speak.request` | `messages/voice.py::VoiceSpeakRequest` | simorgh/execution/service.py | TODO |
| `world.camera.event` | `messages/world.py::CameraEvent` | simorgh/execution/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/execution/service.py | TODO |
| `action.result` | `messages/action.py::ActionResult` | simorgh/execution/service.py | TODO |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/execution/service.py, simorgh/execution/vision.py | TODO |
| `memory.retrieve` | `messages/memory.py::MemoryRetrieve` | simorgh/execution/service.py | TODO |
| `percept.web.fetched` | `messages/percept.py::PerceptWebFetched` | simorgh/execution/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/execution/service.py | TODO |
| `system.schedule.add` | `messages/system.py::SystemScheduleAdd` | simorgh/execution/pim/tools.py | TODO |
| `tool.invoked` | `messages/tool.py::ToolInvoked` | simorgh/execution/service.py | TODO |
| `tool.probed` | `messages/tool.py::ToolProbed` | simorgh/execution/service.py | TODO |
| `tool.registered` | `messages/tool.py::ToolRegistered` | simorgh/execution/service.py | TODO |
| `tool.unavailable` | `messages/tool.py::ToolUnavailable` | simorgh/execution/service.py | TODO |
| `ui.dash.key` | `messages/ui.py::UiDashKey` | simorgh/execution/media/cast.py | TODO |
| `ui.dash.state` | `messages/ui.py::DashState` | simorgh/execution/media/cast.py | TODO |
| `ui.hook.received` | `messages/ui.py::UiHookReceived` | simorgh/execution/home/cameras.py | TODO |
| `ui.notice` | `messages/ui.py::UiNotice` | simorgh/execution/home/cameras.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/vision.py | TODO |
| `ui.tv.state` | `messages/ui.py::TvState` | simorgh/execution/home/cameras.py, simorgh/execution/media/cast.py | TODO |
| `voice.speak.request` | `messages/voice.py::VoiceSpeakRequest` | simorgh/execution/service.py, simorgh/execution/vision.py | TODO |
| `world.camera.event` | `messages/world.py::CameraEvent` | simorgh/execution/home/cameras.py, simorgh/execution/home/ring.py, simorgh/execution/service.py | TODO |
| `world.env.query` | `messages/world.py::WorldEnvQuery` | simorgh/execution/tools.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `action:{action_id}` | simorgh/execution/service.py | simorgh/cognition/compaction.py, simorgh/cognition/config.py, simorgh/guardian/service.py, simorgh/interface/benchmarkchart.py, simorgh/ledger/compaction.py, simorgh/ledger/service.py, simorgh/ledger/streams.py, simorgh/verification/config.py, simorgh/verification/service.py, simorgh/verification/verdict.py, simorgh/voice/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `alpine:` | simorgh/execution/config.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `c:calendar` | simorgh/execution/pim/connectors/caldav.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `caldav:{name}` | simorgh/execution/pim/connectors/caldav.py, simorgh/execution/pim/connectors/fakes.py | simorgh/interface/dispatch.py, simorgh/kernel/cli.py, simorgh/kernel/secrets.py | see ledger/compaction.py DEFAULT_RETENTION |
| `cam_ir:{cam.channel}` | simorgh/execution/home/cameras.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cam_light:{c.channel}` | simorgh/execution/home/cameras.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cam_light:{cam.channel}` | simorgh/execution/home/cameras.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cam_ptz:{cam.channel}` | simorgh/execution/home/cameras.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cam_siren:{cam.channel}` | simorgh/execution/home/cameras.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cam_stream:stop` | simorgh/execution/home/cameras.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cam_stream:stop-main` | simorgh/execution/home/cameras.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cam_stream:{c.channel}` | simorgh/execution/home/cameras.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cam_watch:off` | simorgh/execution/home/cameras.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cam_watch:on` | simorgh/execution/home/cameras.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cast_play:frame` | simorgh/execution/media/cast.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cast_play:{name}` | simorgh/execution/media/cast.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cast_show:{name}` | simorgh/execution/media/cast.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cast_stop:frame` | simorgh/execution/media/cast.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cast_stop:{name}` | simorgh/execution/media/cast.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cast_volume:{name}` | simorgh/execution/media/cast.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `connector:{connector.name}` | simorgh/execution/capabilities.py | simorgh/contracts/connector.py, simorgh/interface/dispatch.py, simorgh/voice/planner.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |
| `d:href` | simorgh/execution/pim/connectors/caldav.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `d:response` | simorgh/execution/pim/connectors/caldav.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `dash_key:{key}` | simorgh/execution/media/cast.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `debian:` | simorgh/execution/config.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `error:` | simorgh/execution/render.py | simorgh/benchmark/api.py, simorgh/benchmark/runner.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/backends/sqlite.py, simorgh/bus/client.py, simorgh/bus/factory.py, simorgh/cognition/providers/claude_code.py, simorgh/cognition/providers/gemini.py, simorgh/cognition/providers/ollama.py, simorgh/cognition/router.py, simorgh/contracts/messages/cognition.py, simorgh/contracts/protocols.py, simorgh/contracts/registry.py, simorgh/interface/dashfeeds.py, simorgh/interface/dispatch.py, simorgh/kernel/cli.py, simorgh/kernel/vault.py, simorgh/ledger/client.py, simorgh/ledger/service.py, simorgh/orchestration/api.py, simorgh/orchestration/context.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/session.py, simorgh/verification/api.py, simorgh/verification/checks/render.py, simorgh/verification/service.py, simorgh/voice/delivery.py, simorgh/voice/planner.py, simorgh/voice/session.py, simorgh/voice/tts/streaming.py, simorgh/voice/tts/subproc.py | see ledger/compaction.py DEFAULT_RETENTION |
| `execution:inflight` | simorgh/execution/service.py | simorgh/ledger/compaction.py | see ledger/compaction.py DEFAULT_RETENTION |
| `execution:tools` | simorgh/execution/service.py | simorgh/interface/dispatch.py, simorgh/ledger/compaction.py, simorgh/orchestration/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `fe80:` | simorgh/execution/render.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `file_create:{rel}` | simorgh/execution/home/cameras.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `file_create:{r}` | simorgh/execution/home/ring.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `file_create:{subject}` | simorgh/execution/tools.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `file_write:{subject}` | simorgh/execution/tools.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `git_discard:{subject}` | simorgh/execution/tools.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `golang:` | simorgh/execution/config.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `home:{service}:{entity_id}` | simorgh/execution/home/tools.py | simorgh/contracts/console.py, simorgh/contracts/settings.py | see ledger/compaction.py DEFAULT_RETENTION |
| `imap:{name}` | simorgh/execution/pim/connectors/imap.py | simorgh/interface/dispatch.py, simorgh/kernel/cli.py, simorgh/kernel/registry.py, simorgh/kernel/secrets.py | see ledger/compaction.py DEFAULT_RETENTION |
| `javascript:` | simorgh/execution/render.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `mcp:proposals` | simorgh/execution/tools.py | simorgh/interface/dispatch.py | see ledger/compaction.py DEFAULT_RETENTION |
| `media:play:{entity_id}` | simorgh/execution/media/tools.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `media:{op}:{entity_id}` | simorgh/execution/media/tools.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `music:play` | simorgh/execution/media/musicapp.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `music:{op}` | simorgh/execution/media/musicapp.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `no:cacheprovider` | simorgh/execution/tools.py | simorgh/verification/checks/_baseline.py | see ledger/compaction.py DEFAULT_RETENTION |
| `node:` | simorgh/execution/config.py | simorgh/contracts/fields.py, simorgh/interface/dashfeeds.py, simorgh/planning/dag.py | see ledger/compaction.py DEFAULT_RETENTION |
| `python:` | simorgh/execution/config.py, simorgh/execution/container.py | simorgh/orchestration/tools.py, simorgh/voice/tts/subproc.py | see ledger/compaction.py DEFAULT_RETENTION |
| `ring_light:{cam.safe}` | simorgh/execution/home/ring.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `ring_live:{cam.safe}` | simorgh/execution/home/ring.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `ring_live:{cam.safe}:close` | simorgh/execution/home/ring.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `ring_siren:{cam.safe}` | simorgh/execution/home/ring.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `ring_watch:off` | simorgh/execution/home/ring.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `ring_watch:on` | simorgh/execution/home/ring.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `run_shell:<command>` | simorgh/execution/writewatch.py | simorgh/benchmark/swebench.py, simorgh/guardian/rules.py, simorgh/verification/checks/didanything.py | see ledger/compaction.py DEFAULT_RETENTION |
| `rust:` | simorgh/execution/config.py | simorgh/learning/competence.py, simorgh/learning/config.py | see ledger/compaction.py DEFAULT_RETENTION |
| `sim:api` | simorgh/execution/security/api.py, simorgh/execution/security/selfcheck.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `sim:guardian` | simorgh/execution/security/selfcheck.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `sim:process` | simorgh/execution/security/selfcheck.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `skill:` | simorgh/execution/service.py | simorgh/contracts/toolargs.py, simorgh/interface/dispatch.py, simorgh/orchestration/tools.py | see ledger/compaction.py DEFAULT_RETENTION |
| `skill:{name}` | simorgh/execution/service.py | simorgh/contracts/toolargs.py, simorgh/interface/dispatch.py, simorgh/orchestration/tools.py | see ledger/compaction.py DEFAULT_RETENTION |
| `skill:{path.stem}` | simorgh/execution/service.py | simorgh/contracts/toolargs.py, simorgh/interface/dispatch.py, simorgh/orchestration/tools.py | see ledger/compaction.py DEFAULT_RETENTION |
| `skill:{skill_name}` | simorgh/execution/tools.py | simorgh/contracts/toolargs.py, simorgh/interface/dispatch.py, simorgh/orchestration/tools.py | see ledger/compaction.py DEFAULT_RETENTION |
| `spotify:` | simorgh/execution/media/tools.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `tv_app:{name}` | simorgh/execution/media/cast.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `tv_charts:{name}` | simorgh/execution/media/cast.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `tv_key:{name}` | simorgh/execution/media/cast.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `tv_pair:{name}` | simorgh/execution/media/cast.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `ubuntu:` | simorgh/execution/config.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `urn:ietf:params:xml:ns:caldav` | simorgh/execution/pim/connectors/caldav.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `vault:home_assistant:token` | simorgh/execution/home/tools.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `vault:home_assistant:url` | simorgh/execution/home/tools.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `vault:{account.cred_id}:password` | simorgh/execution/pim/accounts.py | simorgh/kernel/registry.py, simorgh/kernel/secrets.py, simorgh/kernel/vault.py | see ledger/compaction.py DEFAULT_RETENTION |
| `vault:{account.cred_id}:value` | simorgh/execution/pim/accounts.py | simorgh/kernel/registry.py, simorgh/kernel/secrets.py, simorgh/kernel/vault.py | see ledger/compaction.py DEFAULT_RETENTION |
| `worktree_land:{landed.commit}` | simorgh/execution/worktree.py | simorgh/orchestration/api.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[execution]` in simorgh.toml; dataclass in `simorgh/execution/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `max_concurrent_actions` | `4` | yes |
| `default_timeout_s` | `60.0` | yes |
| `max_output_bytes` | `65536` | yes |
| `blob_inline_threshold_bytes` | `4096` | yes |
| `approval_max_age_s` | `120.0` | NO (declared, never read) |
| `repo_root` | `field(default_factory=lambda: find_repo_root())` | yes |
| `repo_root_named` | `False` | yes |
| `readable_roots` | `('src', 'docs', 'tests', 'simorgh', 'simorgh_skills', 'paper` | yes |
| `readable_root_files` | `('README.md', 'CLAUDE.md', 'requirements.txt', 'simorgh.toml` | NO (declared, never read) |
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

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract execution`.

- `tests/simorgh/execution/energy/test_energy.py` -- TODO: what it pins
- `tests/simorgh/execution/home/test_cameras.py` -- TODO: what it pins
- `tests/simorgh/execution/home/test_home.py` -- TODO: what it pins
- `tests/simorgh/execution/home/test_onvif_events_are_awaited.py` -- TODO: what it pins
- `tests/simorgh/execution/home/test_ring.py` -- TODO: what it pins
- `tests/simorgh/execution/knowledge/test_chunk.py` -- TODO: what it pins
- `tests/simorgh/execution/knowledge/test_index_and_scan.py` -- TODO: what it pins
- `tests/simorgh/execution/knowledge/test_retrieve_and_tools.py` -- TODO: what it pins
- `tests/simorgh/execution/media/test_androidtv.py` -- TODO: what it pins
- `tests/simorgh/execution/media/test_cast.py` -- TODO: what it pins
- `tests/simorgh/execution/media/test_media.py` -- TODO: what it pins
- `tests/simorgh/execution/media/test_musicapp.py` -- TODO: what it pins
- `tests/simorgh/execution/media/test_tvmedia.py` -- TODO: what it pins
- `tests/simorgh/execution/pim/test_connectors_and_tools.py` -- TODO: what it pins
- `tests/simorgh/execution/pim/test_ics_and_nlp.py` -- TODO: what it pins
- `tests/simorgh/execution/security/test_security.py` -- TODO: what it pins
- `tests/simorgh/execution/test_camera_baseline_sweep.py` -- TODO: what it pins
- `tests/simorgh/execution/test_camera_describe.py` -- TODO: what it pins
- `tests/simorgh/execution/test_camera_vision.py` -- TODO: what it pins
- `tests/simorgh/execution/test_cameras_are_looked_at_one_at_a_time.py` -- TODO: what it pins
- `tests/simorgh/execution/test_cancel_all_tasks.py` -- TODO: what it pins
- `tests/simorgh/execution/test_capabilities.py` -- TODO: what it pins
- `tests/simorgh/execution/test_console_tail.py` -- TODO: what it pins
- `tests/simorgh/execution/test_container.py` -- TODO: what it pins
- `tests/simorgh/execution/test_doctext.py` -- TODO: what it pins
- `tests/simorgh/execution/test_external.py` -- TODO: what it pins
- `tests/simorgh/execution/test_geocode.py` -- TODO: what it pins
- `tests/simorgh/execution/test_git_history.py` -- TODO: what it pins
- `tests/simorgh/execution/test_htmltext.py` -- TODO: what it pins
- `tests/simorgh/execution/test_listingsources.py` -- TODO: what it pins
- `tests/simorgh/execution/test_mcp.py` -- TODO: what it pins
- `tests/simorgh/execution/test_memory_forget.py` -- TODO: what it pins
- `tests/simorgh/execution/test_notify.py` -- TODO: what it pins
- `tests/simorgh/execution/test_overheard_tools.py` -- TODO: what it pins
- `tests/simorgh/execution/test_packages.py` -- TODO: what it pins
- `tests/simorgh/execution/test_pathsafety.py` -- TODO: what it pins
- `tests/simorgh/execution/test_pdftext.py` -- TODO: what it pins
- `tests/simorgh/execution/test_realestate.py` -- TODO: what it pins
- `tests/simorgh/execution/test_remote.py` -- TODO: what it pins
- `tests/simorgh/execution/test_render.py` -- TODO: what it pins
- `tests/simorgh/execution/test_replace_in_file.py` -- TODO: what it pins
- `tests/simorgh/execution/test_result_handback.py` -- TODO: what it pins
- `tests/simorgh/execution/test_run_tests_budget_and_loop.py` -- TODO: what it pins
- `tests/simorgh/execution/test_run_tests_failure_marker.py` -- TODO: what it pins
- `tests/simorgh/execution/test_script.py` -- TODO: what it pins
- `tests/simorgh/execution/test_search_code_cannot_read_a_credential.py` -- TODO: what it pins
- `tests/simorgh/execution/test_service.py` -- TODO: what it pins
- `tests/simorgh/execution/test_sim_command.py` -- TODO: what it pins
- `tests/simorgh/execution/test_skills_are_readable.py` -- TODO: what it pins
- `tests/simorgh/execution/test_start_task.py` -- TODO: what it pins
- `tests/simorgh/execution/test_task_subject_is_real.py` -- TODO: what it pins
- `tests/simorgh/execution/test_tests_and_commits_in_a_nested_checkout.py` -- TODO: what it pins
- `tests/simorgh/execution/test_tool_unavailable_is_announced.py` -- TODO: what it pins
- `tests/simorgh/execution/test_tools.py` -- TODO: what it pins
- `tests/simorgh/execution/test_two_runs_share_a_checkout.py` -- TODO: what it pins
- `tests/simorgh/execution/test_verifier.py` -- TODO: what it pins
- `tests/simorgh/execution/test_websearch.py` -- TODO: what it pins
- `tests/simorgh/execution/test_websearch_spacing.py` -- TODO: what it pins
- `tests/simorgh/execution/test_worktree.py` -- TODO: what it pins
- `tests/simorgh/execution/test_writewatch.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim execution --by <you> --task "..."`), commit the lock, edit only `simorgh/execution/`, `tests/simorgh/execution/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py execution` before committing; commit subject `execution: <what changed>`.

This package is Guardian-protected: Sim's own tasks cannot edit it. A human-run agent may, with the lock, because a person is accountable for the commit.

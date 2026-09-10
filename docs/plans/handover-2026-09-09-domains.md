# Domains: what is built, and what is left

Updated 2026-09-09 (Opus 5) after building the platform layer and all
five domains. Supersedes the earlier version of this file, which was
written before any of it existed.

## 1. Built and pushed

### Platform (`platform-connectors-design.md`)

| section | what landed | commit |
|---|---|---|
| §1 vault | `kernel/vault.py` | 7f54faa |
| §3 connectors | `contracts/connector.py`: protocol, `Budget`, `FakeConnector`; Execution probes each as `connector:<name>` under `capabilities` | 38bcc36 |
| §4 HTTP API | bearer-token auth, `register_route`, body cap, per-route rate limit; `registry.DEFAULT_SECRETS` | 9caf8ba |
| §7 notify | ntfy, Gotify, Home Assistant, Matrix, apprise -- self-hosted first in `auto` order | b69c87f |
| §6 monitors | `reflection/digest.py`: `Monitor`, `Alert`, `AlertRouter`, `Digest`, wired to `system.tick.idle` and out through `action.proposed` | 1d0b54f |

### Domains

| domain | tools | commit |
|---|---|---|
| 1 knowledge | `kb_search`, `kb_ask`, `kb_open`, `kb_sources`, `kb_status` | 00a8e70 |
| 2 pim | `cal_list`, `mail_search`, `mail_read`, `remind` | 9c22b66 |
| 4 security | `sec_self`, `sec_posture`, `sec_findings`, `sec_show`, `sec_accept` | 030213b |
| -- house | `home_find`, `home_state`, `home_describe`, `home_call`, `home_undo` | 1d218ab |
| 3 energy | `energy_status`, `energy_report`, `energy_tariff` | 52defbb |
| 5 media | `media_now`, `media_control`, `media_play` | 52defbb |

50 builtin tools; Execution boots to `ok | 50 tools registered`.
4355 tests pass.

**No pip dependency was added for any of it** except optional `apprise`.
CalDAV, IMAP, iCalendar, the natural-language date parser, the Home
Assistant REST client and the document index are all stdlib. A
capability that needs a pip install before it can be tried is one tier
further away than it needs to be.

## 2. Where things live, and why

- `contracts/connector.py` -- the `Connector` protocol, `Budget`.
- `contracts/home/` -- HA client, dataclasses, `policy.py`,
  `fakes.py`. Shared because Execution's tools and a future `home`
  subsystem both need it and may not import each other. Stdlib only
  (`urllib`), because contracts may import nothing else.
- `contracts/timewindow.py` -- `parse_quiet_hours`, shared by
  Reflection and the media tools for the same reason.
- `execution/<domain>/` -- engine and tools for knowledge, pim,
  security, home, energy, media. They live under Execution because the
  tools are there and a subsystem may not import another's internals.

## 3. What is NOT built

**The `home` subsystem** (`home-automation-design.md` sections 2, 4,
5, 6): the WebSocket bridge that turns `state_changed` into
`percept.home.*`, the trigger/condition/action rules engine, presence,
the built-in monitors, `home_announce`, `home_camera`, `home_scene`,
`home_rule`. This is the largest remaining piece and needs a real
WebSocket library. The acting half is done and the percept half is
not; a half-built subscription would be worse than none.

**Guardian's `HomeRule`** (section 7). `classify_call` already computes
the right class and `to_action_payload` sets it per call, so an unlock
is proposed as `irreversible` today. What is missing is the Guardian
side: `auto_approve_exempt_layers = ("home",)`, so `always_human`
survives `SIMORGH_GUARDIAN_AUTO_APPROVE`, plus the announce rate limit
and the >20-entity denial.

**Per domain, the later build-order steps:**

- 1 knowledge: Docling, OCR, the watcher, Paperless/mail-archive
  sources, the reranker, `kb_similar`, `kb_summarize`, `kb_tag`.
  Semantic search needs `pip install sentence-transformers`; without
  it the vector half matches shared words, and every tool says so.
- 2 pim: OAuth (`kernel/oauth.py`, platform §2) for Google and
  Microsoft, the sync database, triage, tasks, contacts, and the
  writing half (`mail_draft`, `mail_send`, `cal_create`) which is
  human-gated by design.
- 3 energy: forecasts, the 1R1C thermal model, the greedy planner and
  the EMHASS adapter, EV charging, the monitors. Each is only worth
  building once the cost figure is trustworthy.
- 4 security: TLS/certificate checks, CVE lookups (OSV/NVD/KEV),
  trivy and lynis on other boxes, the gated exposure checks, HIBP,
  `sec_fix`.
- 5 media: Jellyfin, Music Assistant multi-room, history, `media_cast`,
  `yt-dlp` saving, transcription.

**Platform §2 OAuth, §5 browser profiles, §10 `PrivacyRule`.** The
privacy *decisions* are enforced at each tool edge already
(`knowledge_cloud_llm_may_see`, `pim_cloud_llm_may_see`); what is
missing is the Guardian rule that generalises it.

## 4. Conventions any next step must follow

- The ten-step wiring checklist (`resourcefulness-toolset.md` §2).
  `tests/simorgh/orchestration/test_tools_router.py` now has a
  whole-registry test: every builtin tool must have a `_TOOL_POLICY`
  row and a scaffold note, every profile may only offer tools that
  exist, and the read-only profile may only offer read-only tools.
- Every account-backed integration ships a fake, and **no test touches
  a real account, network or device**.
- A missing credential or package is a refusal naming the exact
  variable or pip line. Never a crash, never absence.
- A tool must never succeed while saying nothing true. `home_call`
  re-reads state because HA answers 200 for a call on an unplugged
  device; `kb_search` says when retrieval was lexical-only.
- Run the suite with
  `python -m pytest tests -q -n auto -p no:cacheprovider --deselect
  tests/simorgh/interface/test_service.py::InterfaceTestCase::test_a_dispatch_created_task_prints_its_real_completion`.
  Never two pytest processes at once: the real-browser tests in
  `test_render.py` fail when two Chromium instances compete.
- Commit with explicit paths and `git commit -F <msgfile>`. No
  `Claude-Session:` line.

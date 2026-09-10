# Handover: implementing the platform layer and the five domains

Written 2026-09-09 by Fable for the next model (Sonnet/Opus). The
creator's instruction: **"read domain folder contents and implement
what is not implemented yet"** -- `docs/plans/domains/01..05` -- and
work hands-free (design assumptions are yours to make; commit and
push often with explicit paths and `git commit -F <msgfile>`).

## 1. Where things stand (verified, not assumed)

Implemented and committed:

- `kernel/vault.py` (platform §1) -- done earlier (7f54faa).
- `contracts/connector.py` (platform §3) -- done, 38bcc36:
  `Connector` protocol, `ConnectorStatus`, `Budget`/`BudgetExhausted`
  (sliding-window rate limit + capped backoff), `FakeConnector`,
  `missing_requirements`, `missing_packages`. Execution takes
  `connectors=` / `register_connector()`, probes each as
  `connector:<name>` (`execution/capabilities.py::connector_probe`),
  lists them under the `capabilities` CLI, closes them on stop.

**Nothing** from `domains/01..05` exists yet. Nor do the designs they
lean on: `home-automation-design.md` (no `simorgh/home/`),
`network-discovery-design.md` (no `simorgh/network/`),
`data-toolset-design.md` (no `query_data`/`db_exec`/`describe_data`
tools -- grep `execution/tools.py` to confirm). `interface/httpapi.py`
has POST `/api/chat` but no auth. `notify` has slack/email/sms only.

## 2. Build order (platform §12, then domains by number)

Do them in this order; each step is one commit with tests.

### 2.1 HTTP API auth, body cap, route table (platform §4) -- NEXT
File: `simorgh/interface/httpapi.py`, config in
`simorgh/interface/config.py`, wiring in `interface/service.py` (the
`HttpApi(...)` construction ~line 226), tests in
`tests/simorgh/interface/test_httpapi.py` (real sockets; `_FakeBus`,
`_FakeLedger`, `_get`/`_post` helpers are there).

Decisions already made:
- Token: `ctx.secrets.get("SIM_API_TOKEN")` (the chained store
  resolves env first, then `secrets.toml`, then `vault:`). Pass it as
  `HttpApi(..., token=...)`. Compare with `hmac.compare_digest`.
- When a token is set: `Authorization: Bearer <token>` required on
  every route except `/` and `/api/status`; 401 JSON body otherwise.
  When no token is set: behaviour unchanged (local dashboard).
- Non-loopback `http_host` without a token: still starts, but logs a
  warning and prints one line saying so (domain 4's `sec_self` will
  report it as critical).
- `_MAX_BODY_BYTES` becomes config `api_max_body_bytes` (default
  1_000_000 per the design; the chat route may keep its own 16 KiB).
- `register_route(method, path, handler, *, auth=True)`; handler is
  `async (query: dict, body: bytes, headers: dict) -> (status, bytes,
  content_type)`. Move the existing routes onto the table only if it
  stays small; a new elif per route is acceptable for now.
- Dashboard (`interface/static/dashboard.html`, 8 `fetch(` sites at
  ~555/628/743/784/806/830/854/946): add one `apiFetch()` wrapper that
  reads `?token=` once into `sessionStorage`, strips it from the URL,
  and sends the header. On 401 show the existing `conn-banner`.

### 2.2 `notify` open-source providers (platform §7)
File `simorgh/execution/notify.py`; tests `tests/simorgh/execution/test_notify.py`
(every test injects `_Opener`; assert the request that WOULD go out).
Add rows to `PROVIDERS`, in `auto` order BEFORE the cloud three:

| provider | env | request |
|---|---|---|
| `ntfy` | `NTFY_URL` (topic URL), optional `NTFY_TOKEN` | POST body=text, headers `Title: <subject>`, Bearer if token |
| `gotify` | `GOTIFY_URL`, `GOTIFY_TOKEN` | POST `{url}/message` JSON `{title, message, priority:5}`, header `X-Gotify-Key` |
| `home_assistant` | `HASS_URL`, `HASS_TOKEN`, optional `HASS_NOTIFY_SERVICE` (default `notify`) | POST `{url}/api/services/notify/{service}` JSON `{title, message}`, Bearer |
| `matrix` | `MATRIX_HOMESERVER`, `MATRIX_TOKEN`, `MATRIX_ROOM` | PUT `{hs}/_matrix/client/v3/rooms/{room}/send/m.room.message/{uuid}` JSON `{msgtype:"m.text", body}` |
| `apprise` | `APPRISE_URLS` | lazy `import apprise`; refuse naming `pip install apprise` when absent |

These are self-hosted, so `_post(...)` needs `allow_private=True` for
them (the URL is the operator's own env var, never a model argument);
the cloud three keep `allow_private=False`. Update the config comment
(`execution/config.py:279`), the tool description, and
`orchestration/scaffolds.py::_TOOL_NOTES["notify"]`. Body never enters
metadata (existing rule).

### 2.3 Monitor/digest framework (platform §6)
`simorgh/reflection/digest.py`: `Monitor` protocol, `Alert(monitor,
severity, key, message)`, idempotent per key until `clear(key)`,
routing info→digest, warn→notify ≤1/h/monitor, critical→notify now.
Pure core with a FakeClock; the bus/`notify` side through Reflection
on `system.tick.idle`. Domains 1/2/4 cite it; keep it small.

### 2.4 OAuth (§2), browser profiles (§5), PrivacyRule (§10)
Only when a domain step needs them (domain 2 step 4 for OAuth).

### 2.5 Domain 1 -- knowledge (`domains/01-knowledge.md`) steps 1-2
**Architecture decision (module boundaries,
`tests/simorgh/test_module_boundaries.py`): a subsystem may import only
`contracts`, `bus.client`, `ledger.client`, stdlib, and itself.** So
`execution/knowledge.py` tools cannot import a `simorgh/knowledge/`
package and cannot import `memory.embedders`. Put the engine under
`simorgh/execution/knowledge/` (`index.py` sqlite+FTS5, `chunk.py`,
`parse.py` reusing `execution/pdftext.py` + `doctext.py`,
`retrieve.py` hybrid FTS5 + a stdlib hashing-vector with RRF, `sources.py`
files source) and the tools in `simorgh/execution/knowledge_tools.py`
or `execution/knowledge.py` (tools module beside the package; pick one
and say so in the docstring). Index at `workspace/knowledge/index.db`.
FTS5 works in this interpreter (checked: `unicode61 remove_diacritics 2`).
Tools for step 1-2: `kb_search`, `kb_ask`, `kb_open`, `kb_sources`,
`kb_status`. `kb_ask` = retrieve → one cognition call via the bus
(`topics.COGNITION_*` request/reply -- see how `verification` or
`curiosity` ask) → answer must cite `[doc:page]` or say "not in your
documents". `excluded_globs` reuses `pathsafety.looks_like_credential_path`.
Follow the ten-step wiring checklist (`resourcefulness-toolset.md` §2)
for every tool; the marker-path test template is
`tests/simorgh/orchestration/test_tools_router.py::TestNotifyMarkerReachesTheTool`.

### 2.6 Domain 2 -- pim (`02-calendar-mail-tasks.md`) steps 1-2
Connectors under `simorgh/contracts/connectors/{caldav,imap}.py`
(third-party imports guarded by `try/except ImportError`, which the
boundary test allows; `caldav`/`icalendar` are NOT installed here,
`imaplib` is stdlib). Each ships `Fake<Name>` in
`contracts/connectors/fakes.py`. Credentials via `VaultHandle` scoped
to `caldav:*` / `imap:*`; ship the `SECRET`-appears-nowhere test.
Tools `cal_list`, `mail_search`, `mail_read`, then `remind` (compiles
to a Kernel schedule -- see the `schedule` command, 089f73c). Hand the
connectors to Execution through `connectors=` so `capabilities` lists them.

### 2.7 Domain 4 -- security (`04-security-posture.md`) step 1
`sec_self` needs no network: report API bind + token presence, vault
key source (`Vault.key_source`), Guardian auto-approve state and
`always_human` exemptions, secrets-looking files in `workspace/` and
`results/` (`pathsafety.looks_like_credential_path`), ledger size.
Findings store `workspace/security/findings.db`; `sec_posture` score.

### 2.8 Domains 3 (energy) and 5 (media)
Both are built on `home` (HA bridge, `home_call`, media_player
entities), which does not exist. Either build `home` first
(`home-automation-design.md`) or defer these and say so in the report.
Pure pieces that need no HA can go early: `home/energy/tariffs.py`
(TOU/tiered price math with tests), `media/resolve.py` fuzzy title
resolution against a fake library.

## 3. Rules that bit before (do not relearn them)

- Unit tests assert code shape; only running the system asserts
  behaviour. After wiring a tool, run one real task with
  `python tools/trial.py "..." --kind research --max-steps 10 --keep`.
- Run the suite: `python -m pytest tests -q -n auto -p no:cacheprovider
  --deselect tests/simorgh/interface/test_service.py::InterfaceTestCase::test_a_dispatch_created_task_prints_its_real_completion`.
  Never run two pytest processes at once.
- `tests/simorgh/execution/test_tools.py::test_registers_exactly_the_scoped_set`
  and `tests/simorgh/test_every_subsystem_reads_its_config.py` fail on
  every new tool/subsystem until updated -- that is the point.
- A tool never succeeds while saying nothing true; a guard that cannot
  classify denies. A missing credential/package is a refusal naming
  the exact variable or `pip install`, never a crash and never absence.
- No test touches a real account, network, or device.
- Do not put Claude-Session URLs in commit messages.

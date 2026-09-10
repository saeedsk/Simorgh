# Platform: what every account-backed domain needs once

Design pass, 2026-09-09 (Fable). Implementation is handed to Opus or a
cheaper model. This is the shared foundation for the ten domain
designs (`domains/*.md`); each of them cites a section here rather than
re-specifying it. Build this first -- most of it is small -- and every
domain gets shorter.

The rules that apply to all of it, restated once:

- **The five invariants and the ten-step wiring checklist** in
  `resourcefulness-toolset.md`. Every tool below is wired through all
  ten steps; the marker-path test in
  `tests/simorgh/orchestration/test_tools_router.py::TestNotifyMarkerReachesTheTool`
  is the template.
- **Tier 5 rule**: a feature needing an account is built ready and
  key-gated; it refuses naming the exact variable/secret to set; it is
  never absent.
- **Local first, cloud as a named tier** for capabilities
  (`feedback_resourcefulness`); **cloud model primary, Ollama fallback**
  for the LLM itself (`voice-design.md §0`).
- **Honesty**: a tool never succeeds while saying nothing true; a guard
  that cannot classify denies (`project_honesty_rules`).
- **No test touches a real account, network, or device.** Every
  connector ships a fake.

## 0. What exists, measured

- `kernel/secrets.py`: `EnvSecretStore`, `FileSecretStore` (refuses
  unsafe permissions), `ChainedSecretStore`. Subsystems declare the
  secrets they need and receive only those. **There is no write path,
  no OAuth token refresh, and no per-account namespace.**
- `execution/mcp.py::McpServerConfig` declares a server's
  side-effect-free tools; everything else is `irreversible`. Wiring an
  MCP tool still needs a `_TOOL_POLICY` row (the seam that broke
  `browse_page`).
- `execution/external.py`: LangChain/Composio/Pydantic-AI tool
  *implementations* wrap as ordinary tools; their runners are never
  used. Any domain may pull a library's tools this way.
- `interface/httpapi.py`: GET-only, no auth, no body parsing.
- `execution/render.py::browse_page`: no cookie/session persistence,
  no storage state -- every visit is a fresh browser.
- `notify` (b639300): Slack/Resend/Twilio only.
- Libraries present: `httpx`, `aiohttp`, `websockets`, `imaplib`
  (stdlib), `watchdog`, `PIL`, `pandas`, `sqlalchemy`, `pyarrow`.
  Absent: `caldav`, `icalendar`, `playwright`, `docling`,
  `unstructured`, `pdfplumber`, `pymupdf`, `paramiko`, `docker`,
  `yt-dlp`, `ofxparse`, `ansible`.

## 1. Credential vault (`simorgh/kernel/vault.py`)

Every domain has accounts. Today a secret is an env var read at boot.
That does not survive OAuth (tokens expire and refresh), multiple
accounts of one kind (two mailboxes), or a person adding an account at
the REPL.

```python
@dataclass(frozen=True)
class Credential:
    id: str                 # "google:saeed", "imap:fastmail", "unifi:home"
    kind: str               # "oauth2" | "token" | "password" | "keyfile" | "cookie_jar"
    scopes: tuple[str, ...] = ()
    expires_at: float | None = None
    # values are NEVER on this object; see `VaultStore.open`

class VaultStore(Protocol):
    def list(self) -> list[Credential]
    def open(self, id: str) -> Mapping[str, str]        # decrypted values, in-memory only
    def put(self, id: str, kind: str, values: Mapping[str, str], *, scopes=(), expires_at=None) -> None
    def delete(self, id: str) -> None
```

Backend, decided: a single file `~/.simorgh/vault.age` encrypted with
**age** (`pyrage`, MIT; or the `age` binary) using a key stored in the
OS keychain via **`keyring`** (macOS Keychain, Linux Secret Service,
Windows Credential Locker). No master password prompt on boot; the OS
already gates it. Fallback when neither is available: `FileSecretStore`
semantics (0600, refuse otherwise) and a startup warning saying so.
`EnvSecretStore` stays first in the chain so nothing that works today
changes.

Rules:
- A subsystem receives a `VaultHandle` scoped to the credential ids it
  declared (`needs = ("google:*", "imap:*")`); `open` outside the scope
  raises.
- Values never enter the bus, the ledger, a `ToolResult`, metadata, or
  a log. The existing tests that assert `SECRET` appears nowhere are
  the model; every connector adds one.
- The CLI: `vault list` (ids, kinds, expiry -- never values),
  `vault add <id> <kind>` (prompts on the terminal with echo off; never
  a tool argument), `vault remove <id>`, `vault rotate <id>`.
- `secrets` audit: `vault list` shows which credentials no subsystem
  has used in 90 days.

## 2. OAuth2 (`simorgh/kernel/oauth.py`)

Google, Microsoft, Withings, Garmin, Spotify, GitHub all need it. One
helper:

```python
async def authorize(provider: OAuthProvider, *, scopes, vault: VaultStore, cred_id: str,
                    open_browser: Callable[[str], None] = webbrowser.open) -> Credential
```

- **Loopback flow** (RFC 8252): starts a one-shot listener on
  `127.0.0.1:<random port>`, prints/opens the URL, receives the code,
  exchanges it, stores `access_token`/`refresh_token`/`expires_at` in
  the vault. PKCE always.
- **Device flow** when there is no browser (a headless HA box): prints
  the code and URL; polls.
- `Refreshing` wrapper: any connector call gets a valid token; refresh
  happens under a lock; a refresh failure marks the credential
  `needs_reauth` and the tool refuses with `vault reauth <id>` -- it
  never loops on 401s.
- Providers are rows: `OAuthProvider(name, auth_url, token_url,
  device_url?, client_id_env, client_secret_env, default_scopes)`.
  Client ids come from env (the creator registers an app once;
  documented per domain).

## 3. Connector pattern (`simorgh/contracts/connector.py`)

Every account-backed integration is a `Connector`:

```python
class Connector(Protocol):
    name: str                       # "google_calendar", "imap", "unifi"
    needs: tuple[str, ...]          # credential ids / env vars; any-of groups allowed
    packages: tuple[str, ...]       # optional pip deps
    async def probe(self) -> tuple[bool, str]      # cheap; never a paid call; names what is missing
    async def close(self) -> None
```

- Construction never raises; `probe()` is the health. `capabilities`
  (the CLI command) lists every connector with its probe result -- so
  "why can't Sim read my mail" is one command.
- A connector's methods return **domain dataclasses**, not vendor
  JSON; tools render them. This is what lets `caldav` and Google
  Calendar sit behind one `calendar_*` tool.
- Rate limits and backoff live in the connector, with a per-connector
  `Budget` (calls/hour) in config; exhaustion is a refusal that says
  when.
- Every connector ships `fakes.py::Fake<Name>` implementing the same
  Protocol from an in-memory table; the domain's tests use only that.

## 4. HTTP API: `POST`, auth, bodies (`interface/httpapi.py`)

Prerequisite for home webhooks, voice, mobile, and every inbound
integration:

- `SIM_API_TOKEN` env (or `vault: api:token`); `Authorization: Bearer`
  on every route except `/` and `/api/status`; constant-time compare.
- `POST` routing with a JSON body limit (`api_max_body_bytes =
  1_000_000`) and a per-route rate limit.
- Bind `127.0.0.1` by default; `[interface] api_bind = "0.0.0.0"` is an
  explicit choice with a startup warning; TLS is the reverse proxy's
  job (Tailscale Serve / Caddy), documented.
- Routes register from subsystems via a small table
  (`register_route(method, path, handler, *, auth=True)`) so `home`,
  `voice`, and the domains below add theirs without editing this file.

## 5. Browser sessions (`execution/render.py`)

`browse_page` gets **named profiles**: `profile: "bank"` → Playwright
`storage_state` saved to `~/.simorgh/browser/<profile>.json`
(encrypted at rest through the vault as `cookie_jar`), loaded on the
next call, so a login done once by a person persists. New tool
`browser_login <profile> <url>` opens a *headed* browser for the person
to log in (2FA included), then saves state -- Sim never types a
password (the existing `#pwd`/`#login_pwd` refusal in `render.py`
stays). Profiles are a `HomeRule`-style Guardian concern: a profile
named in `[execution] browser_profiles_human = ("bank",)` makes every
`browse_page` on it `needs_human`.

## 6. Digest and monitors framework (`simorgh/reflection/digest.py`)

`home` and `network` each specified a daily digest and severity-routed
alerts. Generalise once:

- `Monitor` Protocol: `name`, `check(now) -> list[Alert]`, `interval`;
  registered from any subsystem; run by Reflection on `system.tick.idle`.
- `Alert(monitor, severity: info|warn|critical, key, message, entity?)`
  idempotent per `key` until `clear(key)`.
- Routing: `info` → digest; `warn` → `notify`, ≤ 1/hour/monitor;
  `critical` → `notify` now + `home_announce` if `home` is on + a
  percept for cognition. Quiet hours from `[reflection] quiet_hours`.
- One digest at `digest_hour`, sections contributed per subsystem,
  **one** bounded cognition call for "things I noticed" (Curiosity's
  budget applies).

## 7. `notify`: open-source providers (correction 10 in `resourcefulness-designs.md`)

Add, in `auto` preference order before the cloud ones: `ntfy`
(`NTFY_URL` + optional `NTFY_TOKEN`; topic per severity), `gotify`,
`home_assistant` (`notify.mobile_app_*` via the HA client -- the
phones already have the app), `matrix`, and `apprise` as a catch-all
(`APPRISE_URLS`). Existing three stay. The message body still never
enters metadata.

## 8. MCP integration policy

For every MCP server a domain recommends:

1. A `[[execution.mcp_servers]]` entry with `read_only_tools` named
   explicitly (the protocol has no reversibility field; unnamed =
   irreversible).
2. A `_TOOL_POLICY` row per tool the model may call, and a
   `_MARKER_ARG_KEY` when it is single-argument -- **the missing row is
   how `browse_page` crashed**; a test asserts every configured MCP
   tool has one.
3. Secrets to the server via `env` from the vault, never in the TOML.
4. Prefer a native connector when the domain needs domain dataclasses
   (calendar, mail); prefer MCP when the server is the maintained
   integration and the tool surface is small (Docker, Playwright,
   Obsidian).

## 9. Data flow into `query_data`

Any tool that returns rows puts them in `metadata["rows"]`; Execution
writes `results/<id>.json`; `query_data` (data-toolset-design.md) can
then aggregate. Every domain's list/search tool does this. Larger,
durable tables (a mail index, an inventory, a transaction ledger) go
to `workspace/<domain>/*.db` via `db_exec` conventions, so
`describe_data` finds them.

## 10. Privacy classes

Every connector and tool declares a `privacy` class; Guardian's
`PrivacyRule` (pure) escalates or denies by class × destination:

| class | examples | rule |
|---|---|---|
| `public` | weather, package metadata | free |
| `personal` | calendar, mail subjects, media library | never leaves the machine except to the provider it came from; never into a `notify` body to a cloud provider without `[privacy] allow_personal_in_notify` |
| `sensitive` | mail bodies, documents, health, finance | never into a cloud LLM prompt unless `[privacy] cloud_llm_may_see = ("health", …)` names the class; local model or extraction-only otherwise; never into `results/` unencrypted for finance/health -- those use `workspace/<domain>/*.db` with the vault key |
| `secret` | credentials | never anywhere; the vault only |

The per-task-class provider selection (`voice-design.md §0`) is what
makes "sensitive → local model" enforceable: `[cognition]
sensitive_provider = "ollama"`.

## 11. Subsystem template (for the domains that get one)

`simorgh/<domain>/{api.py, config.py, connectors/, service.py,
monitors.py, fakes.py}` + `simorgh/execution/<domain>.py` for tools +
`tests/simorgh/<domain>/` + an entry in `kernel/registry.py::LAYERS` +
the subsystem-count boot test updated. A domain that is only tools
over a connector (no background work) skips the subsystem and puts the
connector under `simorgh/contracts/connectors/<name>.py`.

## 12. Build order

1. Vault + `vault` CLI (§1). 2. HTTP API auth/POST (§4). 3. Connector
Protocol + fakes convention + `capabilities` listing (§3). 4. `notify`
OSS providers (§7). 5. Digest/monitor framework (§6). 6. OAuth (§2).
7. Browser profiles (§5). 8. PrivacyRule (§10). Then the domains, in
the order given in `domains/README.md`.

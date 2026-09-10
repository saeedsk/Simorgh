# Domain 4: Security and privacy posture -- of the house and of Sim

Sim keeps a standing answer to "is anything on my network or in my
systems exposed, out of date, or leaking?" -- certificates about to
expire, a camera reachable without a password, firmware with a known
CVE, a port that opened last night, a service on the Sim box talking
to somewhere it should not, a secret that landed in a file. **Advisory
and read-only**: Sim inspects and reports; it never attempts entry,
never guesses a credential, never inspects a network it does not own.
Prerequisites: `network-discovery-design.md` (the inventory and its
risk group are the input), platform §6 (alerts), §10 (privacy).

## 0. What exists

- Discovery (`network`) produces `by_risk`: no-auth camera, telnet,
  default banner, unexpected destination, stale firmware. It does not
  know CVEs, certificates, or what Sim's own box exposes.
- Guardian's `DenylistRule`/`StaticAnalysisRule` (bandit) already
  audit *Sim's generated code*; nothing audits *Sim's runtime* (open
  ports, file permissions, the vault's mode, the ledger's size).
- `pathsafety.looks_like_credential_path` and the `.gitignore`
  backstops exist; nothing scans for a secret already written.

## 1. Open-source inventory

| component | role | notes |
|---|---|---|
| **a web-exposure checker** (e.g. an OSS template-driven scanner, MIT) | detection-only hygiene checks against your own hosts: default-credential-present, exposed admin pages, misconfigurations, TLS issues | **detection templates only** -- report that a weakness exists; never active-entry templates, never load or stress testing |
| **`trivy`** (Aqua, Apache-2) | CVE scan of container images and the Sim box's packages (`trivy fs /`, `trivy image`) | also finds secrets in files and misconfig in Dockerfiles |
| **NVD / OSV.dev / CISA KEV** (keyless APIs) | CVE lookups by CPE/vendor+model+firmware from discovery's evidence | OSV for packages; NVD for firmware; KEV for the high-priority list |
| **`sslyze`** / `cryptography` | TLS certificate and configuration checks (expiry, weak ciphers, self-signed) | for every HTTPS service found (cameras, HA, NAS, router) |
| **`crowdsec`** (MIT) | log-based intrusion detection on the Sim/HA box; community blocklists | optional daemon; Sim reads its alerts |
| **`fail2ban`** | bans repeated failed logins on the boxes | Sim reads its jails |
| **`lynis`** (GPL) | host hardening audit for the Sim box / HA box / Pis | one scan → findings with ids |
| **`gitleaks`** / **`trufflehog`** / `detect-secrets` | secrets in files, repos, the workspace | run over `workspace/`, `results/`, the repo, and the ledger blobs |
| **`osquery`** (optional) | listening ports, users, processes, launchd/systemd items on each box | uniform across macOS/Linux; Sim queries it via `run_remote`/local |
| **`ss`/`lsof`/`netstat`** | listening ports on the Sim box | stdlib fallback when osquery is absent |
| **Vaultwarden** (optional) | if the creator wants a self-hosted password manager; Sim never reads it | mentioned for completeness; not integrated |
| **HIBP** (`haveibeenpwned` API, k-anonymity, keyless for range queries) | breached-email checks for the household's addresses (domain 2 contacts) | opt-in |
| **`pi-hole` / `AdGuard Home`** (via API) | DNS-level blocklists; Sim reads query logs for the *unexpected destination* monitor without running tcpdump | if present |
| MCP: Semgrep MCP (code), Trivy has none | | |

## 2. Architecture -- `simorgh/security/` (subsystem #22)

```
security/
  api.py         Finding(id, severity, category, asset, title, evidence, remediation, first_seen, last_seen, status)
  config.py
  checkers/      ports_self.py tls.py cves.py exposures.py trivy.py lynis.py secrets.py hibp.py dns_log.py
  assets.py      the asset list: discovery's inventory + Sim's own boxes (domain 9 fleet) + Sim's own process
  findings.py    store (workspace/security/findings.db), dedupe by (asset, category, fingerprint), status: open|accepted|fixed|regressed
  remediate.py   remediation *proposals*: HA automation to disable UPnP? no -- a checklist per finding kind, plus the few Sim can do (rotate a Sim token, tighten a file mode, re-run with a fix)
  posture.py     the score: weighted open findings → 0–100 with the top three reasons
  service.py     schedules: quick posture daily, deep weekly (after discovery's deep sweep), certs daily
  fakes.py       FakeExposureChecker, FakeTrivy, FakeNVD, fixed asset lists
```

## 3. Tools (`execution/security.py`)

| tool | args | read_only | reversibility | Guardian |
|---|---|---|---|---|
| `sec_posture` | -- | yes | read_only | score, top findings, trend |
| `sec_findings` | `severity?`, `asset?`, `status?`, `since?` | yes | read_only | rows → results |
| `sec_show` | `finding` | yes | read_only | evidence + remediation steps |
| `sec_scan` | `kind: quick\|certs\|cves\|host\|secrets\|exposure`, `asset?`, `confirm?` | no | quick/certs/cves/secrets: reversible; `exposure` (the web-exposure checker) and `host` (lynis on a remote box): **irreversible** | `SecurityRule` (§5) |
| `sec_accept` | `finding`, `reason` | no | reversible | accepted risk, ledgered with who/why |
| `sec_fix` | `finding` | no | irreversible | only for the finding kinds with an automated fix (a Sim-side file mode, rotating `SIM_API_TOKEN`, disabling a `home` webhook); everything else returns the checklist |
| `sec_self` | -- | yes | read_only | Sim's own posture: vault mode, api bind, auto-approve state, secrets in workspace, ledger size, Guardian rules enabled, which exemptions are active |
| `sec_breaches` | `email?` | yes | read_only | HIBP range check; opt-in |

Markers: `SEC_SCAN: certs`; `SEC_SCAN: exposure\n{"asset": "192.168.50.44", "confirm": true}`.

## 4. Config (`[security]`)

```python
enabled: bool = False
assets_from_discovery: bool = True
own_boxes: tuple[str, ...] = ()          # fleet names from domain 9, or "local"
quick_every_s: float = 86400
deep_every_s: float = 604800
cert_warn_days: int = 21
exposure_templates: tuple[str, ...] = ("http/exposures", "http/misconfiguration", "ssl", "network/detection")
check_default_logins: bool = False      # detect that a documented default is still in place; detection only, opt-in, escalated
cve_sources: tuple[str, ...] = ("osv", "nvd", "kev")
secrets_paths: tuple[str, ...] = ("workspace", "results", ".")
hibp_emails: tuple[str, ...] = ()
dns_log: str = ""                        # "pihole:<url>" | "adguard:<url>" | ""
posture_weights: dict = {"critical": 25, "high": 10, "medium": 3, "low": 1}
```

## 5. Guardian -- `SecurityRule`

- Any scanner target outside `[network] allowed_cidrs` → **deny**
  (same rule as discovery, re-checked here).
- an exposure check runs → escalate; default-credential checks → escalate
  *and* require `check_default_logins = true`; templates outside the
  configured list → deny (a template arg is not something the model
  chooses).
- `sec_fix` → escalate always; `sec_accept` → reversible.
- Findings text may contain banners with credentials echoed by a
  badly-written device page; the scanner redacts anything matching a
  password-like field before storing (test with a fake banner
  containing `password=SECRET`).
- Rate: one deep scan per day; the exposure checker ≤ 50 requests/s total.

## 6. Monitors and automations

- Findings raise alerts by severity through the platform framework:
  `critical` (no-auth camera, KEV CVE on an exposed service, an expired
  cert on HA, a secret in `workspace/`, Sim's API bound to `0.0.0.0`
  without a token) → notify now; `high` → notify; `medium/low` →
  digest.
- `regressed` (a fixed finding reappears) → warn.
- Weekly digest: posture score and delta, new/fixed/accepted counts,
  the three things to do this week with the exact steps.
- Percepts: `percept.security.finding {severity, asset, category}` so a
  `home` rule can react ("critical finding on a camera → `home_call
  switch.turn_off` its PoE port", human-gated).

## 7. Tests

- Each scanner against its fake produces `Finding`s with stable
  fingerprints; a second run dedupes; a disappeared finding becomes
  `fixed`; a returning one `regressed`.
- CVE matching: (vendor, model, firmware) → CPE → OSV/NVD fake → only
  versions in range; KEV flag raises severity.
- TLS: expiring in 20 days → warn; self-signed on a LAN device → low,
  not critical (it is normal).
- Redaction test on banners.
- `SecurityRule`: out-of-CIDR deny; exposure-check escalate; template
  allow-list.
- `sec_self` reports every item in §3's list against a temp config,
  including "auto-approve is on and `always_human` exemptions are
  active".
- End-to-end: FakeNetwork inventory (one no-auth camera, one stale
  firmware) → `SEC_SCAN quick` → posture < 60 with those two reasons.

## 8. Build order and acceptance

1. Findings store + `sec_self` + `sec_posture` from discovery's risk
   group. Acceptance: on this laptop, `sec_self` correctly reports the
   API bind, vault mode, auto-approve state.
2. TLS + secrets scanners. 3. CVE lookups from discovery evidence.
4. trivy/lynis on own boxes (via domain 9). 5. exposure checks,
gated. 6. HIBP, DNS-log destinations, `sec_fix` for the Sim-side kinds.

## 9. Traps

- CVE matching on IoT is noisy: match only when firmware version is
  known; vendor-only matches are `info` with "verify".
- the exposure checker's default config phones home for template updates; run with
  `-duc` (disable update check) and pin a templates commit.
- trivy's DB download is ~50 MB and rate-limited from GitHub; cache in
  `workspace/security/`.
- Never store a full HTTP response body from a device page; evidence
  is headers + the matched line.
- "Accepted" risks must expire (90 days) or they become permanent
  blind spots.

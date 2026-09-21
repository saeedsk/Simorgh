# domains -- contract

One-line status: not a Subsystem; six tool packages behind Execution's `extra_tools` seam · lock: `domains` in docs/modules/locks.toml

## Purpose

The product domains -- the creator's documents (`knowledge`), calendar and mail (`pim`), Sim's own security posture (`security`), the house through Home Assistant (`home`, with the Reolink and Ring cameras), energy (`energy`) and media (`media`) -- lived inside `simorgh/execution/` next to the HMAC verifier and the sandboxes until stage 9 item 1 (2026-09-20). That put ~10,600 lines of integrations in the one package Sim may never edit, for no safety reason: a media tool is not part of the approval path, it is something the approval path gates.

They are here now, registered through `Execution.extra_tools` exactly as an external adapter would be, and **Sim may edit them**: `simorgh/domains/` is not a Guardian-protected subject (pinned by `tests/simorgh/guardian/test_protected_subjects.py`). Execution keeps the registry, the verifier, the sandboxes, the worktrees and path/net safety, and only that is protected.

Nothing about the tools changed: same names, same schemas, same `action.proposed` path, same `source: execution` on the bus (they run under Execution's Context). The set of tools Sim can reach is identical (`tests/simorgh/execution/test_tools.py::test_registers_exactly_the_scoped_set` checks builtin and domain tools together).

## Files

| Path | For |
|---|---|
| `simorgh/domains/__init__.py` | `domain_tools(config, secrets=)` -- the one factory Execution is handed; `DOMAINS` |
| `simorgh/domains/knowledge/` | the creator's own documents, indexed locally; `kb_*` |
| `simorgh/domains/pim/` | calendar and mail, read-only; `cal_list`, `mail_*`, `remind` |
| `simorgh/domains/security/` | posture, findings, self-check; `sec_*` |
| `simorgh/domains/home/` | Home Assistant `home_*`; Reolink `cam_*` (`cameras.py`); Ring `ring_*` (`ring.py`). `home_call` and `home_undo` report `after` in their metadata -- what each entity is NOW, not only that it moved -- because the World Model folds it into `world:home` (stage 6 item 3, 2026-09-20): Sim turning the kitchen light on used to leave Sim not knowing the light was on. `home_state` shows EVERY match for an ambiguous name rather than refusing (2026-09-20): reading is not acting, and the refusal it replaced listed the candidates anyway. `home_call` still refuses an ambiguous target |

`ring_live` gates the OFFER and the CLOSE and nothing in between. The session id is minted by an approved offer, so refreshing it is that approval continuing, not a new capability; the process runs its own keep-alive every `contracts/home/live.py::KEEPALIVE_EVERY_S` while the dashboard's ordinary ten-second poll says somebody is still watching, and drops the session after `WATCHING_TIMEOUT_S` with no sign of the page. Before 2026-09-20 the page sent one keep-alive per camera every twenty seconds as a full gated action -- 640 approvals in the worst measured hour, each its own `action:` ledger stream, against a stage 1 target of ten.

Home Assistant's URL and token are read from the secret store under EITHER `vault:home_assistant:url`/`token` (the documented names) or the plain `HOME_ASSISTANT_URL`/`HOME_ASSISTANT_TOKEN`, and then from the environment; the vault name wins if both are set. Until 2026-09-20 only the vault name was asked of the store and the plain name fell through to the environment alone, so a token written into `secrets.toml` the way `REOLINK_*` and `RING_*` are written was silently ignored and Sim said Home Assistant was not configured.
| `simorgh/domains/energy/` | `energy_*` |
| `simorgh/domains/media/` | players, Cast, the TV, the dashboard, the Mac's Music app |

Each domain still has its own `CONTRACT.md` describing its tools, config and streams; this file is the seam.

## What a domain may import

`simorgh.contracts` only (plus guarded third-party libraries), like every other package -- pinned by `tests/simorgh/test_module_boundaries.py`. Two things the domains needed from Execution moved into contracts so this holds: `contracts/pathnames.py::looks_like_credential_path` and the document converters `contracts/text/{pdftext,doctext,htmltext}`. Execution imports them from there too; the old `simorgh.execution.{pdftext,doctext,htmltext}` paths are shims for one bless cycle.

## No library output on the creator's screen

A domain that loads a model loads it in Sim's own process, where a library's progress bar goes straight into the TUI (`evals/house/script.py::tui_is_sane` fails a scene that shows one). `knowledge/embed.py::hush_model_progress()` runs before `sentence-transformers` is imported and `QuietEncoder` passes `show_progress_bar=False` around `encode`. Both are the libraries' own switches: nothing redirects stdout or stderr, so a real error still arrives. Pinned by `tests/simorgh/domains/knowledge/test_retrieve_and_tools.py::EmbedTestCase::test_the_model_is_asked_not_to_draw_a_progress_bar`.

## Manifests

The domains publish (`ui.tv.state`, `ui.dash.*`, `world.camera.event`, `system.schedule.add`, ...) under Execution's Context, so those topics stay in **Execution's** `produces` and the manifest tests count `simorgh/domains/` as Execution's code (`_ALSO_RUNS_AS` in `tests/simorgh/test_manifests_match_the_code.py`, `_ALSO` in `tests/simorgh/execution/test_produces_manifest.py`).

## Working on this module

Lock `domains`; edit `simorgh/domains/<name>/`, `tests/simorgh/domains/<name>/` and the domain's own CONTRACT. A new tool for an external service does not belong here at all -- it arrives as an MCP server (`docs/adding-capability.md`). Run `python tools/modtest.py domains`; commit subject `domains: <what changed>` or `<domain>: <what changed>`.

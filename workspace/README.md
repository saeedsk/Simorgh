# workspace/

Sim's own scratch directory, and the one place it may write freely.

It is in `[execution] write_scopes_source`, so `apply_source_patch` can
create files here without touching the repository proper. Nothing here
is committed except this README (see `.gitignore`), nothing here is
reviewed, and everything here survives to the next session -- which is
what makes it the right home for notes, intermediates, a dataset still
being worked on, and anything a person asked Sim to *make*.

Subdirectories the domains use:

| path | what it holds |
|---|---|
| `knowledge/index.db` | the document index (domain 1) |
| `security/findings.db` | security findings (domain 4) |
| `energy/tariff.json` | the electricity tariff (domain 3) |
| `media/downloads/` | anything `media_save` fetches (domain 5) |

Deleting any of them is safe: each is derived and is rebuilt on the
next scan or check.

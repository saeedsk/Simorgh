# A2A JSON Schema fixtures (vendored test data)

The A2A protocol's own JSON Schema, vendored verbatim so
`tests/simorgh/contracts/test_a2a.py` can prove that `simorgh/contracts/a2a.py`
writes what the spec accepts and reads back what it wrote. Nothing in
`simorgh/` reads these files.

| File | A2A version | Source | sha256 | Fetched |
|---|---|---|---|---|
| `a2a-v1.0.1.json` | **v1.0.1** (release 2026-05-28; the version `a2a.py` writes by default) | https://a2a-protocol.org/v1.0.1/spec/a2a.json | `ba4b702b5edbdcbfe972c272484eb38e1fcd72af3c0b7eaa114b50e97455d8dd` | 2026-10-27 |
| `a2a-v0.3.0.json` | **v0.3.0** (release 2025-07-30; the last version with the schema committed in the repo) | https://github.com/a2aproject/A2A/blob/v0.3.0/specification/json/a2a.json | `97d6e2435336836cd1d41dffacf83a1a97902b62b826ef14ec5704db85c95f17` | 2026-10-27 |

Why two. Since v1.0 the repository's `specification/json/` holds only a README:
`a2a.json` is generated from `specification/a2a.proto` at docs-build time and
published on the docs site instead, so v1.0.1 comes from there. v0.3.0 is the
wire most deployed agents and SDK releases from 2025 still speak (`kind`
discriminators, lower-case task states such as `input-required`); `a2a.py`
reads both and can write either.

Quirk of the v1.0.1 bundle: its `definitions` are keyed by spaced titles
(`"Task Status"`) and its `$ref`s name the unbundled per-message files
(`lf.a2a.v1.TaskStatus.jsonschema.json`, `google.protobuf.Struct.jsonschema.json`).
The test resolves such a ref to the definition whose key, with spaces removed,
is the ref's last dotted name before `.jsonschema.json`. The file itself is not
edited.

To move to a newer version: download the new bundle next to these, add a row,
point `A2A_DEFAULT_VERSION` in `a2a.py` and the test at it, and keep the old
file until nothing writes that version.

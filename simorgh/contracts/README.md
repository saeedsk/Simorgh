# `simorgh.contracts`

The single shared dependency of every Simorgh v2 subsystem. Prose spec:
[`docs/blueprint/03-contracts-and-messaging.md`](../../docs/blueprint/03-contracts-and-messaging.md);
architecture and module rules: [`02-system-architecture.md`](../../docs/blueprint/02-system-architecture.md) §4.
This package imports nothing but the standard library (enforced by
`tests/simorgh/test_module_boundaries.py`).

| Module | What |
|---|---|
| `envelope.py` | `Message` (the envelope), `validate()`, canonical JSON, `Event` (the Ledger record) |
| `topics.py` | every domain and message type as constants, `CATALOG`, pattern matching (`*`, `#`), reply naming, the reserved-topology tables the Kernel enforces |
| `fields.py` | the tiny field-type language messages are declared in |
| `registry.py` | `define()` → frozen dataclass + JSON Schema + catalog entry; `get_spec`, `all_specs` |
| `messages/<domain>.py` | one module per domain; the catalog's declarations (v1) |
| `schema/<type>.v1.json` | generated JSON Schema (draft 2020-12) per type — a verified projection of `messages/` |
| `validation.py` | dependency-free JSON Schema subset validator |
| `protocols.py` | `Bus`, `Ledger`, `Subsystem`, `Context`, `Health`, `Clock`, `Provider`, `Tool`, … |
| `security.py` | approval tokens (HMAC-bound to the exact action), `ReplayGuard`, subsystem tokens |
| `compat.py` | schema-version translator registry (empty at v1, mechanism ready) |
| `schemagen.py` | `python -m simorgh.contracts.schemagen [--check]` |

## Using it

```python
from simorgh.contracts import Message, validate, topics
m = Message.new(topics.TASK_STEP, source="orchestration@w1", partition_key="task:t1",
                payload={"task_id": "t1", "step_no": 1, "phase": "act", "summary": "read src/x.py"})
validate(m)                       # raises ContractError with every problem, or returns m
reply = request.reply(topics.TASK_CLAIM_REPLY, {"granted": True}, source="planning")
```

Dataclasses: `from simorgh.contracts.messages.task import TaskStep`;
`TaskStep(...).to_payload()`, `TaskStep.from_payload(payload)`.

## Regenerating schemas

After editing any `messages/*.py`: `python3 -m simorgh.contracts.schemagen`,
then commit `schema/`. `--check` (and `tests/simorgh/contracts/test_schemagen.py`)
fails if the files drift from the declarations.

## Changing the catalog

Follow `docs/blueprint/05-agent-build-instructions.md` §6. Adding an
optional field is non-breaking; anything else bumps `schema_version` and
needs a translator in `compat.py`.

## Tests

`python3 -m unittest discover -s tests -t .` (whole repo) or
`python3 -m unittest tests.simorgh.contracts tests.simorgh.test_module_boundaries`.

## Build log

- 2026-09-06 — Phase 0: package built to `03` (catalog v1, 123 types across
  21 domains), schemas generated, protocols/security/compat, contract
  tests, and the AST boundary checker with its own self-test. Doc fix:
  `turn` and `project` added to `03` §3's domain table (they are their
  own first segment on the wire; the prose listed them under `task.*` /
  `plan.*`). Open: `system.status.reply`'s snapshot shape is a minimal
  open object pending the Kernel spec's build.

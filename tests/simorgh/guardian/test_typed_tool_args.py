"""Guardian reads the tool registry and typed arguments (stage 2 item 7).

Before: `ToolInfo` was built from the proposal's own `reversibility`
label (evaluation S6), no argument was checked against the tool's
schema, and the rules guessed which argument names a file from a fixed
pair of keys. Now Guardian keeps what Execution announced on
`tool.registered` and judges the proposal by that.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message, validate
from simorgh.guardian.api import DecisionContext, Proposal
from simorgh.guardian.config import Config
from simorgh.guardian.pipeline import Pipeline
from simorgh.guardian.posture import Posture
from simorgh.guardian.registry import ToolRegistry, enforced_schema, schema_errors, schema_subject_keys
from simorgh.guardian.rules import DEFAULT_PIPELINE, DenylistRule, ProtectedRule, SchemaRule
from simorgh.guardian.service import TOOLS_STREAM, Service

RUN_SHELL = {"name": "run_shell", "reversibility": "irreversible", "read_only": False,
             "input_schema": {"type": "object", "required": ["command"],
                              "properties": {"command": {"type": "string"}}}}
READ_FILE = {"name": "read_file", "reversibility": "read_only", "read_only": True,
             "input_schema": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}}
# An MCP-style writer whose file argument is neither `path` nor `subject`.
WRITE_NOTE = {"name": "mcp_fs_write_note", "reversibility": "reversible", "read_only": False,
              "input_schema": {"type": "object", "required": ["file_path", "content"],
                               "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}}}


def _proposal(tool, args, claimed="reversible", **kw):
    return Proposal(action_id=kw.pop("action_id", "a1"), tool=tool, args=args, scope=kw.pop("scope", {}),
                    reversibility=claimed, rationale="t", proposed_by="test", **kw)


def _ctx(registry: ToolRegistry, proposal: Proposal, **cfg) -> DecisionContext:
    config = Config(irreversible_requires_human=True, **cfg)
    return DecisionContext(now=1.0, system_state="running", posture=Posture(level="guarded", baseline="guarded"),
                           config=config, tool=registry.info_for(proposal.tool, proposal.reversibility))


def _registry(*payloads) -> ToolRegistry:
    reg = ToolRegistry()
    for p in payloads:
        reg.note(p)
    return reg


class TheRegistrationBeatsTheClaim(unittest.IsolatedAsyncioTestCase):
    async def test_a_read_only_claim_for_an_irreversible_tool_still_reaches_a_person(self):
        reg = _registry(RUN_SHELL)
        proposal = _proposal("run_shell", {"command": "make clean"}, claimed="read_only")
        verdict = await Pipeline(DEFAULT_PIPELINE).decide(proposal, _ctx(reg, proposal))
        self.assertEqual(verdict.kind, "needs_human")
        self.assertEqual(verdict.layer, "reversibility")
        self.assertTrue(any("registered irreversible" in n for n in verdict.notes), verdict.notes)

    async def test_the_same_claim_cannot_pass_plan_mode(self):
        reg = _registry(RUN_SHELL)
        proposal = _proposal("run_shell", {"command": "ls"}, claimed="read_only", task_mode="plan")
        verdict = await Pipeline(DEFAULT_PIPELINE).decide(proposal, _ctx(reg, proposal))
        self.assertEqual((verdict.kind, verdict.layer), ("denied", "mode"))

    async def test_a_proposer_may_tighten_but_never_loosen(self):
        reg = _registry(READ_FILE)
        info = reg.info_for("read_file", "irreversible")
        self.assertEqual(info.reversibility, "irreversible")
        self.assertEqual(reg.info_for("run_shell", "read_only").reversibility, "read_only")  # unregistered

    async def test_an_unregistered_tool_falls_back_to_the_claim_and_says_so(self):
        proposal = _proposal("mystery_tool", {"x": 1}, claimed="read_only")
        verdict = await Pipeline(DEFAULT_PIPELINE).decide(proposal, _ctx(ToolRegistry(), proposal))
        self.assertEqual(verdict.kind, "approved")
        self.assertTrue(any("not registered" in n for n in verdict.notes), verdict.notes)

    async def test_a_sandbox_registered_read_only_but_reversible_is_still_not_plan_mode_safe(self):
        reg = _registry({"name": "run_python_sandboxed", "reversibility": "reversible", "read_only": True,
                         "input_schema": {"type": "object", "required": ["code"],
                                          "properties": {"code": {"type": "string"}}}})
        proposal = _proposal("run_python_sandboxed", {"code": "print(1)"}, task_mode="plan")
        verdict = await Pipeline(DEFAULT_PIPELINE).decide(proposal, _ctx(reg, proposal))
        self.assertEqual((verdict.kind, verdict.layer), ("denied", "mode"))


class ArgumentsAreCheckedAgainstTheSchema(unittest.IsolatedAsyncioTestCase):
    async def test_a_missing_required_argument_is_denied_at_schema(self):
        reg = _registry(READ_FILE)
        proposal = _proposal("read_file", {}, claimed="read_only")
        verdict = await Pipeline(DEFAULT_PIPELINE).decide(proposal, _ctx(reg, proposal))
        self.assertEqual((verdict.kind, verdict.layer), ("denied", "schema"))
        self.assertTrue(any("$.path: required property missing" in r for r in verdict.reasons), verdict.reasons)

    async def test_a_list_where_a_path_string_belongs_is_denied_before_protected_reads_it(self):
        reg = _registry(WRITE_NOTE)
        proposal = _proposal("mcp_fs_write_note", {"file_path": ["docs/SOUL.md"], "content": "x"})
        verdict = await Pipeline(DEFAULT_PIPELINE).decide(proposal, _ctx(reg, proposal))
        self.assertEqual((verdict.kind, verdict.layer), ("denied", "schema"))

    async def test_extra_arguments_are_tolerated(self):
        reg = _registry(READ_FILE)
        proposal = _proposal("read_file", {"path": "README.md", "lines": "1-20"}, claimed="read_only")
        decision = await SchemaRule().evaluate(proposal, _ctx(reg, proposal))
        self.assertEqual(decision.kind, "abstain")

    def test_marker_shapes_that_work_today_still_pass(self):
        """Each of these is what the marker dialect sends and the tool
        accepts; every one failed the schema as declared."""
        cases = [
            ("cast_volume", {"level": "35 Bedroom"},
             {"type": "object", "required": ["level"], "properties": {"level": {"type": "number"}}}),
            ("cam_watch", {"on": "off"}, {"type": "object", "properties": {"on": {"type": "boolean"}}}),
            ("cam_ptz", {"camera": "front left"},
             {"type": "object", "required": ["camera", "command"],
              "properties": {"camera": {"type": "string"}, "command": {"type": "string"}}}),
            ("media_play", {"what": "jazz"},
             {"type": "object", "required": ["what", "where"],
              "properties": {"what": {"type": "string"}, "where": {"type": "string"}}}),
            ("browse_page", {"target": "https://x", "actions": "click a"},
             {"type": "object", "required": ["target"],
              "properties": {"target": {"type": "string"}, "actions": {"type": "array"}}}),
            ("memory_forget", {"minutes": "2"}, {"type": "object", "properties": {"minutes": {"type": "number"}}}),
            ("music_control", {"op": "Pause"},
             {"type": "object", "required": ["op"], "properties": {"op": {"enum": ["pause", "play"]}}}),
        ]
        for tool, args, schema in cases:
            with self.subTest(tool=tool):
                self.assertEqual(schema_errors(tool, args, schema), ([], None))

    def test_a_tool_without_a_marker_shape_keeps_its_whole_required_list(self):
        schema = {"type": "object", "required": ["a", "b"], "properties": {}}
        self.assertEqual(enforced_schema("some_mcp_tool", schema)["required"], ["a", "b"])

    def test_a_malformed_schema_is_a_note_not_a_denial(self):
        errors, note = schema_errors("t", {"x": 1}, {"type": "object", "properties": {"x": {"type": "bogus"}}})
        self.assertEqual(errors, [])
        self.assertIn("could not be checked", note)


class ThePathComesFromTheSchema(unittest.IsolatedAsyncioTestCase):
    def test_the_schema_names_its_file_arguments(self):
        self.assertEqual(schema_subject_keys(WRITE_NOTE["input_schema"]), ("file_path",))
        self.assertEqual(schema_subject_keys({"type": "object", "properties": {"n": {"type": "integer"}}}), ())

    async def test_a_protected_path_under_a_schema_known_key_is_caught(self):
        reg = _registry(WRITE_NOTE)
        proposal = _proposal("mcp_fs_write_note", {"file_path": "simorgh/guardian/rules.py", "content": "x"})
        decision = await ProtectedRule().evaluate(proposal, _ctx(reg, proposal))
        self.assertEqual(decision.kind, "deny")
        self.assertIn("simorgh/guardian/", decision.reasons[0])

    async def test_the_same_key_was_invisible_to_the_old_guess(self):
        proposal = _proposal("mcp_fs_write_note", {"file_path": "simorgh/guardian/rules.py", "content": "x"})
        decision = await ProtectedRule().evaluate(proposal, _ctx(ToolRegistry(), proposal))
        self.assertEqual(decision.kind, "abstain")

    async def test_a_web_url_is_not_a_protected_path_but_a_climbing_one_is(self):
        reg = _registry({"name": "browse_page", "reversibility": "reversible", "read_only": False,
                         "input_schema": {"type": "object", "properties": {"target": {"type": "string"}}}})
        ok = _proposal("browse_page", {"target": "https://github.com/x/Simorgh/blob/main/simorgh/kernel/cli.py"})
        self.assertEqual((await ProtectedRule().evaluate(ok, _ctx(reg, ok))).kind, "abstain")
        bad = _proposal("browse_page", {"target": "https://../simorgh/kernel/cli.py"})
        self.assertEqual((await ProtectedRule().evaluate(bad, _ctx(reg, bad))).kind, "deny")

    async def test_denylist_diffs_against_the_schema_known_subject(self):
        """An existing file's untouched lines are not rescanned: the diff
        baseline is found through the schema's own key."""
        reg = _registry({"name": "mcp_fs_rewrite", "reversibility": "reversible", "read_only": False,
                         "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"},
                                                                           "code": {"type": "string"}}}})
        from simorgh.guardian import rules
        existing = rules._existing_text("tools/trial.py")  # noqa: SLF001 -- a real file with subprocess.run in it
        self.assertIsNotNone(existing)
        proposal = _proposal("mcp_fs_rewrite", {"file_path": "tools/trial.py", "code": existing + "\n# a comment\n"})
        self.assertEqual((await DenylistRule().evaluate(proposal, _ctx(reg, proposal))).kind, "abstain")
        # Unregistered, `file_path` is not a key the old guess knows: the
        # whole body is scanned and its existing subprocess call denied.
        self.assertEqual((await DenylistRule().evaluate(proposal, _ctx(ToolRegistry(), proposal))).kind, "deny")


# -- the Service end to end ---------------------------------------------------

class _Bus:
    """Validates every publish the way the real bus does, so a verdict
    that could not reach anyone fails here too."""

    def __init__(self):
        self.handlers: dict[str, list] = {}
        self.published: list[Message] = []

    async def subscribe(self, topic, handler, group=None):
        self.handlers.setdefault(topic, []).append(handler)
        return SimpleNamespace(unsubscribe=_noop)

    async def publish(self, message):
        validate(message)
        self.published.append(message)

    async def deliver(self, message):
        for handler in self.handlers.get(message.type, []):
            await handler(message)


async def _noop():
    return None


class _Ledger:
    inline_threshold = 4096

    def __init__(self, events=()):
        self.events = list(events)

    async def read(self, stream, **kw):
        return [e for e in self.events if e.stream == stream]

    async def append(self, stream, event):
        self.events.append(event)


async def _started(ledger_events=()):
    bus, ledger = _Bus(), _Ledger(ledger_events)
    svc = Service(config=Config(irreversible_requires_human=True))
    ctx = SimpleNamespace(bus=bus, ledger=ledger, secrets={"__hmac__": "00" * 32},
                          clock=SimpleNamespace(now=lambda: 1000.0), telemetry=None)
    await svc.start(ctx)
    return svc, bus


def _registered(payload):
    body = {"version": "1", "description": "", "schema_ref": "", "provider": "builtin", **payload}
    return Message.new(topics.TOOL_REGISTERED, source="execution", payload=body)


def _proposed(tool, args, claimed):
    return Message.new(topics.ACTION_PROPOSED, source="orchestration", payload={
        "action_id": f"act-{tool}-{len(args)}", "tool": tool, "args": args, "scope": {},
        "reversibility": claimed, "rationale": "t", "proposed_by": "orchestration"})


class TheServiceUsesTheRegistry(unittest.IsolatedAsyncioTestCase):
    async def test_a_read_only_claim_for_a_registered_irreversible_tool_asks_a_person(self):
        svc, bus = await _started()
        await bus.deliver(_registered(RUN_SHELL))
        await bus.deliver(_proposed("run_shell", {"command": "make clean"}, "read_only"))
        self.assertIn(topics.ACTION_NEEDS_HUMAN, [m.type for m in bus.published])
        self.assertNotIn(topics.ACTION_APPROVED, [m.type for m in bus.published])

    async def test_a_schema_denial_reaches_the_proposer(self):
        svc, bus = await _started()
        await bus.deliver(_registered(READ_FILE))
        await bus.deliver(_proposed("read_file", {}, "read_only"))
        denied = [m for m in bus.published if m.type == topics.ACTION_DENIED]
        self.assertEqual(len(denied), 1)
        self.assertEqual(denied[0].payload["layer"], "policy")  # the wire enum has no `schema`
        self.assertTrue(any("schema" in r for r in denied[0].payload["reasons"]))

    async def test_registrations_made_before_guardian_subscribed_are_replayed(self):
        record = Event(stream=TOOLS_STREAM, type="registered", ts=1.0, trace_id="", causation_id=None,
                       payload={"name": "run_shell", "provider": "builtin", "reversibility": "irreversible",
                                "read_only": False})
        svc, bus = await _started([record])
        await bus.deliver(_proposed("run_shell", {"command": "ls"}, "read_only"))
        self.assertIn(topics.ACTION_NEEDS_HUMAN, [m.type for m in bus.published])

    async def test_a_live_registration_is_not_overwritten_by_an_older_record(self):
        reg = ToolRegistry()
        reg.note(READ_FILE, live=True)
        reg.note({"name": "read_file", "reversibility": "irreversible", "read_only": False}, live=False)
        self.assertEqual(reg.get("read_file")["reversibility"], "read_only")

    async def test_every_pipeline_layer_can_be_published(self):
        """`static_analysis`, `package`, `grant`, `human_only` and
        `physical` denials failed contract validation on publish before
        2026-09-19 and reached nobody."""
        from simorgh.guardian.service import _wire_layer

        for rule in DEFAULT_PIPELINE:
            with self.subTest(layer=rule.layer):
                validate(Message.new(topics.ACTION_DENIED, source="guardian", payload={
                    "action_id": "a", "reasons": [], "layer": _wire_layer(rule.layer), "tool": "t"}))


if __name__ == "__main__":
    unittest.main()

"""Stage 18 item 8: `contracts/a2a.py` writes what the A2A spec accepts and
reads back exactly what it wrote, in both pinned wire versions, and reads
a Task or Message from an agent that is not Sim.

The schemas are the spec's own, vendored under `fixtures/a2a/` with their
versions pinned (see the README there). The validator below is a test-side
JSON Schema subset with `$ref` resolution, because the package's own
validator has no `$ref` and the v1.0.1 bundle's refs name unbundled files.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from simorgh.contracts import a2a
from simorgh.contracts.messages import crew

pytestmark = pytest.mark.contract

FIXTURES = Path(__file__).parent / "fixtures" / "a2a"
SCHEMA_FILES = {"1.0": "a2a-v1.0.1.json", "0.3": "a2a-v0.3.0.json"}
SHA256 = {
    "a2a-v1.0.1.json": "ba4b702b5edbdcbfe972c272484eb38e1fcd72af3c0b7eaa114b50e97455d8dd",
    "a2a-v0.3.0.json": "97d6e2435336836cd1d41dffacf83a1a97902b62b826ef14ec5704db85c95f17",
}


# --- a small validator for the spec's own schemas ------------------------------


class Spec:
    def __init__(self, version: str) -> None:
        self.doc = json.loads((FIXTURES / SCHEMA_FILES[version]).read_text(encoding="utf-8"))
        defs = self.doc.get("$defs") or self.doc["definitions"]
        self.defs = {name.replace(" ", ""): schema for name, schema in defs.items()}

    def schema(self, name: str) -> dict:
        return self.defs[name]

    def resolve(self, ref: str) -> dict:
        if ref.startswith("#/"):
            return self.defs[ref.rsplit("/", 1)[1].replace(" ", "")]
        # v1.0.1: "lf.a2a.v1.TaskStatus.jsonschema.json", "google.protobuf.Struct.jsonschema.json"
        return self.defs[ref.removesuffix(".jsonschema.json").rsplit(".", 1)[1]]

    def errors(self, value, schema: dict, path: str = "$") -> list[str]:
        if "$ref" in schema:
            return self.errors(value, self.resolve(schema["$ref"]), path)
        out: list[str] = []
        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_is(value, t) for t in types):
                return [f"{path}: {value!r} is not {types}"]
        if "enum" in schema and value not in schema["enum"]:
            out.append(f"{path}: {value!r} not in enum")
        if "const" in schema and value != schema["const"]:
            out.append(f"{path}: {value!r} != const {schema['const']!r}")
        if "pattern" in schema and isinstance(value, str) and not re.search(schema["pattern"], value):
            out.append(f"{path}: {value!r} does not match {schema['pattern']}")
        for key, test in (("minimum", lambda v, m: v >= m), ("maximum", lambda v, m: v <= m)):
            if key in schema and _is(value, "number") and not test(value, schema[key]):
                out.append(f"{path}: {value} breaks {key}")
        for key in ("anyOf", "oneOf"):
            if key in schema:
                ok = [b for b in schema[key] if not self.errors(value, b, path)]
                if not ok or (key == "oneOf" and len(ok) != 1):
                    out.append(f"{path}: {key} matched {len(ok)} branches")
        for branch in schema.get("allOf", ()):
            out += self.errors(value, branch, path)
        if isinstance(value, dict):
            for name in schema.get("required", ()):
                if name not in value:
                    out.append(f"{path}: missing {name}")
            props = schema.get("properties", {})
            patterns = schema.get("patternProperties", {})
            extra = schema.get("additionalProperties", True)
            for key, item in value.items():
                matched = False
                if key in props:
                    matched = True
                    out += self.errors(item, props[key], f"{path}.{key}")
                for pattern, sub in patterns.items():
                    if re.search(pattern, key):
                        matched = True
                        out += self.errors(item, sub, f"{path}.{key}")
                if not matched:
                    if extra is False:
                        out.append(f"{path}: unexpected key {key!r}")
                    elif isinstance(extra, dict):
                        out += self.errors(item, extra, f"{path}.{key}")
        if isinstance(value, list) and isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                out += self.errors(item, schema["items"], f"{path}[{i}]")
        return out

    def check(self, value, name: str) -> None:
        problems = self.errors(value, self.schema(name))
        assert not problems, problems


def _is(value, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "null":
        return value is None
    return False


@pytest.fixture(scope="module", params=a2a.A2A_VERSIONS)
def spec(request) -> tuple[str, Spec]:
    return request.param, Spec(request.param)


# --- shapes --------------------------------------------------------------------


def _member(status: str = "running") -> crew.Member:
    return crew.Member("t-2", "research", parent="t-1", depth=2, status=status,
                       budget=crew.MemberBudget(steps=20, tokens=9000, usd=0.05, wall_s=180),
                       report_policy="every_steps:5", isolation="fork", crew_id="t-1")


def _report(status: str = "ok") -> crew.Report:
    return crew.Report(status=status, summary="Dishwasher A is 499 at two shops.",
                       findings=(crew.Finding("499 at shop 1", "blob:e1"), crew.Finding("499 at shop 2")),
                       artifacts=("blob:table", "workspace/notes.md"), steps=6, tokens=5100,
                       cost_usd=0.011, wall_s=42.0, questions_unanswered=("delivery?",))


def _message(kind: str, **over) -> dict:
    return {"crew_id": "t-1", "from": "t-2", "to": "t-1", "kind": kind, "body": f"a {kind}",
            "seq": 4, "refs": ["blob:r1"], "reply_to": 3, **over}


class TestFixtures:
    def test_the_vendored_schemas_are_the_pinned_ones(self):
        for name, digest in SHA256.items():
            assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest, name
        readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
        for name, digest in SHA256.items():
            assert name in readme and digest in readme

    def test_the_validator_is_not_vacuous(self, spec):
        version, s = spec
        task = a2a.to_a2a_task(_member(), version=version)
        s.check(task, "Task")
        broken = json.loads(json.dumps(task))
        broken["status"]["state"] = "pondering"
        assert s.errors(broken, s.schema("Task"))
        if version == "1.0":
            assert s.errors({**task, "kind": "task"}, s.schema("Task"))     # additionalProperties: false
        else:
            assert s.errors({k: v for k, v in task.items() if k != "kind"}, s.schema("Task"))


class TestTask:
    @pytest.mark.parametrize("status", crew.MEMBER_STATUS)
    def test_every_status_round_trips_and_is_a_spec_state(self, spec, status):
        version, s = spec
        member = _member(status)
        task = a2a.to_a2a_task(member, version=version)
        s.check(task, "Task")
        back, report = a2a.from_a2a_task(task)
        assert back == member
        # A terminal task with no artifacts still reads as a report: the state's.
        assert (report is None) == (not crew.is_terminal(status))

    @pytest.mark.parametrize("status", crew.REPORT_STATUS)
    def test_member_with_report_round_trips(self, spec, status):
        version, s = spec
        member, report = _member("done"), _report(status)
        task = a2a.to_a2a_task(member, report, version=version)
        s.check(task, "Task")
        assert a2a.from_a2a_task(task) == (member, report)

    def test_dicts_are_accepted_like_the_dataclasses(self, spec):
        version, _ = spec
        assert (a2a.to_a2a_task(_member().to_dict(), _report().to_dict(), version=version)
                == a2a.to_a2a_task(_member(), _report(), version=version))

    def test_waiting_is_input_required(self):
        assert a2a.task_state("waiting", "0.3") == "input-required"
        assert a2a.task_state("waiting", "1.0") == "TASK_STATE_INPUT_REQUIRED"
        for state in ("input-required", "TASK_STATE_INPUT_REQUIRED", 6):
            assert a2a.member_status(state) == "waiting"

    def test_states_sim_cannot_say_read_as_the_nearest(self):
        assert a2a.member_status("auth-required") == "blocked"
        assert a2a.member_status("TASK_STATE_AUTH_REQUIRED") == "blocked"
        assert a2a.member_status("TASK_STATE_UNSPECIFIED") == "running"
        assert a2a.member_status("unknown") == "running"
        assert a2a.member_status(99) == "running"

    def test_bad_inputs_are_refused_by_name(self):
        with pytest.raises(ValueError, match="2.0"):
            a2a.to_a2a_task(_member(), version="2.0")
        with pytest.raises(ValueError, match="zombie"):
            a2a.task_state("zombie")


class TestForeignTask:
    """Tasks an agent that is not Sim might send, written by hand to the spec."""

    def test_completed_v1_task(self):
        task = {"id": "remote-9", "contextId": "ctx-1",
                "status": {"state": "TASK_STATE_COMPLETED", "timestamp": "2026-10-27T10:00:00Z"},
                "artifacts": [{"artifactId": "a1", "name": "answer",
                               "parts": [{"text": "Delivery on Friday."},
                                         {"url": "https://example.com/r.pdf", "mediaType": "application/pdf"}]}]}
        Spec("1.0").check(task, "Task")
        member, report = a2a.from_a2a_task(task, parent="t-1")
        assert (member.handle, member.agent, member.parent, member.status, member.crew_id) == \
            ("remote-9", "a2a", "t-1", "done", "ctx-1")
        assert report == crew.Report(status="ok", summary="Delivery on Friday.",
                                     artifacts=("https://example.com/r.pdf",))

    def test_input_required_v03_task_has_no_report_yet(self):
        task = {"kind": "task", "id": "r1", "contextId": "c",
                "status": {"state": "input-required",
                           "message": {"kind": "message", "messageId": "m1", "role": "agent",
                                       "parts": [{"kind": "text", "text": "Which colour?"}]}}}
        Spec("0.3").check(task, "Task")
        member, report = a2a.from_a2a_task(task)
        assert member.status == "waiting" and report is None

    def test_failed_task_without_artifacts_reports_its_status_message(self):
        task = {"id": "r2", "contextId": "c",
                "status": {"state": "TASK_STATE_FAILED",
                           "message": {"messageId": "m", "role": "ROLE_AGENT", "parts": [{"text": "site down"}]}}}
        Spec("1.0").check(task, "Task")
        _, report = a2a.from_a2a_task(task)
        assert (report.status, report.summary) == ("failed", "site down")

    def test_a_long_foreign_summary_is_cut_to_the_cap(self):
        task = {"id": "r3", "contextId": "c", "status": {"state": "TASK_STATE_COMPLETED"},
                "artifacts": [{"artifactId": "a", "parts": [{"text": "w " * 2000}]}]}
        _, report = a2a.from_a2a_task(task)
        assert len(report.summary) == crew.SUMMARY_MAX
        assert crew.validate_report(report) == []

    def test_rejected_is_blocked_and_canceled_is_cancelled(self):
        for state, member_status, report_status in (("rejected", "blocked", "blocked"),
                                                    ("canceled", "cancelled", "cancelled")):
            member, report = a2a.from_a2a_task({"id": "r", "contextId": "c", "status": {"state": state}})
            assert (member.status, report.status) == (member_status, report_status)


class TestMessage:
    @pytest.mark.parametrize("kind", crew.MESSAGE_KIND)
    def test_every_kind_round_trips(self, spec, kind):
        version, s = spec
        payload = _message(kind)
        message = a2a.to_a2a_message(payload, version=version)
        s.check(message, "Message")
        back = a2a.from_a2a_message(message)
        assert back.to_payload() == payload

    def test_optional_fields_stay_absent(self, spec):
        version, s = spec
        payload = {k: v for k, v in _message("note").items() if k not in ("refs", "reply_to")}
        message = a2a.to_a2a_message(payload, version=version)
        s.check(message, "Message")
        assert a2a.from_a2a_message(message).to_payload() == payload

    def test_the_dataclass_is_accepted(self):
        from simorgh.contracts.registry import get_spec
        msg = get_spec("crew.message").dataclass.from_payload(_message("steer"))
        assert a2a.to_a2a_message(msg) == a2a.to_a2a_message(_message("steer"))

    def test_role_is_the_working_members_side(self):
        progress = a2a.to_a2a_message(_message("progress"))
        steer = a2a.to_a2a_message(_message("steer", **{"from": "t-1", "to": "t-2"}))
        assert (progress["role"], progress["taskId"]) == ("ROLE_AGENT", "t-2")
        assert (steer["role"], steer["taskId"]) == ("ROLE_USER", "t-2")
        assert a2a.to_a2a_message(_message("question"), version="0.3")["role"] == "agent"

    def test_a_bad_kind_is_refused(self):
        with pytest.raises(ValueError, match="gossip"):
            a2a.to_a2a_message(_message("gossip"))


class TestForeignMessage:
    def test_agent_message_is_progress_from_its_task(self):
        message = {"kind": "message", "messageId": "m1", "role": "agent", "taskId": "r1", "contextId": "c",
                   "parts": [{"kind": "text", "text": "Found two shops."},
                             {"kind": "data", "data": {"shops": 2}},
                             {"kind": "file", "file": {"uri": "https://example.com/a.html"}}]}
        Spec("0.3").check(message, "Message")
        back = a2a.from_a2a_message(message, parent="t-1", seq=7).to_payload()
        assert back == {"crew_id": "c", "from": "r1", "to": "t-1", "kind": "progress",
                        "body": 'Found two shops.\n{"shops":2}', "seq": 7,
                        "refs": ["https://example.com/a.html"]}

    def test_user_message_is_a_steer_to_its_task_and_kind_overrides(self):
        message = {"messageId": "m2", "role": "ROLE_USER", "taskId": "r1", "parts": [{"text": "Only red."}]}
        Spec("1.0").check(message, "Message")
        back = a2a.from_a2a_message(message, crew_id="t-1", parent="t-1")
        assert (back.from_, back.to, back.kind, back.crew_id) == ("t-1", "r1", "steer", "t-1")
        question = a2a.from_a2a_message({**message, "role": "ROLE_AGENT"}, parent="t-1", kind="question")
        assert (question.from_, question.kind) == ("r1", "question")

"""Stage 18 item 1: the crew contracts -- four topics, the `Report` and
`Member` shapes, the report-policy grammar and the `crew:<id>` stream."""

from __future__ import annotations

import pytest

from simorgh.contracts import CATALOG, DOMAINS, ContractError, get_spec, topics, validate
from simorgh.contracts.messages import crew
from simorgh.contracts.registry import attr_name
from simorgh.contracts.streamnames import CREW_PREFIX, crew_stream, writers_for
from tests.simorgh.helpers import make_message

pytestmark = pytest.mark.contract

TOPICS = (topics.CREW_SPAWNED, topics.CREW_MESSAGE, topics.CREW_REPORT, topics.CREW_CANCEL)


def _report(**over) -> crew.Report:
    base = dict(status="ok", summary="A is 499, B is 549.",
                findings=(crew.Finding("A costs 499", "blob:aa"), crew.Finding("B costs 549")),
                artifacts=("blob:page-a",), steps=7, tokens=4200, cost_usd=0.012, wall_s=31.5,
                questions_unanswered=("which colour?",))
    base.update(over)
    return crew.Report(**base)


class TestTopics:
    def test_the_four_topics_are_catalogued_in_the_crew_domain(self):
        assert "crew" in DOMAINS
        for name in TOPICS:
            assert name in CATALOG
            assert topics.domain_of(name) == "crew"
            assert not name.endswith(".request")      # none needs a reply type

    def test_every_crew_topic_validates_as_a_message(self):
        for name in TOPICS:
            validate(make_message(name, source="orchestration", include_optional=True))

    def test_message_kinds_and_statuses_are_the_plans(self):
        assert crew.MESSAGE_KIND == ("progress", "milestone", "question", "answer", "steer", "note", "report")
        assert crew.MEMBER_STATUS == ("starting", "running", "waiting", "done", "failed", "blocked", "cancelled")
        assert crew.REPORT_STATUS == ("ok", "partial", "failed", "blocked", "cancelled")

    def test_crew_message_says_from_on_the_wire_and_from__in_python(self):
        spec = get_spec(topics.CREW_MESSAGE)
        payload = {"crew_id": "t1", "from": "t2", "to": "t1", "kind": "question",
                   "body": "which colour?", "seq": 3, "refs": ["blob:x"], "reply_to": 2}
        msg = spec.dataclass.from_payload(payload)
        assert msg.from_ == "t2"
        assert msg.to_payload() == payload
        assert "from" in spec.schema["required"] and "from_" not in spec.schema["properties"]
        assert attr_name("from") == "from_" and attr_name("body") == "body"

    def test_an_unknown_kind_is_refused(self):
        spec = get_spec(topics.CREW_MESSAGE)
        with pytest.raises(ContractError):
            spec.build(crew_id="c", from_="a", to="b", kind="gossip", body="", seq=1)

    def test_crew_report_carries_the_typed_report(self):
        spec = get_spec(topics.CREW_REPORT)
        payload = {"crew_id": "c", "handle": "t2", "report": _report().to_dict()}
        assert spec.validate(payload) == []
        bad = {**payload, "report": {**payload["report"], "status": "done"}}
        assert spec.validate(bad)

    def test_spawned_and_cancel_shapes(self):
        spawned = get_spec(topics.CREW_SPAWNED).build(
            crew_id="c", handle="t2", parent="c", agent="research", brief_ref="blob:brief",
            report_policy="every_steps:5", budget=crew.MemberBudget(steps=20, usd=0.1).to_dict(),
            depth=1, isolation="fresh", background=False)
        assert spawned.to_payload()["budget"] == {"steps": 20, "usd": 0.1}
        cancel = get_spec(topics.CREW_CANCEL).build(crew_id="c", handle="t2", reason="crew budget")
        assert cancel.cascade is None             # absent means cascade


class TestReport:
    def test_round_trip(self):
        r = _report()
        assert crew.Report.from_dict(r.to_dict()) == r
        assert crew.validate_report(r) == []

    def test_caps_keep_it_a_conclusion(self):
        long = _report(summary="x" * (crew.SUMMARY_MAX + 1))
        assert any("summary" in p for p in crew.validate_report(long))
        many = _report(findings=tuple(crew.Finding(f"c{i}") for i in range(crew.FINDINGS_MAX + 1)))
        assert any("findings" in p for p in crew.validate_report(many))
        assert crew.validate_report({"status": "done", "summary": ""})

    def test_a_minimal_report_reads(self):
        r = crew.Report.from_dict({"status": "partial", "summary": "half"})
        assert (r.findings, r.artifacts, r.steps) == ((), (), 0)


class TestMember:
    def test_round_trip_and_validation(self):
        m = crew.Member("t2", "research", parent="t1", depth=2, status="waiting",
                        budget=crew.MemberBudget(steps=10, wall_s=60), report_policy="milestones",
                        isolation="fork", crew_id="t1")
        assert crew.Member.from_dict(m.to_dict()) == m
        assert crew.validate_member(m) == []
        assert crew.validate_member(crew.Member("", "x", status="zombie", report_policy="loud"))

    def test_terminal_statuses(self):
        assert [s for s in crew.MEMBER_STATUS if crew.is_terminal(s)] == ["done", "failed", "blocked", "cancelled"]


class TestReportPolicy:
    @pytest.mark.parametrize("text,expected", [
        ("end", ("end", 0)), ("", ("end", 0)), ("progress", ("progress", 0)),
        ("every_steps:5", ("every_steps", 5)), ("every_s:30", ("every_s", 30.0)),
        ("milestones", ("milestones", 0)), ("silent", ("silent", 0)),
    ])
    def test_accepted(self, text, expected):
        assert crew.parse_report_policy(text) == expected

    @pytest.mark.parametrize("text", ["loud", "every_steps", "every_steps:0", "every_s:-1",
                                      "every_steps:two", "end:3"])
    def test_refused(self, text):
        with pytest.raises(ValueError):
            crew.parse_report_policy(text)


class TestStream:
    def test_crew_stream_name(self):
        assert crew_stream("t-1f3a") == "crew:t-1f3a"
        assert CREW_PREFIX == "crew:"
        for bad in ("", "Has/Slash", "x" * 130):
            with pytest.raises(ValueError):
                crew_stream(bad)

    def test_only_orchestration_writes_a_crew(self):
        assert writers_for("crew:t-1") == frozenset({"orchestration"})

    def test_stream_event_types(self):
        assert set(TOPICS) <= set(crew.STREAM_EVENTS)
        assert crew.MEMBER_STATUS_CHANGED not in CATALOG and crew.BOARD not in CATALOG

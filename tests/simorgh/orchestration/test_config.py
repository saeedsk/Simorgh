"""`[orchestration]` has no `lease_seconds`.

The key was declared and never read: the lease is Planning's, carried on
every `task.available`. Removing it means writing it is reported as a
section that changed nothing, instead of silently looking like a setting
(docs/findings/2026-09-19-contract-writing.md)."""

from simorgh.kernel.configcheck import dead_sections
from simorgh.orchestration.config import Config


class _Loaded:
    def __init__(self, raw: dict) -> None:
        self.raw = raw

    def section(self, name: str) -> dict:
        return dict(self.raw.get(name, {}))


def test_orchestration_has_no_lease_seconds_field():
    assert "lease_seconds" not in Config.__dataclass_fields__


def test_writing_lease_seconds_under_orchestration_is_reported_dead():
    assert dead_sections(_Loaded({"orchestration": {"lease_seconds": 30}}), names=["orchestration"]) == [
        "orchestration"]


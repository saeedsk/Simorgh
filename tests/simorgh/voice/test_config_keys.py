"""`[voice]` declares only keys that do something.

`overheard_hours` parsed into the Config and nothing read it: the
overheard store (`contracts/overheard.py`) keeps `MAX_AGE_S` whoever
writes to it. It was removed rather than left looking like a setting
(docs/findings/2026-09-19-contract-writing.md)."""

from simorgh.contracts import overheard
from simorgh.voice.config import Config


def test_there_is_no_overheard_hours_setting():
    assert "overheard_hours" not in Config.__dataclass_fields__
    assert Config.from_mapping({"overheard_hours": 1.0}) == Config()


def test_the_store_keeps_its_own_two_days():
    assert overheard.MAX_AGE_S == 48 * 3600.0

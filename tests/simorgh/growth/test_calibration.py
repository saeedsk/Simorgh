"""Tests for simorgh/growth/calibration.py."""

import json

from simorgh.growth.calibration import CalibrationTable, attach_estimator


def test_record_and_delta_overconfident():
    t = CalibrationTable()
    for _ in range(8):
        t.record("patch", 0.88, True)
    for _ in range(2):
        t.record("patch", 0.88, False)
    assert t.samples("patch") == 10
    assert abs(t.stated_mean("patch") - 0.88) < 1e-9
    assert abs(t.empirical_rate("patch") - 0.8) < 1e-9
    delta = t.delta("patch")
    assert delta is not None and abs(delta - 0.08) < 1e-9


def test_delta_underconfident_and_none():
    t = CalibrationTable()
    t.record("research", 0.4, True)
    assert t.delta("research") < 0
    assert t.delta("missing") is None
    assert t.correction_factor("missing") is None


def test_correction_factor_shrinks_toward_empirical():
    t = CalibrationTable()
    for _ in range(100):
        for _ in range(12):
            t.record("patch", 0.88, False)
    # empirical ~0.25 vs stated 0.88 -> factor well below 1
    f = t.correction_factor("patch")
    assert f is not None and 0.0 < f < 0.6


def test_correction_factor_grows_with_samples():
    few = CalibrationTable()
    many = CalibrationTable()
    for _ in range(2):
        few.record("a", 0.9, False)
    for _ in range(50):
        many.record("a", 0.9, False)
    ff, fm = few.correction_factor("a"), many.correction_factor("a")
    assert fm < ff


def test_record_validates_confidence():
    t = CalibrationTable()
    try:
        t.record("x", 1.5, True)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_bus_publish_and_json_roundtrip():
    sent = []

    class Bus:
        def publish(self, topic, payload):
            sent.append((topic, payload))

    t = CalibrationTable(bus=Bus())
    t.record("patch", 0.8, True)
    assert sent and sent[0][0] == "learn:calibration"
    raw = t.to_json()
    t2 = CalibrationTable()
    t2.load_json(raw)
    assert t2.samples("patch") == 1
    json.loads(raw)


def test_attach_estimator():
    t = CalibrationTable()
    for _ in range(20):
        t.record("patch", 0.9, False)

    class Est:
        pass

    e = Est()
    attach_estimator(t, e)
    assert e.calibration_correction("patch") < 1.0
    assert e.calibration_correction("unknown") == 1.0

    hooked = []
    e2 = Est()

    def hook(fn):
        hooked.append(fn)

    e2.set_calibration_hook = hook
    attach_estimator(t, e2, area_of=lambda tt: tt)
    assert hooked and hooked[0]("patch") < 1.0

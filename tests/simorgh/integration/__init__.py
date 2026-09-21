"""Integration tests: the real Kernel, booted."""


def assert_up(test, holder, name: str) -> None:
    """A subsystem is up: `ok`, or `degraded` for a reason that is
    about the MACHINE rather than the code.

    The Ledger reports `degraded` when the volume is under 5% free,
    which is a true and useful thing to say and has nothing to do
    with whether it booted. On 2026-09-20 the creator's disk crossed
    that line and two boot tests went red -- reading, to anyone who
    saw them, as though the Kernel had broken. A test that fails
    because the laptop is full is measuring the laptop.

    Anything else degraded, and anything `down`, still fails: those
    are the states this assertion exists for.
    """
    status = holder.status
    if status == "ok":
        return
    detail = str(getattr(holder, "detail", "") or getattr(holder, "note", "") or "")
    test.assertNotEqual(status, "down", f"{name} is down: {detail}")
    test.assertIn("free disk", detail,
                  f"{name} is {status} for a reason that is not the disk: {detail}")

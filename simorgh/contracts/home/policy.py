"""How dangerous is this service call?

A pure function, in contracts, so Guardian and the tool that proposes
the call compute the same answer from the same inputs -- and so
Guardian never has to trust a label the proposer supplied
(`home-automation-design.md` section 7).

The three classes:

- **`human`** -- a person decides, every time, whatever the
  auto-approve setting says. Unlocking a door, disarming an alarm,
  opening a garage, turning a camera off, disabling an automation, or
  a thermostat outside the range a house can survive. Also *anything*
  while the alarm is armed away: the house is in security mode and
  only a person changes that.
- **`reversible`** -- there is a prior state and it can be put back.
  Lights, switches, fans, media players, covers, climate inside the
  safe range.
- **`unattended`** -- reversible, and safe enough that a rule may do it
  with nobody watching.

`sim.sh` auto-approves irreversible actions by default. For the house
that default is wrong, and `human` here is meant to survive it.
"""

from __future__ import annotations

from typing import Literal

Class = Literal["unattended", "reversible", "human"]

#: Services that always wait for a person. Each one either lets someone
#: in, stops the house noticing that someone came in, or cannot be
#: undone by putting a state back.
ALWAYS_HUMAN_SERVICES: frozenset[str] = frozenset({
    "lock.unlock", "lock.open",
    "alarm_control_panel.alarm_disarm",
    "cover.open_cover",            # a garage door, most of the time
    "camera.turn_off", "camera.disable_motion_detection",
    "automation.turn_off", "automation.disable",
    "script.turn_off",
    "vacuum.send_command",
    "homeassistant.stop", "homeassistant.restart",
    "input_boolean.turn_off",      # commonly wired to a security mode
})

#: Domains a rule may act on with nobody watching.
UNATTENDED_DOMAINS: frozenset[str] = frozenset({
    "light", "switch", "fan", "media_player", "scene", "climate", "cover", "humidifier",
    "input_number", "input_select", "number", "select", "button",
})

#: Domains where a prior state can be put back.
REVERSIBLE_DOMAINS: frozenset[str] = UNATTENDED_DOMAINS | frozenset({"vacuum", "water_heater"})

#: Outside this, a thermostat is a hazard rather than a preference:
#: pipes freeze below it and people are harmed above it.
CLIMATE_HARD_LIMITS: tuple[float, float] = (10.0, 32.0)

#: Words in an entity id that mean "this is part of the security
#: system", whatever its domain says.
_SECURITY_WORDS = ("alarm", "siren", "security", "lock", "gate", "garage", "door_strike")


def classify_call(service: str, entity_id: str, *, device_class: str = "",
                  data: dict | None = None, alarm_state: str = "",
                  always_human: tuple[str, ...] = ()) -> Class:
    """The safety class of one service call on one entity.

    Deliberately pessimistic: an unrecognised domain is `human`, not
    `reversible`. A new HA integration should not be able to widen what
    Sim may do unattended just by existing.
    """
    service = (service or "").strip().lower()
    entity_id = (entity_id or "").strip().lower()
    domain = service.split(".", 1)[0] if "." in service else entity_id.split(".", 1)[0]
    data = data or {}

    if service in ALWAYS_HUMAN_SERVICES or service in {s.lower() for s in always_human}:
        return "human"

    # The house is in security mode. Nothing is routine while it is.
    if (alarm_state or "").lower().startswith("armed"):
        return "human"

    if any(word in entity_id for word in _SECURITY_WORDS):
        return "human"
    if device_class in ("garage", "door", "gate", "lock"):
        return "human"

    if domain == "climate":
        for key in ("temperature", "target_temp_high", "target_temp_low"):
            value = data.get(key)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                return "human"
            low, high = CLIMATE_HARD_LIMITS
            if not low <= number <= high:
                return "human"
        return "unattended"

    if domain in UNATTENDED_DOMAINS:
        return "unattended"
    if domain in REVERSIBLE_DOMAINS:
        return "reversible"
    return "human"


def reversibility_of(klass: Class) -> str:
    """The `_TOOL_POLICY` label for a class. `human` maps to
    `irreversible` because that is the label Guardian escalates on."""
    return {"unattended": "reversible", "reversible": "reversible"}.get(klass, "irreversible")


__all__ = ["ALWAYS_HUMAN_SERVICES", "CLIMATE_HARD_LIMITS", "Class", "REVERSIBLE_DOMAINS",
           "UNATTENDED_DOMAINS", "classify_call", "reversibility_of"]

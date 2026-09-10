"""What Home Assistant's model looks like to Sim.

HA's own model is already uniform -- `entity_id`, `state`, `attributes`
-- so these add almost nothing to it except a few derived properties
worth having in one place rather than re-derived at every call site.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Entity:
    entity_id: str
    state: str = ""
    attributes: dict = field(default_factory=dict)
    last_changed: str = ""

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]

    @property
    def object_id(self) -> str:
        return self.entity_id.split(".", 1)[-1]

    @property
    def name(self) -> str:
        return str(self.attributes.get("friendly_name") or
                   self.object_id.replace("_", " ").strip())

    @property
    def device_class(self) -> str:
        return str(self.attributes.get("device_class") or "")

    @property
    def area(self) -> str:
        """HA does not put the area in the state object, so this is a
        best guess from the friendly name until the registry
        WebSocket call is wired. It is used only for matching, never
        for a safety decision."""
        return str(self.attributes.get("area") or "")

    @property
    def available(self) -> bool:
        return self.state not in ("unavailable", "unknown", "")

    @property
    def numeric(self) -> float | None:
        try:
            return float(self.state)
        except (TypeError, ValueError):
            return None

    @property
    def unit(self) -> str:
        return str(self.attributes.get("unit_of_measurement") or "")

    def render(self) -> str:
        line = f"{self.entity_id}  {self.state}"
        if self.unit:
            line += f" {self.unit}"
        if self.name and self.name.lower() != self.object_id.replace("_", " "):
            line += f"  ({self.name})"
        if not self.available:
            line += "  [unavailable]"
        return line


@dataclass(frozen=True)
class ServiceResult:
    """What a service call actually did.

    `changed` is the point. HA answers 200 for a service call on a
    device that is unplugged, so "the call succeeded" and "the house
    did something" are different facts and only one of them is worth
    reporting.
    """

    service: str
    entities: tuple[str, ...] = ()
    before: dict = field(default_factory=dict)   # entity_id -> Entity
    after: dict = field(default_factory=dict)
    dry_run: bool = False

    @property
    def changed(self) -> tuple[str, ...]:
        out = []
        for entity_id, before in self.before.items():
            after = self.after.get(entity_id)
            if after is None:
                continue
            if after.state != before.state or after.attributes != before.attributes:
                out.append(entity_id)
        return tuple(out)

    @property
    def unchanged(self) -> tuple[str, ...]:
        return tuple(e for e in self.before if e not in self.changed)

    def render(self) -> str:
        lines = []
        for entity_id in self.entities:
            before = self.before.get(entity_id)
            after = self.after.get(entity_id)
            if before is None or after is None:
                lines.append(f"  {entity_id}: called")
                continue
            if entity_id in self.changed:
                lines.append(f"  {entity_id}: {before.state} -> {after.state}")
            else:
                lines.append(f"  {entity_id}: still {after.state} (nothing changed)")
        return "\n".join(lines)


__all__ = ["Entity", "ServiceResult"]

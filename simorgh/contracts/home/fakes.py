"""`FakeHomeAssistant`: a house in memory.

In `contracts/` rather than under `tests/` because Execution's tool
tests need it and may not import from the test tree
(`home-automation-design.md` section 2). It satisfies the same surface
as the real client, and it behaves like a real house in the two ways
that matter for correctness: a service call on an unavailable device
succeeds and changes nothing, and an unknown service is refused.
"""

from __future__ import annotations

from .api import Entity, ServiceResult
from .client import HomeUnavailable

#: What a small, plausible house looks like. Enough domains to exercise
#: the safety policy, the registry and the media tools.
DEFAULT_HOUSE: tuple[tuple[str, str, dict], ...] = (
    ("light.kitchen_main", "off", {"friendly_name": "Kitchen main", "brightness": 0}),
    ("light.living_room", "on", {"friendly_name": "Living room lamp", "brightness": 180}),
    ("switch.kettle", "off", {"friendly_name": "Kettle"}),
    ("switch.alarm_siren", "off", {"friendly_name": "Alarm siren"}),
    ("climate.hallway", "heat", {"friendly_name": "Hallway thermostat", "temperature": 20.0,
                                 "current_temperature": 18.5}),
    ("sensor.outside_temperature", "9.5", {"friendly_name": "Outside temperature",
                                            "unit_of_measurement": "°C",
                                            "device_class": "temperature"}),
    ("sensor.grid_import", "1234.5", {"friendly_name": "Grid import",
                                       "unit_of_measurement": "kWh", "device_class": "energy",
                                       "state_class": "total_increasing"}),
    ("sensor.solar_generation", "678.9", {"friendly_name": "Solar generation",
                                           "unit_of_measurement": "kWh", "device_class": "energy",
                                           "state_class": "total_increasing"}),
    ("sensor.house_power", "450", {"friendly_name": "House power",
                                    "unit_of_measurement": "W", "device_class": "power"}),
    ("lock.front_door", "locked", {"friendly_name": "Front door"}),
    ("alarm_control_panel.house", "disarmed", {"friendly_name": "House alarm"}),
    ("media_player.kitchen_echo", "idle", {"friendly_name": "Kitchen Echo",
                                            "volume_level": 0.3}),
    ("media_player.living_room_tv", "playing", {"friendly_name": "Living room TV",
                                                 "media_title": "The Bear",
                                                 "media_content_type": "tvshow",
                                                 "volume_level": 0.25}),
    ("cover.garage", "closed", {"friendly_name": "Garage door", "device_class": "garage"}),
    ("binary_sensor.front_motion", "off", {"friendly_name": "Front motion",
                                            "device_class": "motion"}),
    ("device_tracker.saeed_phone", "home", {"friendly_name": "Saeed's phone"}),
)

#: Services the fake house knows about, mirroring HA's own set.
DEFAULT_SERVICES: dict[str, set[str]] = {
    "light": {"turn_on", "turn_off", "toggle"},
    "switch": {"turn_on", "turn_off", "toggle"},
    "climate": {"set_temperature", "set_hvac_mode", "turn_on", "turn_off"},
    "lock": {"lock", "unlock", "open"},
    "alarm_control_panel": {"alarm_arm_home", "alarm_arm_away", "alarm_disarm"},
    "media_player": {"turn_on", "turn_off", "media_play", "media_pause", "media_stop",
                     "media_next_track", "media_previous_track", "volume_set", "volume_mute",
                     "play_media", "join", "unjoin"},
    "cover": {"open_cover", "close_cover", "stop_cover"},
    "scene": {"turn_on"},
    "notify": {"notify"},
    "homeassistant": {"turn_on", "turn_off"},
}


class FakeHomeAssistant:
    """The same surface as `HomeAssistantClient`, over a dict."""

    def __init__(self, entities=None, *, services=None, configured: bool = True,
                 dry_run: bool = False, unavailable: tuple[str, ...] = ()) -> None:
        rows = entities if entities is not None else DEFAULT_HOUSE
        self._entities: dict[str, Entity] = {}
        for row in rows:
            if isinstance(row, Entity):
                self._entities[row.entity_id] = row
            else:
                entity_id, state, attributes = row
                self._entities[entity_id] = Entity(entity_id, state, dict(attributes))
        self._services = dict(services if services is not None else DEFAULT_SERVICES)
        self._configured = configured
        self.dry_run = dry_run
        #: Devices that answer 200 and do nothing -- an unplugged bulb.
        self.unavailable = set(unavailable)
        self.url = "http://homeassistant.fake:8123"
        self.name = "home_assistant"
        self.needs = ("HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN")
        self.packages: tuple[str, ...] = ()
        self.calls: list[tuple[str, tuple[str, ...], dict]] = []

    @property
    def configured(self) -> bool:
        return self._configured

    def missing(self) -> tuple[str, ...]:
        return () if self._configured else ("HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN")

    async def probe(self):
        from ..connector import ConnectorStatus

        if not self._configured:
            return ConnectorStatus(False, "Home Assistant is not configured: set "
                                          "HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN",
                                   self.missing())
        return ConnectorStatus(True, f"home assistant is running at {self.url}")

    async def close(self) -> None:
        return None

    async def states(self) -> list[Entity]:
        self._require()
        return list(self._entities.values())

    async def state(self, entity_id: str) -> Entity | None:
        self._require()
        return self._entities.get(entity_id)

    async def services(self) -> dict[str, set[str]]:
        self._require()
        return {domain: set(names) for domain, names in self._services.items()}

    async def history(self, entity_id: str, *, hours: float = 24.0) -> list[dict]:
        self._require()
        entity = self._entities.get(entity_id)
        return [] if entity is None else [
            {"entity_id": entity_id, "state": entity.state, "attributes": entity.attributes}]

    async def call(self, service: str, *, entity_ids=(), data=None, settle_s: float = 0.0
                   ) -> ServiceResult:
        self._require()
        domain, _, name = service.partition(".")
        if name not in self._services.get(domain, set()):
            raise HomeUnavailable(f"Home Assistant has no service {service!r}")
        self.calls.append((service, tuple(entity_ids), dict(data or {})))
        before = {e: self._entities[e] for e in entity_ids if e in self._entities}
        if self.dry_run:
            return ServiceResult(service, tuple(entity_ids), before, dict(before), dry_run=True)
        for entity_id in entity_ids:
            entity = self._entities.get(entity_id)
            if entity is None or entity_id in self.unavailable:
                continue
            self._entities[entity_id] = _apply(entity, service, dict(data or {}))
        after = {e: self._entities[e] for e in entity_ids if e in self._entities}
        return ServiceResult(service, tuple(entity_ids), before, after)

    # -- helpers for tests ---------------------------------------------------

    def set_state(self, entity_id: str, state: str, **attributes) -> None:
        existing = self._entities.get(entity_id)
        merged = dict(existing.attributes) if existing else {}
        merged.update(attributes)
        self._entities[entity_id] = Entity(entity_id, state, merged)

    def _require(self) -> None:
        if not self._configured:
            raise HomeUnavailable("Home Assistant is not configured: set HOME_ASSISTANT_URL "
                                  "and HOME_ASSISTANT_TOKEN")


def _apply(entity: Entity, service: str, data: dict) -> Entity:
    """What a real house would do. Enough of it to make a `before ->
    after` comparison mean something."""
    domain, _, name = service.partition(".")
    attributes = dict(entity.attributes)
    state = entity.state

    if name == "turn_on":
        state = "on"
        if domain == "light":
            attributes["brightness"] = int(data.get("brightness", data.get("brightness_pct", 100)))
    elif name == "turn_off":
        state = "off"
        if domain == "light":
            attributes["brightness"] = 0
    elif name == "toggle":
        state = "off" if entity.state == "on" else "on"
    elif service == "climate.set_temperature":
        attributes["temperature"] = float(data.get("temperature", attributes.get("temperature", 20)))
    elif service == "climate.set_hvac_mode":
        state = str(data.get("hvac_mode", state))
    elif service == "lock.lock":
        state = "locked"
    elif service in ("lock.unlock", "lock.open"):
        state = "unlocked"
    elif service == "media_player.media_pause":
        state = "paused"
    elif service in ("media_player.media_play", "media_player.play_media"):
        state = "playing"
        if data.get("media_content_id"):
            attributes["media_title"] = str(data["media_content_id"])
    elif service == "media_player.media_stop":
        state = "idle"
    elif service == "media_player.volume_set":
        attributes["volume_level"] = float(data.get("volume_level", 0.3))
    elif service == "cover.open_cover":
        state = "open"
    elif service == "cover.close_cover":
        state = "closed"
    elif service.startswith("alarm_control_panel."):
        state = {"alarm_disarm": "disarmed", "alarm_arm_home": "armed_home",
                 "alarm_arm_away": "armed_away"}.get(name, state)
    return Entity(entity.entity_id, state, attributes)


__all__ = ["DEFAULT_HOUSE", "DEFAULT_SERVICES", "FakeHomeAssistant"]

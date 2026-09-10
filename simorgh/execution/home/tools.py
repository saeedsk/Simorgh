"""`home_find`, `home_state`, `home_describe`, `home_call`, `home_undo`.

`home_call` is the one that matters, and its shape is set by two rules
from the design:

**Ambiguity is refused, never guessed.** A target matching four
different things is a coin flip that turns the wrong one on.

**Report what the house did, not what HA accepted.** Home Assistant
answers 200 for a service call on a device that is unplugged. A tool
that said "turned the kitchen light on" when nothing happened is the
"succeeds while saying nothing true" failure, in the one place where a
person can walk into the room and see that it is a lie.

Safety is computed by `contracts/home/policy.py::classify_call`, which
Guardian imports too -- so the label the tool proposes and the label
Guardian enforces come from one function rather than two that can
drift. Anything classed `human` is proposed as `irreversible`, which
is what Guardian escalates on.
"""

from __future__ import annotations

import json
import os
import time

from simorgh.contracts.home.api import Entity
from simorgh.contracts.home.client import HomeAssistantClient, HomeUnavailable
from simorgh.contracts.home.policy import classify_call
from simorgh.contracts.protocols import ToolContext, ToolResult

from .registry import Ambiguous, NotFound, Registry

#: How a `before` snapshot is put back, per domain. A domain absent
#: from this table cannot be undone, and `home_call` says so at the
#: time rather than letting somebody discover it afterwards.
_UNDO_SERVICE = {
    "light": ("light.turn_on", "light.turn_off"),
    "switch": ("switch.turn_on", "switch.turn_off"),
    "fan": ("fan.turn_on", "fan.turn_off"),
    "media_player": ("media_player.turn_on", "media_player.turn_off"),
    "cover": ("cover.open_cover", "cover.close_cover"),
}


class _HomeTool:
    def __init__(self, config, *, client=None, env=None, secrets=None, clock=time.time) -> None:
        self._config = config
        self._given = client
        self._env = env if env is not None else os.environ
        self._secrets = secrets
        self._clock = clock

    def _client(self):
        if self._given is not None:
            return self._given
        url = self._lookup("HOME_ASSISTANT_URL", "vault:home_assistant:url")
        token = self._lookup("HOME_ASSISTANT_TOKEN", "vault:home_assistant:token")
        return HomeAssistantClient(
            url=url, token=token,
            timeout_s=float(getattr(self._config, "home_timeout_s", 10.0)),
            dry_run=bool(getattr(self._config, "home_dry_run", False)))

    def _lookup(self, env_name: str, vault_name: str) -> str:
        if self._secrets is not None:
            try:
                value = self._secrets.get(vault_name)
            except Exception:  # noqa: BLE001
                value = None
            if value:
                return str(value)
        return str(self._env.get(env_name) or "")

    def _aliases(self) -> dict:
        return dict(getattr(self._config, "home_aliases", {}) or {})

    @staticmethod
    def _unconfigured(client) -> ToolResult:
        return ToolResult(
            ok=False,
            error=("refused: Home Assistant is not configured. Set "
                   + " and ".join(client.missing() or ("HOME_ASSISTANT_URL",))
                   + " -- the token is a long-lived access token from your Home Assistant "
                     "profile page. Sim does not talk to devices directly; it talks to Home "
                     "Assistant, which already has an integration for everything in the house."))

    async def _registry(self, client) -> Registry:
        return await Registry.load(client, aliases=self._aliases())


class HomeFindTool(_HomeTool):
    name = "home_find"
    description = (
        "Find things in the house by name -- \"kitchen\", \"thermostat\", \"anything with a "
        "battery\". Returns entity ids you can use with home_state and home_call."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "required": ["query"],
                   "properties": {"query": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        client = self._client()
        if not client.configured:
            return self._unconfigured(client)
        try:
            registry = await self._registry(client)
        except HomeUnavailable as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")
        found = registry.search(str(args.get("query") or ""))
        if not found:
            return ToolResult(ok=True, output=f"nothing in the house matches "
                                               f"{args.get('query')!r}", metadata={"rows": []})
        return ToolResult(
            ok=True,
            output="\n".join("  " + entity.render() for entity in found),
            metadata={"rows": [{"entity_id": e.entity_id, "state": e.state, "name": e.name,
                                "domain": e.domain, "unit": e.unit} for e in found]})


class HomeStateTool(_HomeTool):
    name = "home_state"
    description = "What one thing in the house is doing right now. Takes an entity id or a name."
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "required": ["target"],
                   "properties": {"target": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        client = self._client()
        if not client.configured:
            return self._unconfigured(client)
        try:
            registry = await self._registry(client)
            entity_ids = registry.resolve(str(args.get("target") or ""))
        except HomeUnavailable as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")
        except (Ambiguous, NotFound) as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")

        entities = [registry.by_id(entity_id) for entity_id in entity_ids]
        entities = [e for e in entities if e is not None]
        lines = []
        for entity in entities:
            lines.append("  " + entity.render())
            for key in ("brightness", "temperature", "current_temperature", "volume_level",
                        "media_title", "hvac_action"):
                if key in entity.attributes:
                    lines.append(f"      {key}: {entity.attributes[key]}")
        return ToolResult(
            ok=True, output="\n".join(lines),
            metadata={"rows": [{"entity_id": e.entity_id, "state": e.state,
                                "attributes": e.attributes} for e in entities]})


class HomeDescribeTool(_HomeTool):
    name = "home_describe"
    description = (
        "What Sim can see in the house: how many things of each kind, and which services are "
        "available. Start here if you do not know what is there."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "properties": {}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        client = self._client()
        if not client.configured:
            return self._unconfigured(client)
        try:
            registry = await self._registry(client)
            services = await client.services()
        except HomeUnavailable as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")

        counts = registry.domains()
        unavailable = [e.entity_id for e in registry.entities if not e.available]
        lines = [f"{len(registry.entities)} things in the house:"]
        for domain, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            offered = ", ".join(sorted(services.get(domain, ()))[:6])
            lines.append(f"  {count:3} {domain}" + (f"   services: {offered}" if offered else ""))
        if unavailable:
            lines.append(f"unavailable right now: {', '.join(unavailable[:8])}")
        aliases = self._aliases()
        if aliases:
            lines.append("aliases: " + ", ".join(sorted(aliases)))
        return ToolResult(ok=True, output="\n".join(lines),
                          metadata={"entities": len(registry.entities), "domains": counts,
                                    "unavailable": unavailable})


class HomeCallTool(_HomeTool):
    name = "home_call"
    description = (
        "Do something in the house: turn a light on, set the thermostat, pause the TV. Takes a "
        "Home Assistant service (light.turn_on) and a target name or entity id. Reports what "
        "actually changed, which is not always what was asked for."
    )
    read_only = False
    #: The table's default. The real class is computed per call by
    #: `classify_call` and set on the proposal, because "turn a light
    #: on" and "unlock the front door" are not the same act.
    reversibility = "reversible"
    args_schema = {
        "type": "object", "required": ["service", "target"],
        "properties": {"service": {"type": "string"}, "target": {"type": "string"},
                       "data": {"type": "object"}, "all": {"type": "boolean"}},
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        service = str(args.get("service") or "").strip().lower()
        target = str(args.get("target") or "").strip()
        data = args.get("data") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                return ToolResult(ok=False, error=f"refused: `data` is not JSON: {data[:80]!r}")
        if "." not in service:
            return ToolResult(ok=False,
                              error=f"refused: {service!r} is not a Home Assistant service. "
                                    "They look like `light.turn_on` or `climate.set_temperature`.")

        client = self._client()
        if not client.configured:
            return self._unconfigured(client)
        try:
            registry = await self._registry(client)
            entity_ids = registry.resolve(target, domain=service.split(".", 1)[0])
            services = await client.services()
        except HomeUnavailable as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")
        except (Ambiguous, NotFound) as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")

        domain, _, name = service.partition(".")
        known = services.get(domain, set())
        if known and name not in known:
            near = ", ".join(sorted(known)[:8])
            return ToolResult(ok=False,
                              error=f"refused: Home Assistant has no {service!r}. "
                                    f"{domain} offers: {near}")

        limit = int(getattr(self._config, "home_max_entities_per_call", 20))
        if len(entity_ids) > limit and not args.get("all"):
            return ToolResult(
                ok=False,
                error=(f"refused: {target!r} resolves to {len(entity_ids)} entities, over the "
                       f"limit of {limit}. That is usually a name matching more than intended. "
                       f"Pass \"all\": true if you really mean all of them."))

        alarm = next((e.state for e in registry.entities
                      if e.domain == "alarm_control_panel"), "")
        classes = {classify_call(service, entity_id,
                                 device_class=(registry.by_id(entity_id).device_class
                                               if registry.by_id(entity_id) else ""),
                                 data=data, alarm_state=alarm,
                                 always_human=tuple(
                                     getattr(self._config, "home_always_human_services", ())))
                   for entity_id in entity_ids}
        worst = "human" if "human" in classes else (
            "reversible" if "reversible" in classes else "unattended")

        try:
            result = await client.call(service, entity_ids=tuple(entity_ids), data=data,
                                       settle_s=float(getattr(self._config, "home_settle_s", 1.0)))
        except HomeUnavailable as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")

        if result.dry_run:
            return ToolResult(
                ok=True,
                output=(f"dry run: would call {service} on {', '.join(entity_ids)}"
                        + (f" with {json.dumps(data)}" if data else "")
                        + "\n([execution] home_dry_run is on, so nothing was sent)"),
                metadata={"dry_run": True, "service": service, "entities": list(entity_ids),
                          "safety": worst})

        changed, unchanged = result.changed, result.unchanged
        body = f"{service} on {len(entity_ids)} entity(ies):\n{result.render()}"
        if unchanged and not changed:
            # Home Assistant answers 200 for a call on an unplugged
            # device. Reporting success here is the failure a person
            # can walk into the room and see.
            body += ("\n\nNothing actually changed. Home Assistant accepted the call, so the "
                     "device is most likely unavailable or does not support it.")
        undoable = all(registry.by_id(e) and registry.by_id(e).domain in _UNDO_SERVICE
                       for e in entity_ids)
        before = {e: {"state": v.state, "attributes": v.attributes}
                  for e, v in result.before.items()}
        if undoable and changed:
            body += "\n\nHOME_UNDO will put this back."
        return ToolResult(
            ok=True, output=body,
            side_effects=tuple(f"home:{service}:{entity_id}" for entity_id in entity_ids),
            metadata={"service": service, "entities": list(entity_ids), "changed": list(changed),
                      "unchanged": list(unchanged), "safety": worst, "undoable": undoable,
                      "before": before})


class HomeUndoTool(_HomeTool):
    name = "home_undo"
    description = (
        "Put back what the last home_call changed. Only works for things with a state that can "
        "be restored -- lights, switches, fans, media players, covers."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {"type": "object",
                   "properties": {"before": {"type": "object"}, "entity": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        before = args.get("before") or {}
        if isinstance(before, str):
            try:
                before = json.loads(before)
            except ValueError:
                before = {}
        if not before:
            return ToolResult(
                ok=False,
                error=("refused: nothing to undo. Pass the `before` map from the home_call "
                       "result you want to reverse -- Sim does not keep a hidden last-action "
                       "slot, because acting on one is how the wrong thing gets undone."))

        client = self._client()
        if not client.configured:
            return self._unconfigured(client)

        restored, skipped = [], []
        for entity_id, snapshot in before.items():
            domain = entity_id.split(".", 1)[0]
            pair = _UNDO_SERVICE.get(domain)
            if pair is None:
                skipped.append(f"{entity_id} ({domain} has no restorable state)")
                continue
            on_service, off_service = pair
            state = str((snapshot or {}).get("state") or "")
            attributes = dict((snapshot or {}).get("attributes") or {})
            if state in ("on", "playing", "open"):
                data = {}
                if domain == "light" and attributes.get("brightness"):
                    data["brightness"] = int(attributes["brightness"])
                service = on_service
            elif state in ("off", "closed", "idle", "paused", "standby"):
                service, data = off_service, {}
            else:
                skipped.append(f"{entity_id} (was {state!r}, which cannot be re-applied)")
                continue
            try:
                # The same settle `home_call` gives a device to actually
                # change (`home_settle_s`), not zero. Zero was harmless
                # while the result was thrown away; now the result IS
                # the verdict, so reading back too early reports a
                # device that did go back as "still on".
                result = await client.call(
                    service, entity_ids=(entity_id,), data=data,
                    settle_s=float(getattr(self._config, "home_settle_s", 1.0)))
            except HomeUnavailable as exc:
                skipped.append(f"{entity_id} ({exc})")
                continue
            # Home Assistant answers 200 for a service call on a device
            # that is unplugged, so "the call did not raise" and "the
            # thing went back" are different facts -- the difference
            # this whole domain exists to keep straight, in the one tool
            # whose entire job is putting something back. Until
            # 2026-09-10 this appended to `restored` on the absence of
            # an exception, and an observer watched it report "put back:
            # light.living_room -> off" for a bulb that was still on.
            if result.dry_run:
                skipped.append(f"{entity_id} (dry run: nothing was sent)")
                continue
            after = (result.after or {}).get(entity_id)
            if after is None:
                # No state came back at all, so nothing here says the
                # device went anywhere. The first version of this check
                # asked whether the state was WRONG, which let an entity
                # the house has never heard of fall through to "put
                # back": `home_undo` on `light.ghost` answered
                # `ok=True, "put back: light.ghost -> off"` (observer,
                # 2026-09-10). Evidence of success, not absence of
                # evidence of failure.
                skipped.append(f"{entity_id} (no state came back, so nothing confirms it moved)")
                continue
            if after.state != state:
                skipped.append(f"{entity_id} (still {after.state!r}, not {state!r})")
                continue
            restored.append(f"{entity_id} -> {state}")

        lines = []
        if restored:
            lines.append("put back:\n" + "\n".join(f"  {r}" for r in restored))
        if skipped:
            lines.append("could not put back:\n" + "\n".join(f"  {s}" for s in skipped))
        return ToolResult(ok=bool(restored), output="\n\n".join(lines) or "nothing to undo",
                          error=None if restored else "; ".join(skipped) or "nothing to undo",
                          side_effects=tuple(f"home:undo:{r.split(' ')[0]}" for r in restored),
                          metadata={"restored": len(restored), "skipped": len(skipped)})


def home_tools(config, **kwargs) -> list:
    return [HomeFindTool(config, **kwargs), HomeStateTool(config, **kwargs),
            HomeDescribeTool(config, **kwargs), HomeCallTool(config, **kwargs),
            HomeUndoTool(config, **kwargs)]


__all__ = ["HomeCallTool", "HomeDescribeTool", "HomeFindTool", "HomeStateTool", "HomeUndoTool",
           "home_tools"]

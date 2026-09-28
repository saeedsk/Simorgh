"""`home_find`, `home_state`, `home_describe`, `home_call`, `home_undo`,
`home_blink`.

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


class _RecoveringClient(HomeAssistantClient):
    """A client that, when Home Assistant cannot be reached, tries once to
    bring it back (`keeper.revive`: start its VM or container) and asks
    again. What was done rides in the answer either way."""

    #: What `revive` did on this client's last failure, for the tool's answer.
    revived = ""

    async def _request(self, method: str, path: str, body):
        try:
            return await super()._request(method, path, body)
        except HomeUnavailable as exc:
            if getattr(exc, "error_kind", "") != "transient":
                raise
            from .keeper import revive

            said = await revive(self.url)
            if not said:
                raise
            self.revived = said
            try:
                return await super()._request(method, path, body)
            except HomeUnavailable as again:
                raise HomeUnavailable(f"{again} -- {said}", error_kind="transient") from None


class _HomeTool:
    def __init_subclass__(cls, **kwargs) -> None:
        """Every tool's answer says when getting it meant starting Home
        Assistant: a tool that changed the machine must say so."""
        super().__init_subclass__(**kwargs)
        inner = cls.__dict__.get("run")
        if inner is None:
            return

        async def run(self, args: dict, *, ctx, _inner=inner):
            self._last_client = None
            result = await _inner(self, args, ctx=ctx)
            said = getattr(self._last_client, "revived", "")
            if not said or not isinstance(result, ToolResult):
                return result
            from dataclasses import replace

            note = f"Home Assistant was not answering: {said}."
            return replace(result, output=f"{note}\n{result.output}" if result.output else note,
                           side_effects=(*result.side_effects, said))

        run.__doc__ = inner.__doc__
        cls.run = run

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
        self._last_client = _RecoveringClient(
            url=url, token=token,
            timeout_s=float(getattr(self._config, "home_timeout_s", 10.0)),
            dry_run=bool(getattr(self._config, "home_dry_run", False)))
        return self._last_client

    def _lookup(self, env_name: str, vault_name: str) -> str:
        """The setting, from the secret store under either name, else
        the environment.

        Both names, since 2026-09-20. This asked the store for
        `vault:home_assistant:token` and then fell back to the
        ENVIRONMENT -- so `HOME_ASSISTANT_TOKEN = "..."` written into
        `secrets.toml`, which is exactly what somebody does after
        setting Home Assistant up, was silently ignored, while
        `REOLINK_*` and `RING_*` in the same file work (they ask the
        store for the bare name). The failure is the worst shape there
        is: the token is right there, correctly spelled, and Sim says
        Home Assistant is not configured.
        """
        for name in (vault_name, env_name):
            if self._secrets is None or not name:
                continue
            try:
                value = self._secrets.get(name)
            except Exception:  # noqa: BLE001 -- a store that will not answer is an unset secret
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
            return ToolResult.from_exception(exc, f"refused: {exc}")
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
    #: The row fields Execution keeps in the metadata blob (bounded, see
    #: `execution.service.metadata_for_blob`) so the World Model can
    #: fold what Sim just read into its entity table. `attributes` stays
    #: out: it is the bulky part, and the table holds a state, not a
    #: device's whole attribute dump.
    evidence_fields = ("entity_id", "state")
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
            return ToolResult.from_exception(exc, f"refused: {exc}")
        except Ambiguous:
            # Reading is not acting. `home state front` matching forty
            # things is a reason to show forty things, not to refuse:
            # ambiguity only costs something when the next step turns
            # one of them off. The creator typed exactly this on
            # 2026-09-20 and got a refusal with a list in it, which is
            # a list, delivered rudely.
            entity_ids = [e.entity_id for e in registry.search(str(args.get("target") or ""))]
        except NotFound as exc:
            return ToolResult.refused(f"refused: {exc}")

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
            return ToolResult.from_exception(exc, f"refused: {exc}")

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
                return ToolResult.refused(f"refused: `data` is not JSON: {data[:80]!r}")
        if "." not in service:
            return ToolResult.refused(f"refused: {service!r} is not a Home Assistant service. "
                                    "They look like `light.turn_on` or `climate.set_temperature`.")

        client = self._client()
        if not client.configured:
            return self._unconfigured(client)
        try:
            registry = await self._registry(client)
            entity_ids = registry.resolve(target, domain=service.split(".", 1)[0])
            services = await client.services()
        except HomeUnavailable as exc:
            return ToolResult.from_exception(exc, f"refused: {exc}")
        except (Ambiguous, NotFound) as exc:
            return ToolResult.refused(f"refused: {exc}")

        domain, _, name = service.partition(".")
        known = services.get(domain, set())
        if known and name not in known:
            near = ", ".join(sorted(known)[:8])
            return ToolResult.refused(f"refused: Home Assistant has no {service!r}. "
                                    f"{domain} offers: {near}")

        limit = int(getattr(self._config, "home_max_entities_per_call", 20))
        if len(entity_ids) > limit and not args.get("all"):
            return ToolResult.refused(f"refused: {target!r} resolves to {len(entity_ids)} entities, over the "
                       f"limit of {limit}. That is usually a name matching more than intended. "
                       f"Pass \"all\": true if you really mean all of them.")

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
            return ToolResult.from_exception(exc, f"refused: {exc}")

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
                      "before": before,
                      # What each thing IS now, not only that it moved.
                      # The World Model folds this so Sim knows the
                      # kitchen light is on because Sim turned it on;
                      # without it Sim changed the house and then had
                      # to wait for a camera or a person to tell it
                      # what it had done (stage 6 item 3).
                      "after": {e: v.state for e, v in result.after.items()}})


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
            return ToolResult.refused("refused: nothing to undo. Pass the `before` map from the home_call "
                       "result you want to reverse -- Sim does not keep a hidden last-action "
                       "slot, because acting on one is how the wrong thing gets undone.")

        client = self._client()
        if not client.configured:
            return self._unconfigured(client)

        restored, skipped = [], []
        # What each restored thing IS now, read back from the house --
        # the same `changed`/`after` shape `home_call` reports, so the
        # World Model folds an undo exactly as it folds the call it
        # undid. Until 2026-09-22 this reported only counts, and Sim put
        # the kitchen light back off and still believed it was on.
        changed, after_state = [], {}
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
            changed.append(entity_id)
            after_state[entity_id] = after.state

        lines = []
        if restored:
            lines.append("put back:\n" + "\n".join(f"  {r}" for r in restored))
        if skipped:
            lines.append("could not put back:\n" + "\n".join(f"  {s}" for s in skipped))
        return ToolResult(ok=bool(restored), output="\n\n".join(lines) or "nothing to undo",
                          error=None if restored else "; ".join(skipped) or "nothing to undo",
                          side_effects=tuple(f"home:undo:{r.split(' ')[0]}" for r in restored),
                          metadata={"restored": len(restored), "skipped": len(skipped),
                                    "changed": changed, "after": after_state})


#: Blinks running now, by entity: a second blink of the same light
#: replaces the first rather than the two fighting over it.
_BLINKING: dict[str, "asyncio.Task"] = {}


#: What "every light in the house" is called, once lower-cased and without "the".
_EVERY_LIGHT = frozenset({"all", "all lights", "every light", "everything", "whole house", "house",
                          "all lights in house", "all house lights", "lights", "all of lights"})


class HomeBlinkTool(_HomeTool):
    """A light (or a switch) switched off and on at a steady rate for a
    while, then put back as it was -- a signal, a light show.

    Live, 2026-09-27: asked three times to blink a light at 1-5 Hz for a
    minute, the model wrote a shell loop around `curl` with a token
    variable the shell did not have, reported "started", and nothing
    blinked. The first switch here is made and read back before the
    answer, so "blinking" is never said of a light that did not move; the
    rest runs in the background, one Guardian decision for the whole act.
    """

    name = "home_blink"
    description = (
        "Blink a light on and off at a steady rate for a while, then put it back as it was. "
        "Takes a target name, `hz` (switches per second, up to 4) and `seconds` (up to 300). "
        "Target \"stop\" stops every blink early and puts the lights back."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {
        "type": "object", "required": ["target"],
        "properties": {"target": {"type": "string"}, "hz": {"type": "number"},
                       "seconds": {"type": "number"}},
    }
    MAX_HZ = 4.0          # a Home Assistant round trip is ~0.1 s; faster only queues calls
    MAX_SECONDS = 300.0
    MAX_ENTITIES = 10
    MAX_ALL = 40          # "all lights": the whole house, in one service call per switch
    _DOMAINS = ("light", "switch")

    async def _stop_all(self) -> ToolResult:
        """Every running blink cancelled; each puts its lights back as it
        ends. Live, 2026-09-27: asked to stop, Sim said "stopped" with no
        tool call -- there was no way to stop one."""
        import asyncio

        running = set(_BLINKING.values())
        lights = sorted(_BLINKING)
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        if not running:
            return ToolResult(ok=True, output="nothing was blinking.", metadata={"stopped": []})
        return ToolResult(ok=True, output=f"stopped blinking {', '.join(lights)}; each is back as it was.",
                          side_effects=tuple(f"home:blink_stop:{e}" for e in lights),
                          metadata={"stopped": lights})

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        import asyncio

        target = str(args.get("target") or "").strip()
        if args.get("stop") or target.lower() in ("stop", "off", "none", "stop all", "stop blinking"):
            return await self._stop_all()
        if not target:
            return ToolResult.refused("refused: which light? Pass a `target`, like \"family room light\".")
        try:
            hz = float(args.get("hz") or 1.0)
            seconds = float(args.get("seconds") or 10.0)
        except (TypeError, ValueError):
            return ToolResult.refused("refused: `hz` and `seconds` are numbers, like 1 and 60.")
        if hz <= 0 or seconds <= 0:
            return ToolResult.refused("refused: `hz` and `seconds` must be above zero.")
        notes = []
        if hz > self.MAX_HZ:
            notes.append(f"{hz:g} Hz is faster than Home Assistant can switch a light, so {self.MAX_HZ:g} Hz")
            hz = self.MAX_HZ
        if seconds > self.MAX_SECONDS:
            notes.append(f"{seconds:g} s is over the {self.MAX_SECONDS:g} s limit, so {self.MAX_SECONDS:g} s")
            seconds = self.MAX_SECONDS

        client = self._client()
        if not client.configured:
            return self._unconfigured(client)
        everything = " ".join(target.lower().replace("the ", " ").split()) in _EVERY_LIGHT
        try:
            registry = await self._registry(client)
            entity_ids, last = None, None
            if everything:
                # "all lights" as a NAME matched only the lights whose names
                # say "Lights" -- two of the house's -- and Sim told the
                # creator every light was blinking (live, 2026-09-27).
                entity_ids = [e.entity_id for e in registry.entities
                              if e.domain == "light" and e.state in ("on", "off")]
            for domain in (() if everything else self._DOMAINS):
                try:
                    entity_ids = registry.resolve(target, domain=domain)
                    break
                except NotFound as exc:
                    last = exc
            if entity_ids is None:
                raise last or NotFound(target)
        except HomeUnavailable as exc:
            return ToolResult.from_exception(exc, f"refused: {exc}")
        except (Ambiguous, NotFound) as exc:
            return ToolResult.refused(f"refused: {exc}")
        if not entity_ids:
            return ToolResult.refused(f"refused: no light found for {target!r}.")
        if len(entity_ids) > (self.MAX_ALL if everything else self.MAX_ENTITIES):
            return ToolResult.refused(f"refused: {target!r} is {len(entity_ids)} things; blink at most "
                                      f"{self.MAX_ENTITIES} at once -- name them more narrowly.")

        # The first switch, read back: the evidence that the house moves.
        domain = entity_ids[0].split(".", 1)[0]
        on, off = f"{domain}.turn_on", f"{domain}.turn_off"
        try:
            probe = await client.call(f"{domain}.toggle", entity_ids=tuple(entity_ids),
                                      settle_s=float(getattr(self._config, "home_settle_s", 1.0)))
        except HomeUnavailable as exc:
            return ToolResult.from_exception(exc, f"refused: {exc}")
        if probe.dry_run:
            return ToolResult(ok=True, output=(f"dry run: would blink {', '.join(entity_ids)} at {hz:g} Hz "
                                               f"for {seconds:g} s ([execution] home_dry_run is on)"),
                              metadata={"dry_run": True, "entities": list(entity_ids)})
        if not probe.changed:
            return ToolResult.refused(
                f"refused: switched {', '.join(entity_ids)} once and nothing changed -- Home Assistant "
                "accepted the call, so the light is most likely unavailable. Nothing is blinking.")
        before = {e: v.state for e, v in probe.before.items()}

        for entity_id in entity_ids:
            running = _BLINKING.pop(entity_id, None)
            if running is not None:
                running.cancel()
        half = 1.0 / (2.0 * hz)
        switches = max(1, int(seconds / half))
        lit = {e: (v.state == "on") for e, v in probe.after.items()}

        async def blink() -> None:
            state = all(lit.values())
            # Bounded by the clock, not the count: each switch waits for Home
            # Assistant (~0.7 s live), and 240 switches meant to take 60 s
            # blinked for three minutes while the creator asked it to stop
            # (2026-09-27).
            ends = asyncio.get_running_loop().time() + seconds
            try:
                for _ in range(switches):
                    if asyncio.get_running_loop().time() >= ends:
                        break
                    started = asyncio.get_running_loop().time()
                    state = not state
                    try:
                        await client.fire(on if state else off, entity_ids=tuple(entity_ids))
                    except HomeUnavailable:
                        pass                          # a missed switch; the next one tries again
                    await asyncio.sleep(max(0.0, half - (asyncio.get_running_loop().time() - started)))
            finally:
                # Put each back as it was, whatever ended the blink.
                for entity_id, was in before.items():
                    try:
                        await client.fire(on if was == "on" else off, entity_ids=(entity_id,))
                    except HomeUnavailable:
                        pass
                for entity_id in entity_ids:
                    if _BLINKING.get(entity_id) is task:
                        _BLINKING.pop(entity_id, None)

        task = asyncio.get_running_loop().create_task(blink())
        for entity_id in entity_ids:
            _BLINKING[entity_id] = task
        # Let it start: a task cancelled before its first step never runs its
        # `finally`, and a stop that came at once left the light switched.
        await asyncio.sleep(0)
        moved = ", ".join(f"{e}: {probe.before[e].state} -> {probe.after[e].state}"
                          for e in probe.changed if e in probe.before and e in probe.after)
        body = (f"blinking {', '.join(entity_ids)} at {hz:g} Hz for {seconds:g} s ({switches} switches), "
                f"then back to {', '.join(f'{e} {s}' for e, s in before.items())}. "
                f"The first switch was confirmed ({moved}).")
        lights = sum(1 for e in registry.entities if e.domain == "light")
        body += (f" That is {len(entity_ids)} of the {lights} lights in the house"
                 + (" -- all that are reachable." if everything else "; say which ones, not \"all\", "
                    "unless it is all of them.") if lights else "")
        if notes:
            body += " Limited: " + "; ".join(notes) + "."
        return ToolResult(ok=True, output=body,
                          side_effects=tuple(f"home:blink:{e}" for e in entity_ids),
                          metadata={"entities": list(entity_ids), "hz": hz, "seconds": seconds,
                                    "switches": switches, "before": before, "changed": list(probe.changed)})


def home_tools(config, **kwargs) -> list:
    return [HomeFindTool(config, **kwargs), HomeStateTool(config, **kwargs),
            HomeDescribeTool(config, **kwargs), HomeCallTool(config, **kwargs),
            HomeUndoTool(config, **kwargs), HomeBlinkTool(config, **kwargs)]


__all__ = ["HomeBlinkTool", "HomeCallTool", "HomeDescribeTool", "HomeFindTool", "HomeStateTool", "HomeUndoTool",
           "home_tools"]

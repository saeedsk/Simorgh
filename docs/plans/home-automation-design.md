# Sim as the brain of the house

Design pass, 2026-09-09 (Fable). Implementation is handed to Opus; this
document is written so that nothing below needs a design decision.
Where a choice was open it is made here, with the reason. The five
invariants and the ten-step wiring checklist in
`docs/plans/resourcefulness-toolset.md` apply to every tool below.

The house: Alexa Echo Show / Echo Dot units, Ring devices, IP cameras, a
digital thermostat, temperature/humidity sensors, IoT light strings,
and every light in the house on IoT. The ask: Sim controls all of it,
monitors it, schedules it, and reacts to it (IFTTT-style triggers).

## 0. The one architectural decision everything else follows from

**Sim does not speak to devices. Sim speaks to Home Assistant.**

Every device class in this house is already integrated by Home
Assistant (HA), the largest open-source home automation project there
is: Alexa (via `alexa_media_player`), Ring (native integration +
`ring-mqtt`), IP cameras (ONVIF/RTSP, and Frigate for detection),
thermostats (Nest/Ecobee/Honeywell/Z-Wave/Zigbee natively), sensors,
Hue/LIFX/Tuya/Kasa/Govee lights and strips. HA exposes all of it as
one uniform model -- `entity_id`, `state`, `attributes`, and
`domain.service` calls -- over a documented REST + WebSocket API with a
long-lived token.

Writing device drivers into Sim would be the reinvention the creator
already ruled out (`feedback_reuse_open_source`). It would also be
slower, worse, and abandoned the day a vendor changes an API. HA has
~2,800 integrations and a release every month. Sim's value is not
talking to a bulb; it is deciding what the house should do.

So the layering is:

```
 devices ──► Home Assistant ──► Sim `home` subsystem ──► Sim bus (percepts)
             (drivers, state,      (bridge, registry,       │
              hard-safety rules)    triggers, monitors)     ▼
                                                     cognition / rules / Guardian
 devices ◄── Home Assistant ◄── Execution `home_*` tools ◄─┘
```

**Two consequences, both non-negotiable:**

1. **Hard safety automations live in HA, not Sim.** Smoke detector →
   all lights on + unlock nothing; water leak → valve off; freeze
   warning → heat on. These must work when Sim is down, being
   restarted, or mid-bad-decision. HA runs them locally with no
   dependency on Sim. Sim may *create* such automations (section 6.4)
   but never *owns* them at runtime.
2. **Sim owns the intelligent layer**: anything with context, judgment,
   memory, or a person in the loop. "Lights on when motion" is HA.
   "Lights on when motion, unless it is 3am and someone just went to
   bed, and dim them to 10% if so" is Sim.

## 1. Open-source inventory (what to install, what it is for)

| component | role | why this one | runs where |
|---|---|---|---|
| **Home Assistant** (HAOS or container) | device hub, state, services, hard-safety automations | the standard; every device here has an integration | a dedicated box: mini PC / RPi 4+ / NUC. Not the Sim machine. |
| **Mosquitto** (HA add-on) | MQTT broker | the lingua franca of local IoT; Frigate, ring-mqtt, Zigbee2MQTT all speak it | HA box |
| **Frigate** | NVR + real-time object detection on the IP cameras (person, car, package, animal) | local, open source, publishes detections to MQTT, exposes snapshots/clips; HA integration is first-class | HA box, or its own box; a Google Coral USB TPU makes it cheap on CPU |
| **go2rtc** (bundled in Frigate) | camera stream restreaming (RTSP/WebRTC) | one place that speaks every camera's stream dialect | with Frigate |
| **ring-mqtt** | Ring doorbells/cams/alarm → MQTT (events, snapshots, live streams, alarm arm/disarm) | the HA native Ring integration is polling-only for some events; ring-mqtt is push and richer | HA add-on |
| **alexa_media_player** (HACS) | Echo devices as media players: TTS, announcements, volume, routines | the only way to make an Echo *speak* from outside Alexa | inside HA |
| **HA Alexa Smart Home skill** | voice → device control ("Alexa, turn off the kitchen") | devices exposed to Alexa through HA, so one source of truth | Nabu Casa cloud ($) or self-hosted skill |
| **Zigbee2MQTT** / **Z-Wave JS** (HA add-ons) | if any sensors/lights are Zigbee/Z-Wave | local, no vendor cloud | HA box + a USB coordinator |
| **ESPHome** | optional, for any DIY sensor | | |
| **Tailscale** (or WireGuard) | Sim ↔ HA when they are not on one LAN | keep HA off the public internet | both |
| **`websockets` / `httpx`** (already installed) | Sim's HA client | no new dependency | Sim |
| **`aiomqtt`** | Sim's optional direct MQTT tap (Frigate events without HA in the middle) | small, asyncio-native | Sim, optional dep |

Not used, and why: **Node-RED** (Sim *is* the rules engine; two engines
is two sources of truth); **Homebridge** (Apple-only); **openHAB**
(smaller ecosystem than HA); **IFTTT itself** (cloud, slow, paid; Sim
implements the trigger model locally and exposes a webhook so IFTTT can
still call *in* if ever wanted).

## 2. The `home` subsystem (`simorgh/home/`)

A 17th subsystem, registered in `kernel/registry.py::LAYERS` after
`execution` (it publishes percepts Execution's tools act on, and it
calls HA through the same client Execution's tools use).

```
simorgh/home/
  __init__.py
  api.py           Entity, StateChange, Rule, Trigger, Condition, Action dataclasses
  config.py        Config (section 2.1)
  client.py        HomeAssistantClient: REST + WebSocket, token from env, reconnect
  registry.py      entity cache, aliases ("kitchen lights" -> light.kitchen_main), areas
  bridge.py        WS state_changed -> percept.home.state_changed (filtered, debounced)
  engine.py        the trigger/condition/action engine (section 4)
  rules_store.py   rules persisted in the ledger stream `home:rules`, plus TOML import
  monitors.py      built-in watchdogs (section 5)
  presence.py      "who is home", derived from device_tracker + Ring + motion
  service.py       Service: start/stop/health, subscriptions, the digest
  fakes.py         FakeHomeAssistant for tests (WS + REST), NOT under tests/ because
                   Execution's tool tests need it too and may not import tests/
```

### 2.1 Config (`[home]` in simorgh.toml)

```python
@dataclass(frozen=True)
class Config:
    enabled: bool = False                 # off until a URL+token exist
    url_env: str = "HOME_ASSISTANT_URL"   # e.g. http://homeassistant.local:8123
    token_env: str = "HOME_ASSISTANT_TOKEN"
    mqtt_url_env: str = "MQTT_URL"        # optional: mqtt://user:pass@host:1883
    # Which entities Sim SEES. Empty = every domain in `domains`.
    domains: tuple[str, ...] = ("light", "switch", "climate", "sensor", "binary_sensor",
                                "camera", "lock", "alarm_control_panel", "cover",
                                "media_player", "device_tracker", "person", "sun",
                                "weather", "scene", "script", "automation", "fan", "vacuum")
    include: tuple[str, ...] = ()         # entity_id globs that always pass
    exclude: tuple[str, ...] = ("sensor.*_linkquality", "sensor.*_rssi", "sensor.*_uptime")
    # Percept volume control -- the ledger has already exploded once
    # (192k trace files, project_ledger_growth_watch). Numeric sensors
    # publish only when the value moves by `numeric_deadband` or
    # `numeric_min_interval_s` has passed, whichever is later.
    numeric_deadband: float = 0.5
    numeric_min_interval_s: float = 60.0
    # Domains whose EVERY change is a percept (they are events, not readings).
    event_domains: tuple[str, ...] = ("binary_sensor", "lock", "alarm_control_panel",
                                      "cover", "person", "device_tracker")
    reconnect_min_s: float = 2.0
    reconnect_max_s: float = 60.0
    request_timeout_s: float = 10.0
    rules_path: str = "workspace/home/rules.toml"   # human-editable import; ledger is the truth
    digest_hour: int = 8                            # daily digest via notify
    dry_run: bool = False                           # log every service call, send none
    # Section 7: what Sim may do without a human.
    unattended_domains: tuple[str, ...] = ("light", "switch", "fan", "media_player",
                                           "scene", "script", "climate", "cover:non_garage")
    always_human_services: tuple[str, ...] = ("lock.unlock", "alarm_control_panel.alarm_disarm",
                                              "cover.open_cover:garage", "camera.turn_off",
                                              "automation.turn_off", "switch.turn_off:security")
```

`enabled` false by default and the tools refuse naming the two env
variables -- the Tier 5 rule (build it ready; the user supplies the
token when they are ready). `capabilities` (the CLI command) gains a
`home_assistant` probe: `GET /api/` with the token, "cheap" cost,
tools=("home_state", "home_call", …).

### 2.2 `client.py`

```python
class HomeAssistantClient:
    def __init__(self, url: str, token: str, *, session=None, ws_connect=None,
                 timeout_s: float = 10.0, logger=None) -> None: ...
    async def states(self) -> list[Entity]                        # GET /api/states
    async def state(self, entity_id: str) -> Entity | None        # GET /api/states/<id>
    async def call_service(self, domain: str, service: str, data: dict,
                           *, target: dict | None = None) -> list[Entity]   # POST /api/services/<d>/<s>
    async def history(self, entity_id: str, *, hours: float) -> list[StateChange]  # GET /api/history/period
    async def camera_snapshot(self, entity_id: str) -> bytes      # GET /api/camera_proxy/<id>
    async def services(self) -> dict                              # GET /api/services (for describe)
    async def areas(self) -> list[dict]                           # WS config/area_registry/list
    async def entity_registry(self) -> list[dict]                 # WS config/entity_registry/list
    async def subscribe_state_changes(self, on_change: Callable[[StateChange], Awaitable[None]]) -> None
        # WS: auth -> subscribe_events(event_type="state_changed"); reconnect with backoff;
        # on reconnect, re-fetch /api/states and emit synthetic changes for anything that
        # moved while disconnected (the engine must not miss "door opened" during a blip)
    async def fire_event(self, event_type: str, data: dict) -> None   # POST /api/events/<type>
    async def render_template(self, template: str) -> str            # POST /api/template
```

Every method: timeout, one retry on connection error, never raises past
`HomeUnavailable(reason)`. The token is never logged, never in an
error string, never in metadata -- test it with a token containing the
word `SECRET` and assert it appears in no output.

### 2.3 `registry.py` -- names people use

HA entity ids are `light.kitchen_main_2`. People say "the kitchen
lights". The registry keeps:

- every entity: id, domain, friendly_name, area, device_class,
  unit, last state, last_changed, supported services;
- **aliases**: `workspace/home/aliases.toml` (`"kitchen lights" =
  ["light.kitchen_main", "light.kitchen_island"]`), plus aliases the
  model *learns* by asking (`home_alias` tool) which go to the ledger
  stream `home:aliases`;
- `resolve(text) -> list[Entity]`: exact id → alias → friendly-name
  fuzzy (`difflib`, cutoff 0.75, the same threshold `interface/parser`
  autocorrect uses) → area + domain ("bedroom lights" = every `light.*`
  in area Bedroom). **Ambiguity is returned, not resolved**: the tool
  answers "did you mean light.kitchen_main or light.kitchen_island?"
  rather than picking. Wrong-light is a small cost; wrong-lock is not.

Refresh: full `/api/states` at start and on every reconnect; entity
and area registries hourly (they change when someone renames a bulb).

### 2.4 `bridge.py` -- HA events become Sim percepts

New contract topics (`contracts/topics.py` + `contracts/messages/home.py`
+ schemas, catalog v1):

```
percept.home.state_changed   {entity_id, domain, old_state, new_state, attributes: {…subset…},
                              changed_at, area, friendly_name}
percept.home.event           {event_type, data}              # frigate detections, ring dings,
                                                              # HA custom events, webhooks
percept.home.presence        {person, state: home|away, via: device_tracker|ring|motion}
home.action.requested        {action_id, domain, service, target, data, rule_id|task_id, reason}
home.action.done             {action_id, ok, before: [...entities...], after: [...], error}
home.rule.fired              {rule_id, trigger, conditions_met, actions: [action_ids]}
home.monitor.alert           {monitor, severity: info|warn|critical, entity_id, message}
```

Filtering (section 2.1) happens here. The rule: **a binary event is
always a percept; a numeric reading is a percept when it matters.** A
temperature sensor reporting every 10s produces ~8,600 readings a day
per sensor; with a 0.5° deadband and a 60s floor it produces dozens.
The engine's numeric triggers (section 4.2) evaluate against the
*unfiltered* stream inside the bridge, so a threshold is never missed
because of debouncing -- only the bus is spared.

The ledger stream `home:state` records percepts the bridge *published*
(already filtered). Trace sampling per `project_ledger_growth_watch`:
do not sample; filter at the source, as above.

## 3. Execution tools (`simorgh/execution/home.py`)

All construct a `HomeAssistantClient` from env at first use (not at
boot -- the token may appear later) and refuse with the exact variable
names when absent. Injected client in tests. The `home` subsystem and
these tools share `client.py` by import from `simorgh/home/client.py`
-- **which the module-boundary rule forbids** (Execution may not import
another subsystem). Resolution, decided: the client, the entity
dataclasses and the fakes move to **`simorgh/contracts/home/`**
(`client.py`, `api.py`, `fakes.py`), which both may import. Contracts
already holds shared message shapes; a shared client for a shared
external system is the same kind of thing. Keep it dependency-light
(`httpx`, `websockets`, both present).

| tool | args | read_only | reversibility | Guardian |
|---|---|---|---|---|
| `home_find` | `query` | yes | read_only | none -- registry lookup |
| `home_state` | `target` (id/alias/area), `history_hours?` | yes | read_only | none |
| `home_describe` | `target?` | yes | read_only | none -- areas, domains, counts, services available |
| `home_call` | `service`, `target`, `data?` | no | **per call** (section 7) | `HomeRule` |
| `home_scene` | `name` | no | reversible | `HomeRule` (scenes are lights/media only by policy) |
| `home_announce` | `text`, `where?` (echo alias/area/"all"), `volume?` | no | irreversible (you cannot un-say it) but `unattended` | `HomeRule` + rate limit 10/hour |
| `home_camera` | `target`, `what?` ("snapshot" default, "last_event") | yes | read_only | none for a snapshot; `camera.turn_off` is NOT this tool |
| `home_undo` | `action_id?` (default: last) | no | reversible | none -- it restores a recorded `before` |
| `home_rule` | `op` (list/show/add/enable/disable/delete/test), `rule?` | no | reversible (rules are ledger events) | `HomeRule` for `add` when actions include an always-human service |
| `home_alias` | `name`, `entities` | no | reversible | none |
| `home_history` | `target`, `hours` | yes | read_only | none -- rows → `results/` for `query_data` |

Marker shapes (multi-field ones are `_MARKER_SPLIT_FIRST_LINE` +
`_MARKER_JSON_REST`, so JSON on line 2 merges into args; ALL go into
`_CODE_BEARING_MARKERS`):

```
HOME_FIND: kitchen
HOME_STATE: climate.hallway
HOME_CALL: light.turn_on
{"target": "kitchen lights", "data": {"brightness_pct": 40, "color_temp_kelvin": 2700}}
HOME_ANNOUNCE: kitchen echo
The laundry is done.
HOME_RULE: add
{...rule JSON per section 4.1...}
```

`home_call` is the one that matters. Its `run`:

1. resolve `target` through the registry; ambiguity → refuse with the
   candidates; nothing → refuse naming the nearest three.
2. validate `service` exists for that domain (`client.services()`),
   and `data` keys against HA's service schema fields -- a typo'd
   `brightness` vs `brightness_pct` is the most common failure and HA
   silently ignores unknown fields.
3. **snapshot `before`**: the resolved entities' full state. This is
   what `home_undo` restores and what `reversible` means here: for
   `light`/`switch`/`fan`/`media_player`/`climate`/`cover`, the prior
   state is re-appliable (`light.turn_on` with the old brightness/
   color, or `turn_off`; `climate.set_temperature` with the old
   target). For `lock`, `alarm_control_panel`, `camera`, `script`,
   `automation` it is not -- an unlocked door was open for a while;
   these are `irreversible` and section 7 gates them.
4. `dry_run` → log + return `would call …` with `ok=True` and
   `metadata.dry_run=True`. Never a silent no-op.
5. call; wait up to 3s and re-read state; return `before → after` per
   entity. **If the state did not change, say so** -- HA returns 200
   for a service call on an unavailable device. The honesty rule: the
   tool reports what the house did, not what HA accepted.
6. side_effects `("home:<domain>.<service>:<entity_id>", …)`; ledger
   event on `home:actions` with before/after; publish
   `home.action.done`.

`home_camera`: writes the JPEG to `results/camera/<entity>-<ts>.jpg`,
returns the path and, **when a vision-capable provider is configured,
a one-paragraph description** (section 8). Without one it returns the
path and says vision is not configured -- and what would configure it.

## 4. The trigger engine (`simorgh/home/engine.py`) -- IFTTT, local

### 4.1 Rule shape (the contract; stored as JSON in ledger stream `home:rules`)

```json
{
  "id": "evening-porch",            "name": "Porch light at dusk",
  "enabled": true,                  "mode": "single | restart | queued",
  "triggers": [ {"kind": "sun", "event": "sunset", "offset_s": -900} ],
  "conditions": [ {"kind": "presence", "anyone_home": true},
                  {"kind": "state", "entity": "light.porch", "is": "off"} ],
  "actions": [ {"kind": "call", "service": "light.turn_on", "target": "light.porch",
                "data": {"brightness_pct": 60}},
               {"kind": "notify", "text": "Porch light on for the evening", "level": "info"} ],
  "cooldown_s": 300,                "for_s": 0,
  "created_by": "human | rule-engine | task:<id>",  "notes": "why this exists"
}
```

**Trigger kinds** (each a class in `engine.py`, each with a `matches(event, now) -> bool`):

| kind | fields | fires on |
|---|---|---|
| `state` | `entity`, `from?`, `to?`, `for_s?` | `state_changed` matching; `for_s` = must hold that long (a timer armed on match, cancelled on change -- "motion off for 10 minutes") |
| `numeric` | `entity`, `above?`, `below?`, `for_s?`, `hysteresis?` | crossing, evaluated on the unfiltered stream (2.4); hysteresis prevents flapping at the threshold |
| `attribute` | `entity`, `attribute`, `to` | attribute change (battery level, hvac_action) |
| `event` | `event_type`, `match?: {k: v}` | `percept.home.event` -- frigate `person` in `driveway`, ring `ding`, a webhook |
| `time` | `at: "HH:MM"`, `days?` | wall clock, local tz |
| `cron` | `expr` | five-field cron; use `croniter` (optional dep) or a 60-line parser -- decided: the parser, no dep, tests from the croniter suite |
| `sun` | `event: sunrise|sunset|dawn|dusk`, `offset_s` | from HA's `sun.sun` attributes (`next_rising` …), re-armed daily |
| `interval` | `every_s` | via the Kernel scheduler (`system.schedule.add`, which now has a publisher) -- do not run a second timer loop |
| `presence` | `person?`, `becomes: home|away`, `anyone|everyone` | `percept.home.presence` |
| `duration_open` | `entity`, `open_for_s` | a door/window/garage `on` longer than N -- the most-asked-for monitor |
| `webhook` | `id` | `POST /api/home/webhook/<id>` on Sim's HTTP API (section 8); token-protected; this is the IFTTT/Alexa-routine/Shortcuts inbound path |
| `sim_task` | `task_id?`, `outcome: completed|failed` | a Sim task finishing -- "when the nightly backup task fails, flash the office light red" |

**Condition kinds**: `state`, `numeric`, `presence`, `time_window`
(`after`/`before`, wraps midnight), `days`, `sun` (`after_sunset` …),
`rule_fired_within` (`rule_id`, `seconds` -- "not if the doorbell rule
already fired"), `template` (an HA Jinja template rendered by HA,
result must be `true` -- the escape hatch, since HA's template engine
already knows everything).

**Action kinds**: `call` (→ `home_call`, same path, same Guardian --
**rules do not bypass Guardian**; a rule's action is a proposal from
`proposed_by="home-rule:<id>"`), `scene`, `announce`, `notify`,
`delay` (`seconds`), `wait_for` (a trigger spec + `timeout_s`),
`run_rule`, `set_variable` (rule-scoped kv in ledger), `sim_task`
(`kind: research|improve`, `text` -- the bridge to cognition: "when a
package is detected, ask Sim to look at the snapshot and say what it
is"), `fire_event`.

### 4.2 Engine semantics, decided

- Deterministic first. The engine is a pure function of
  `(rules, event, state_snapshot, now)`; cognition is invoked only by
  an explicit `sim_task` action. A house should not need an LLM to turn
  a light on, and the LLM must not be on the path of a 200ms response.
- `mode`: `single` (ignore triggers while running), `restart`
  (cancel the running instance), `queued` (max 5). Default `single`.
- `cooldown_s` per rule; `for_s` timers survive a restart (armed
  timers are ledger events `home:timers`, replayed on boot like
  `kernel/scheduler.py` does).
- Every fire → `home.rule.fired` + ledger `home:rules` `fired` event;
  every action goes through `home.action.requested` so Guardian sees
  it and `home_undo` can revert it.
- A rule that errors 3 times in a row is disabled and a `warn` alert
  is raised. It does not keep trying at 3am.
- `home_rule test` runs the rule's actions in `dry_run` against the
  current state and reports what *would* happen, and which conditions
  are currently true. Build this before `add`; it is how a person (and
  the model) learns the DSL.
- Rules import from `rules_path` (TOML, human-editable) on boot and on
  `home_rule reload`; the ledger is the truth, the file is a
  convenience; a rule present in both with different content → the
  ledger wins and a `warn` says so.

### 4.3 Where HA automations fit

`home_rule add … "hard_safety": true` → the engine does NOT keep it;
it converts it to an HA automation YAML and creates it via HA's config
API (`POST /api/config/automation/config/<id>`), so it runs inside HA
with no Sim dependency. Supported for the subset that maps 1:1
(`state`/`numeric`/`time`/`sun` triggers, `state` conditions, `call`
actions). Anything else → refuse: "this needs Sim's engine; drop
hard_safety". Creating an HA automation is `irreversible`-gated (it
changes the house's behaviour permanently).

## 5. Monitoring (`simorgh/home/monitors.py`)

Built-in monitors, each a small class with `check(state, now) ->
list[Alert]`, run every `system.tick.idle` (not every second) and on
relevant percepts. All on by default when `home.enabled`; each
disableable in `[home.monitors]`.

| monitor | fires when | severity |
|---|---|---|
| `unavailable` | an entity has been `unavailable`/`unknown` > 15 min (lights) / 5 min (locks, cameras, alarm) | warn / critical |
| `stale_sensor` | a sensor's `last_updated` is older than 3× its usual cadence (learned over 24h, stored in ledger) | warn |
| `battery` | any `battery` attribute or `sensor.*_battery` < 20% (warn) / < 10% (critical) | |
| `door_open` | any `binary_sensor` with device_class door/window/garage `on` > 10 min, > 30 min if nobody home → critical | |
| `climate_runaway` | thermostat `hvac_action` heating/cooling > 3h continuously, or indoor temp drifting away from the target for 45 min | warn |
| `humidity` | any humidity sensor > 65% for 2h (mold) or < 25% (dry) | warn |
| `freeze` | any indoor temp < 5°C | critical |
| `camera_offline` | Frigate/HA reports a camera stream down | critical |
| `ring_alarm` | alarm panel `triggered`, or a Ring `ding`/`motion` while everyone is away | critical / info |
| `frigate_detection` | `person` in a zone while away; `package` detected (info); `car` in driveway at night | info / warn |
| `energy_anomaly` | if a power sensor exists: a device drawing power at a time it never has before (24h profile, ledger) | info |
| `ha_unreachable` | the WS has been down > 2 min | critical -- and this one goes out via `notify` with its own provider, since HA-routed announcements are down by definition |

Delivery: `home.monitor.alert` on the bus → `home/service.py` routes
by severity: `info` → ledger + daily digest; `warn` → `notify` (the
tool from b639300), max one per monitor per hour; `critical` → `notify`
immediately + `home_announce` on every Echo if anyone is home + a
`percept.text.received` so cognition can decide whether more is
needed. Every alert is idempotent per (monitor, entity) until cleared
-- no alert storms. Clearing is an `info` ("front door closed after 14
min").

**Daily digest** at `digest_hour` via `notify`: devices unavailable,
batteries low, rules fired (count per rule), alerts raised/cleared,
energy if known, "things I noticed" -- the last one is a bounded
cognition call over the day's `home:state` summary (Curiosity's budget
applies; `project_open_bugs_2026-09-07` -- the budget burn bug is
fixed, but the digest gets ONE call, not a loop).

## 6. Scheduling

Reuse, do not build: the Kernel scheduler (`kernel/scheduler.py`) is
complete and now has a publisher (`schedule` command, 089f73c). The
engine's `interval`, `time`, `cron` and `sun` triggers all compile to
`system.schedule.add` messages with `payload={"rule_id": …}` and fire
back through `percept.time.scheduled`. One timer loop in the process,
one ledger stream, one restart-replay path. The engine's only addition
is `cron`/`sun` → next-fire-time computation, re-armed after each
fire (the scheduler's `every_seconds` cannot express "every weekday at
07:00", so those are one-shots re-scheduled on fire).

`schedule` (the CLI command) gains `schedule 07:00 weekdays home: coffee
scene` -- i.e. a `time` trigger whose action is a rule call. Cheap,
because it is the same engine.

## 7. Guardian: `HomeRule` and the per-call reversibility

`_TOOL_POLICY["home_call"] = ("reversible", True)` is the default the
table shows, and `to_action_payload` sets reversibility **per call**
from `(service, resolved domain, device_class)` -- the `db_query`
pattern from `data-toolset-design.md` §4.3, using a pure function in
`simorgh/contracts/home/policy.py` that Guardian can also import:

```python
def classify_call(service: str, entity_id: str, device_class: str | None,
                  config) -> Literal["unattended", "reversible", "human"]:
```

- `human`: anything in `always_human_services` (unlock, disarm,
  garage open, camera off, automation off, a switch whose
  device_class or name says security/alarm/siren), plus `climate` set
  outside `[10, 32]°C`, plus **any** service when
  `alarm_control_panel` is `armed_away` (the house is in security
  mode; only a person changes anything).
- `reversible`: the rest of the domains in `unattended_domains`, when
  a `before` snapshot is re-appliable.
- `unattended` is `reversible` + the rule engine may do it with no
  human even when `irreversible_requires_human` is on.

`HomeRule` (Guardian, after `DenylistRule`): reads `args["service"]`
and `args["target"]`; `human` → `escalate`; a service HA does not have
→ deny; `home_announce` > 10/hour or between 23:00–07:00 without
`"urgent": true` → deny ("nobody wants an Echo at 3am"); `home_call`
on > 20 entities at once without `"all": true` → deny (a typo'd alias
that matched every light). Guardian never trusts the proposer's
reversibility label; it recomputes with `classify_call`.

`sim.sh` auto-approves irreversible actions by default
(`project_guardian_auto_approve_default`). **For the house that
default is wrong**: `[home] always_human_services` is enforced by
`HomeRule` as `escalate` → `needs_human` **regardless of
`SIMORGH_GUARDIAN_AUTO_APPROVE`**. Add a `GuardianConfig.
auto_approve_exempt_layers = ("home",)` read by the auto-approve path;
test that an unlock proposal with auto-approve on still waits.

Emergency stop: `home off` (CLI) → `home.enabled` false at runtime:
the engine stops firing, tools refuse, monitors keep running (they only
read), `ha_unreachable` still alerts. `home on` restores. Ledgered like
`autonomous_paused` (kernel/state.py), restored on boot -- a hold is
never released by a restart.

## 8. Voice, vision, and the inbound path

**Voice → devices**: HA's Alexa Smart Home skill. Nothing for Sim to
build; document the setup in `docs/home/setup.md`.

**Voice → Sim** ("Alexa, ask the house why the porch light is on"):
an Alexa custom skill whose endpoint is Sim's HTTP API. `interface/
httpapi.py` is GET-only today; add `POST /api/home/voice` (Alexa
request JSON → `percept.text.received` with `channel="alexa"` →
cognition → reply, ≤ 8s or Alexa times out; so the handler answers
from the registry/engine for state questions and only escalates to
cognition for the rest, with a "let me look into that" + follow-up
`home_announce`) and `POST /api/home/webhook/<id>` (section 4.1,
`X-Sim-Token` header = `HOME_WEBHOOK_TOKEN` env). Both behind
`Tailscale`/reverse proxy; never bound to `0.0.0.0` by default.

**Vision** -- CORRECTED 2026-09-09 after the creator's review. The
first version of this paragraph specified vision as key-gated only
("GEMINI_API_KEY or ANTHROPIC_API_KEY, else not configured"), which is
the reach-for-a-paid-API pattern the creator has already corrected
once (`feedback_resourcefulness`). Local first, in this order, each
optional and refused by name when absent -- the full version is
`voice-design.md §8`:

1. **Frigate** already classifies person/car/package/animal on every
   camera locally; `home_camera what=last_event` returns that.
2. **A VLM** -- the configured cloud vision model, or `qwen2.5vl:7b` /
   `moondream` via Ollama as the fallback, per the creator's provider
   policy in `voice-design.md §0` (cloud primary for the LLM, local as
   fallback); `[cognition] vision_provider` decides and the daily cap
   applies to the cloud one.
3. **Task-specific local models** for a repeated question:
   `ultralytics` YOLO, `open_clip`, `EasyOCR`/`tesseract`,
   `insightface` (household members, enrolled, opt-in).
4. **Cloud vision** only when named in `[cognition] vision_provider`,
   with the daily cap.

Cost control is unchanged: one call per Frigate event, never per frame.

## 9. Tests -- what is not optional

- `contracts/home/fakes.py::FakeHomeAssistant`: an in-process REST +
  WS server (aiohttp is installed) with a scriptable entity table,
  service handlers that mutate state, and `emit(event)`. Every test
  below uses it; **no test contacts a real HA**.
- `client`: auth, reconnect with backoff, resync after reconnect
  emits the missed change, token never in any string.
- `registry`: alias > friendly-name > area resolution; ambiguity is
  returned; "bedroom lights" resolves by area+domain.
- `bridge`: deadband/min-interval filtering; a binary event always
  passes; numeric triggers still fire on a filtered-out reading.
- `engine`: every trigger kind, `for_s` timer cancel-on-change,
  `mode` semantics, cooldown, 3-strikes disable, timers survive
  restart, `test` op reports conditions. Property: the same
  `(rules, events)` replayed twice yields identical `fired` lists.
- `monitors`: each one with a FakeClock walking past its threshold;
  idempotent alerts; clear events.
- Guardian: unlock with auto-approve on → `needs_human`; a rule's
  action proposal carries `proposed_by="home-rule:…"` and is gated the
  same as the model's; 21-entity call denied; 3am announce denied.
- Tools: `home_call` reports unchanged state honestly; `dry_run`
  answers `would call`; `home_undo` restores brightness AND color;
  `home_camera` without vision says what would configure it.
- Integration (`tests/simorgh/integration/test_home_end_to_end.py`):
  boot the full Kernel with `[home] enabled=true` pointed at
  `FakeHomeAssistant` → a rule "porch on at sunset if anyone home" →
  emit `sun` + `person.home` → assert the fake received
  `light.turn_on porch` and `home.rule.fired` is in the ledger. Then
  `home off` → emit again → nothing. This is the test that proves the
  wire; `feedback_why_tests_missed_it`.
- Boundary test passes (contracts placement; guarded `aiomqtt`).
- `TestBuiltinTools` set updated with all eleven tools; the
  sixteen-subsystems boot test becomes seventeen and its name changes.

## 10. Build order and acceptance

1. **Foundation**: `contracts/home/` (api, client, fakes, policy),
   `home/config.py`, the probe, `home_find`/`home_state`/
   `home_describe`. Acceptance: `capabilities` shows
   `home_assistant … needs HOME_ASSISTANT_URL`; with the fake, a
   trial task "what is the temperature in the bedroom" answers in ≤ 3
   steps.
2. **Acting**: `home_call`, `home_scene`, `home_undo`, `HomeRule`,
   per-call reversibility, `dry_run`. Acceptance: "dim the kitchen to
   40%" → one `HOME_CALL`, before/after reported, `HOME_UNDO` restores;
   "unlock the front door" → `needs_human` with auto-approve on.
3. **Perceiving**: `home/service.py`, bridge, registry refresh,
   presence, `percept.home.*` topics + schemas. Acceptance: ledger
   volume from the fake emitting a sensor every second for 10 min is
   ≤ 20 `home:state` events.
4. **Rules**: engine, store, `home_rule`, scheduler compilation,
   webhook + `POST` routes. Acceptance: the integration test in §9.
5. **Monitors + digest + announce + notify routing.**
6. **Vision + voice + hard-safety export to HA.**
7. **Setup doc** `docs/home/setup.md`: HA install, the six add-ons,
   creating the long-lived token, aliases file, first three rules,
   Tailscale. Written for the creator, not the model.

Each phase: full suite green, commit, push, and one `tools/trial.py`
run against the fake (`feedback_test_primary_interface_first`: drive
the real CLI, not just the bus).

## 11. Traps

- HA returns HTTP 200 for a service call on an unavailable device.
  Re-read state; report what changed.
- `light.turn_on` with `brightness` (0–255) vs `brightness_pct`; HA
  ignores unknown keys silently. Validate against the service schema.
- Echo TTS through `alexa_media_player` is `notify.alexa_media_<name>`
  with `data.type: announce`, not `media_player.play_media`. Encode it
  once in `home_announce`; it is the single most Googled HA question.
- WS `state_changed` for `sensor.*` arrives for every reading; a Zigbee
  temperature sensor can report every 5s. The bridge filter is not
  optional; the 192k-trace incident is the precedent.
- `sun.sun`'s `next_rising` is UTC ISO; convert once, carefully, with
  the HA-reported timezone (`GET /api/config` → `time_zone`).
- Ring `alarm_control_panel` arming has modes (`armed_home` /
  `armed_away`); `disarm` is always-human; `arm` is unattended --
  arming can only make the house safer.
- A rule's `for_s` timer must be cancelled when the trigger reverts;
  otherwise "motion off for 10m" fires after the person came back.
- `home_undo` on a `climate` restores the *target*, never the
  `hvac_mode` if a schedule changed it meanwhile -- compare
  `last_changed` and refuse to undo across a newer change by someone
  else. Say who changed it (HA `context.user_id`).
- Presence from one phone's `device_tracker` is unreliable (Wi-Fi
  sleep). `presence.py` combines: any tracker home OR motion in the
  last 20 min OR a Ring "someone entered" → home; all trackers away
  AND no motion for 60 min → away. State the rule in the tool output
  when asked "is anyone home".
- Never bind the HTTP API's POST routes on a public interface, and
  never accept a webhook without the token -- an unauthenticated
  webhook is `home_call` for anyone who finds the port.

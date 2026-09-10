# Domain 3: Energy and climate intelligence

Sim knows what the house consumes and produces, what it costs by the
hour, and what the thermostat is doing about it -- and it acts: pre-cool
before a peak-rate window, charge the car when solar is high or rates
are low, catch a runaway HVAC, and report the bill before it arrives.
This is the first domain where Sim saves money on a schedule.
Prerequisites: `home-automation-design.md` (HA bridge, thermostat,
sensors, the rules engine), `data-toolset-design.md` (`query_data`),
platform §6 (monitors/digest).

## 0. What exists

- The thermostat and temperature/humidity sensors are in scope for
  `home` (§2.1 domains: `climate`, `sensor`); the bridge already
  publishes filtered numeric percepts.
- `home`'s `climate_runaway` monitor is specified. Nothing knows
  *cost*, *tariff*, *solar*, or *forecast*.
- `results/` + `query_data` can hold and aggregate hourly series.

## 1. Open-source inventory

| component | role | notes |
|---|---|---|
| **HA Energy dashboard** | HA's own consumption/production/cost tracking from any `sensor` with `device_class: energy` | the source of record; Sim reads its statistics (`recorder/statistics_during_period` WS) |
| **EMHASS** (Energy Management for HA, MIT) | model-predictive optimisation: given tariffs, solar forecast, battery, deferrable loads → an hourly plan | the serious optimiser; runs as an HA add-on; Sim *drives* it, does not reimplement it |
| **Open-Meteo** (keyless) | weather + **solar radiation forecast** | already in `_KEYLESS_SOURCES` |
| **Forecast.Solar** (keyless tier) / **Solcast** (key) | PV production forecast for a given array | |
| **Enphase local API / SolarEdge / Fronius / Tesla Powerwall local** | inverter/battery readings | HA integrations; Sim reads entities |
| **Emporia Vue / Shelly EM / IoTaWatt / Sense** (via HA) | per-circuit consumption | the difference between "the house used 30 kWh" and "the dryer used 4" |
| **OpenEVSE / Wallbox / Tesla / ChargePoint** (via HA) | EV charging control | |
| **Tariff data**: utility TOU tables (TOML, hand-entered once), **Octopus/Agile** (UK API), **NREL OpenEI URDB** (US rate database, keyless CSV) | ¢/kWh by hour/season | |
| **Nord Pool / ENTSO-E** (EU) | wholesale prices | if relevant |
| **`pvlib`** | PV physics for a sanity check on the array's expected output | |
| **`statsmodels`/`prophet`** | consumption baselines/anomalies | `statsmodels` is enough |
| **Thermal model**: a 1R1C fit (`scipy.optimize`) from the house's own temperature history | "how fast does the house cool at 5°C outside" → pre-heat timing | small, own code, tested |
| **Grafana** (optional) | dashboards over HA's db | not a Sim dependency |

## 2. Architecture -- part of `home` (no new subsystem): `simorgh/home/energy/`

```
home/energy/
  api.py         Tariff, Rate, Meter, Reading, Forecast, Plan, DeferrableLoad
  tariffs.py     TOU tables, seasonal, tiered; price(at: datetime) -> Rate; sources (toml, urdb, agile)
  meters.py      which HA entities are the grid import/export, solar, battery, per-circuit, EV
  forecast.py    solar (forecast.solar / open-meteo GHI × pvlib) and load (weekday profile × weather)
  thermal.py     1R1C model fit; comfort bands per person/time; pre-heat/cool lead time
  planner.py     the daily plan: for each deferrable load and the HVAC, the cheapest window that respects constraints; EMHASS when installed, own greedy planner otherwise
  cost.py        cost-to-date, projected bill, per-device cost, comparison to last month
  monitors.py    runaway, baseline anomaly, export clipping, battery health, tariff window alerts
  reports.py     the weekly energy digest section
```

Data: hourly rows to `workspace/energy/energy.db` (`readings`,
`costs`, `plans`, `forecasts`) -- `query_data`-able: `select
strftime('%H', ts) h, avg(kw) from readings group by 1`.

## 3. Tools (`execution/energy.py`)

| tool | args | read_only | reversibility |
|---|---|---|---|
| `energy_status` | `range?` | yes | read_only -- now: import/export/solar/battery/HVAC, today's cost so far, current rate, next rate change |
| `energy_report` | `range` (day/week/month/bill-cycle), `by?` (device/hour/circuit) | yes | read_only -- rows → results |
| `energy_forecast` | `horizon?` (24h/48h) | yes | read_only -- solar kWh, load, cost, best windows |
| `energy_tariff` | `op: show\|set`, `spec?` | no | reversible |
| `energy_plan` | `op: show\|make\|apply\|cancel`, `date?` | `apply`: no | reversible -- apply = create the rules/schedules for today's plan (each action still through `home_call`) |
| `climate_set` | `target`, `temp?`, `mode?`, `until?`, `reason?` | no | reversible -- a wrapper over `home_call climate.*` with comfort-band validation and an automatic revert at `until` |
| `climate_schedule` | `op`, `spec?` | no | reversible -- the weekly comfort schedule (per room, per person) |
| `ev_charge` | `op: status\|start\|stop\|plan`, `by?` (time), `min_pct?` | no | reversible |
| `energy_compare` | `a`, `b` | yes | read_only -- two ranges or two devices |

Markers: `ENERGY_REPORT: week\n{"by": "device"}`; `CLIMATE_SET: bedroom\n{"temp": 20, "until": "07:00", "reason": "sleep"}`.

## 4. Config (`[home.energy]`)

```python
enabled: bool = False
grid_import: str = ""       # sensor.* entity ids (energy device_class)
grid_export: str = ""
solar: str = ""
battery_soc: str = ""
circuits: dict[str, str] = {}      # "dryer": "sensor.dryer_energy"
ev: EvSpec | None = None           # charger entity, car soc entity, kw, departure default
thermostats: tuple[ThermostatSpec, ...] = ()   # entity, rooms, sensors, comfort bands
tariff: str = "workspace/energy/tariff.toml"   # or "urdb:<id>" / "agile:<region>"
currency: str = "USD"
solar_forecast: str = "open-meteo"             # open-meteo | forecast.solar | solcast
pv: PvSpec | None = None                       # kwp, tilt, azimuth, lat/lon (geocode tool)
planner: str = "auto"                          # auto | emhass | greedy
comfort_default: tuple[float, float] = (19.0, 24.0)
comfort_max_deviation: float = 2.0             # planner may not exceed this
hvac_hard_limits: tuple[float, float] = (10.0, 32.0)   # HomeRule already refuses outside
bill_day: int = 1
```

## 5. Guardian

- Every actuation is a `home_call` (climate/switch/ev) → `HomeRule`
  applies; `climate_set` outside comfort ± `comfort_max_deviation` →
  escalate; outside hard limits → deny.
- `energy_plan apply` proposes N rules at once → shown as one summary;
  approved as one; each action still individually ledgered.
- Never turns *off* heating below the freeze threshold or a medical
  device circuit (`[home.energy] protected_circuits`) -- deny.
- EV: `stop` while below `min_pct` and departure < 2h → escalate ("you
  may not make it").

## 6. Automations, monitors

- Percepts: `percept.energy.rate_changed`, `percept.energy.solar_surplus
  {kw}` (export > threshold), `percept.energy.plan_step {load, action}`.
- Built-in rules (shipped disabled, one-line enable): pre-cool before
  peak; run dishwasher/dryer in cheapest window (with a "ready by" from
  the person); charge EV on surplus; lower setpoint when nobody home
  (from `home.presence`) with a pre-heat before expected return
  (calendar from domain 2, or the learned weekday pattern).
- Monitors: `hvac_runaway` (moved here from `home`), `baseline_anomaly`
  (kW > 2σ above the hour's baseline for 30 min → "something is on"),
  `solar_underperforming` (actual < 60% of forecast on a clear day →
  panels/inverter), `export_clipping`, `battery_stuck`, `tariff_window`
  (info 10 min before a peak window while a big load runs), `bill_pace`
  (projected > last month × 1.2).
- Weekly digest: kWh, cost, top 5 devices, solar self-consumption %,
  savings from the plan vs. a naive baseline (*measured*, not claimed).

## 7. Tests

- Tariff math: TOU with seasons and holidays; a cost over a DST
  transition day; tiered rates.
- Thermal fit on synthetic data recovers the constants; pre-heat lead
  time is monotone in outdoor temperature.
- Greedy planner: deferrable loads land in the cheapest windows
  respecting `ready_by`; the EMHASS adapter maps the same inputs
  (against a fake EMHASS HTTP endpoint).
- Comfort constraints: a plan never exceeds `comfort_max_deviation`;
  `climate_set` reverts at `until` (FakeClock).
- Monitors with synthetic series.
- End-to-end with `FakeHomeAssistant` sensors: `ENERGY_STATUS` →
  correct cost so far; `ENERGY_PLAN make` → rules; `apply` → proposals
  through Guardian.

## 8. Build order and acceptance

1. Meters + tariff + `energy_status`/`energy_report` + db.
   Acceptance: today's cost matches a hand calculation from HA's
   statistics.
2. Forecasts + thermal model + `climate_set/schedule`. 3. Greedy
   planner + `energy_plan` + built-in rules. 4. EV. 5. EMHASS adapter.
6. Monitors + digest + savings measurement.

## 9. Traps

- HA "energy" sensors are cumulative (`total_increasing`); differencing
  across meter resets needs the `last_reset` attribute.
- Net metering vs. buy/sell tariffs: model export price separately;
  never assume symmetric.
- A thermostat's `hvac_action` lags; a "runaway" needs 3 consecutive
  readings, not one.
- Solar forecast APIs rate-limit; cache per hour; forecast.solar's free
  tier is 12 calls/hour.
- Do not "learn" occupancy and act on it in week one; ship the
  learned schedule as a *suggestion* in the digest for two weeks
  first, then enable.

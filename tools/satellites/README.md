# Room satellites

A room satellite is a [reSpeaker XVF3800](https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY)
four-mic board with a XIAO ESP32S3, running ESPHome, with a speaker on its
3.5 mm jack. It wakes on its own wake word, streams that turn to Sim, and
plays Sim's reply and music. Sim holds the board's voice assistant itself
(`simorgh/voice/satellite.py`); Home Assistant must not.

Design, measurements and the rules learnt on the first board:
`docs/plan/stage-13-room-satellites.md`.

## What is here

| File | What |
|---|---|
| `room.yaml` | The board's ESPHome config, one file for every room: the room is a substitution |
| `voice-assistant-sim.yaml` | The upstream package's `voice-assistant.yaml` with one change: the wake word during Sim's reply stops it **and** listens. Re-copy from upstream when updating, and keep that change |
| `secrets.yaml.example` | Wi-Fi and keys. Copy to `secrets.yaml` (git-ignored) |

## Adding a room

Once, on the Mac:

```sh
python3 -m venv ~/.venvs/esphome && ~/.venvs/esphome/bin/pip install esphome
cp tools/satellites/secrets.yaml.example tools/satellites/secrets.yaml   # then fill it in
```

For each board (about ten minutes; the first build takes longer):

1. Plug the board into the Mac by USB-C.
2. Flash it, naming the room. Use `run`, not `upload`: `upload` flashes the
   binary from the LAST build, and after changing secrets that one joins
   the old network.
   ```sh
   cd tools/satellites
   ~/.venvs/esphome/bin/esphome -s name kitchen -s friendly_name "Kitchen" run room.yaml
   ```
   The first flash also updates the XMOS DSP firmware (about 45 s; the log
   says `DFU version: 1.0.7`).
3. Attach a speaker to the 3.5 mm jack. The board has none of its own.
4. Tell Sim about it in `~/.simorgh/simorgh.toml`:
   ```toml
   [voice]
   secrets = ["SIM_SATELLITE_KEY"]      # add to the list if it has others

   [[voice.satellites]]
   name = "kitchen"                     # the room, and its device name
   host = "kitchen.local"               # the ESPHome node name + .local
   key_env = "SIM_SATELLITE_KEY"
   volume = 1.0
   ```
   and the key in `~/.simorgh/secrets.toml`: `SIM_SATELLITE_KEY = "<api_key from secrets.yaml>"`.
   All boards may share one key; give a room its own by using another
   `key_env` name and building it with its own `secrets.yaml`.
5. Restart Sim. `voice status` and the log (`voice.satellite ... connected`)
   show it; say the wake word in that room.

Later changes go over Wi-Fi: the same `esphome ... run room.yaml` finds the
board by name.

## Using it

- Speak after the wake word; the board plays Sim's reply. A reply that
  ends with a question opens the mic again for a few seconds, no wake word.
- "Play jazz" (or a station name, or a URL) plays on the board you spoke
  to; "stop the music" stops it.
- `voice mute laptop` mutes the Mac's microphone and leaves the rooms
  listening; `voice mute kitchen` mutes one room. Bare `voice mute` stops all.
- While a board's wake word is open, the laptop leaves that speech to it.

## Known limits

- The board plays FLAC and MP3 by URL. It refused WAV; AAC is untested.
- Its PLAYING/IDLE state lags real playback by up to ~10 s; Sim never reads it.
- Wake words: okay_nabu, hey_jarvis, hey_mycroft, kenobi from upstream, and
  Simorgh's own "Hey Sim" (`wakewords/hey_sim/`, trained 2026-09-27; cutoff
  0.42 by default, selectable on the board as "Wake word sensitivity").
- The board's media player can jam: it logs "Queue full, URI dropped" and
  plays nothing while Sim believes its replies went out. Sim clears it with
  STOP; if the board answers "Queue full, command dropped", Sim presses the
  firmware's own **Restart** button (the upstream package defines it; it is
  hidden in Home Assistant's UI but present on the API) and the board is
  back in about a minute. Keep that button if you change the packages.
- `~/esphome-sim` was the first bring-up's scratch folder (2026-09-25); this
  folder superseded it and is what to flash from.

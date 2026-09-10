# Domain 5: Media and content

Sim knows the household's media -- what is in the library, what is
playing where, what was watched -- and runs it: "play the jazz playlist
in the kitchen and the living room, quietly", "what was that show we
watched last week", "record this stream for later", "put the doorbell
camera on the kitchen Echo Show". Prerequisites: `home-automation-
design.md` (media_player entities, Echos, Chromecasts, TVs through HA),
`voice-design.md` (announcements share the audio path), platform §3.

## 0. What exists

- HA's `media_player` domain is in `home`'s config; `home_call
  media_player.*` works for play/pause/volume/source; nothing knows
  *content* (library, playlists, history).
- `alexa_media_player` is in the home inventory for announcements.
- `yt-dlp`, `mutagen`, `beets`, `ffmpeg` python bindings absent;
  `ffmpeg` binary present.

## 1. Open-source inventory

| component | role | notes |
|---|---|---|
| **Jellyfin** (GPL) | media server: movies/TV/music library, users, watch history, transcoding, REST API | the open one; **primary**. Plex is supported through the same connector interface (its API is documented) |
| **Navidrome** (GPL) / **Subsonic API** | music-first server, playlists, scrobbling | if music is the main use |
| **Music Assistant** (Apache-2, an HA add-on) | *the* multi-room audio controller: Spotify/Tidal/YouTube Music/local library → Sonos/Cast/AirPlay/Echos (via alexa_media)/DLNA, grouping, sync | this is the piece that makes "play X in rooms Y and Z" one call; Sim drives it through HA |
| **Snapcast** | synchronous multi-room audio for DIY players (Pis) | when Music Assistant needs a player in a room without a smart speaker |
| **Kodi** (JSON-RPC) / **LibreELEC** | TV playback on an HDMI box | HA integration |
| **`yt-dlp`** | download/record from thousands of sites; extract metadata | for "save this for later"; respects the creator's judgement on rights -- Sim states the terms it can see and proceeds unless denied (the resourcefulness rule) |
| **Radio Browser** (keyless API) | internet radio stations | |
| **Podcast index** (`podcastindex.org`, free key) / RSS | podcasts | RSS needs no key |
| **`beets`** | music library tagging (MusicBrainz, keyless) | library hygiene |
| **`mutagen`** / **`ffprobe`** | file metadata | |
| **OpenSubtitles** (key) / **Whisper** (from voice-design) | subtitles; **local transcription of any media file** ("what did they say at 12:30") | the voice STT is reused |
| **TMDB / OMDb / MusicBrainz / Discogs** | metadata (TMDB free key; MusicBrainz keyless) | |
| **Frigate / go2rtc** (already in home) | camera streams as media: WebRTC/HLS URLs for casting to an Echo Show or TV | |
| **Immich** (AGPL) | photos/videos with ML search, faces, map | a connector: "show the photos from the lake trip on the TV" |
| MCP: Jellyfin MCP, Spotify MCP | secondary | |

## 2. Architecture -- `simorgh/media/` (subsystem #23)

```
media/
  api.py         Library, Item(kind: movie|episode|track|album|playlist|podcast|station|stream|photo), Player(room, capabilities), NowPlaying, History
  config.py
  connectors/    jellyfin.py plex.py navidrome.py music_assistant.py (via HA) kodi.py immich.py radio.py podcasts.py ytdlp.py
  players.py     the player table: HA media_player entities + Music Assistant players + Kodi, with room from home.registry; capability flags (video, group, tts)
  resolve.py     "the jazz playlist" / "that show we watched" → Item; fuzzy over titles, artists, recent history
  queue.py       Sim-side play queue per room (when the backend has none)
  history.py     what played where, from HA state history + Jellyfin sessions → workspace/media/history.db
  service.py     sync library metadata (incremental), monitors, digest
  fakes.py       FakeJellyfin, FakeMusicAssistant, FakePlayers
```

## 3. Tools (`execution/media.py`)

| tool | args | read_only | reversibility |
|---|---|---|---|
| `media_search` | `query`, `kind?`, `library?` | yes | read_only -- rows → results |
| `media_play` | `what`, `where` (room/player/"here" from voice), `volume?`, `shuffle?` | no | reversible (previous state snapshot, `home_undo`-style) |
| `media_control` | `op: pause\|resume\|next\|prev\|stop\|volume\|mute\|seek`, `where`, `value?` | no | reversible |
| `media_group` / `media_ungroup` | `rooms` | no | reversible |
| `media_now` | `where?` | yes | read_only |
| `media_history` | `range?`, `who?`, `kind?` | yes | read_only |
| `media_queue` | `op: show\|add\|clear`, `where`, `what?` | no | reversible |
| `media_cast` | `stream` (a camera, a URL, a photo album), `where` (a screen) | no | reversible |
| `media_save` | `url`, `as?` | no | irreversible (a download) | rate-limited; lands in `workspace/media/downloads/` |
| `media_transcribe` | `item`, `range?` | yes | read_only | Whisper from voice-design; cached |
| `media_library` | `op: status\|scan\|tag`, `spec?` | no | reversible |
| `media_playlist` | `op: create\|add\|remove\|list`, `name`, `items?` | no | reversible |

Markers: `MEDIA_PLAY: jazz playlist\n{"where": ["kitchen", "living room"], "volume": 25}`;
`MEDIA_CAST: camera.front_door\n{"where": "kitchen echo show"}`.
Voice fast path (voice-design §5.2) gains: `play <x> (in|on) <room>`,
`pause|stop|next|louder|quieter (in <room>)`, `what is playing`.

## 4. Config (`[media]`)

```python
enabled: bool = False
servers: tuple[ServerSpec, ...] = ()        # kind, url, cred_id, libraries include, privacy
music_controller: str = "auto"              # auto | music_assistant | ha_native
default_volume: int = 30
max_volume_unattended: int = 60             # a rule may not go louder
quiet_hours_max_volume: int = 20
history: bool = True
history_retention_days: int = 365
downloads_dir: str = "workspace/media/downloads"
downloads_max_gb: float = 20
transcribe_cache_dir: str = "workspace/media/transcripts"
kids_profiles: tuple[str, ...] = ()         # speakers (voice-design) whose requests are filtered by rating
```

## 5. Guardian

- `media_play`/`media_control volume` above `max_volume_unattended`
  → escalate; in quiet hours above `quiet_hours_max_volume` → deny
  unless `urgent` (an alert announcement uses the voice path, not
  this).
- `media_cast` of a *camera* to a screen → reversible but ledgered
  with who asked (a camera on a screen is a privacy act); casting
  cameras to a screen outside the house (a cast target not in
  `home`'s registry) → deny.
- `media_save` → escalate; ≤ 10/day; never to a path outside
  `downloads_dir`; `yt-dlp` runs with `--no-exec`, `--no-playlist`
  unless asked, size cap.
- Kids profiles: rating filter enforced in `resolve.py` before a
  proposal exists; an override needs an adult speaker.

## 6. Automations and monitors

- Percepts: `percept.media.started {item, where, who}`, `stopped`,
  `percept.media.new_in_library`.
- Built-in rules (disabled by default): "movie starts in the living
  room after sunset → lights 10%" (uses `home` engine, `event`
  trigger); "doorbell rings while a movie plays → pause + cast camera
  to the TV for 20 s → resume"; "nobody home → stop all playback";
  "bedtime scene → fade volume over 5 min".
- Monitors: `server_unreachable`, `library_scan_failed`, `player_stuck`
  (playing with no position change for 5 min), `downloads_full`.
- Digest: what was watched/listened (per person if speaker-id), new
  library items, unfinished series ("you are on S2E4").

## 7. Tests

- Connectors against fakes: library sync incremental; history import;
  play/pause/volume map to the right HA service or MA call.
- `resolve.py`: "that show we watched last week" → the item from
  history; ambiguity asks; kids filter.
- Multi-room: `media_play` with two rooms groups via MA when present,
  falls back to sequential plays with a warning when not.
- Guardian volume/quiet-hours rules; camera cast targets.
- `media_save` sandboxing (path, size, flags).
- End-to-end: FakeJellyfin + FakePlayers → `MEDIA_PLAY: jazz playlist`
  in two rooms → both fake players playing at 25%; `MEDIA_CONTROL
  pause` → paused; undo → previous state.

## 8. Build order and acceptance

1. Players table from `home` + `media_now`/`media_control`.
   Acceptance: "what is playing in the kitchen" and "pause it" through
   the CLI against the fake.
2. Jellyfin connector + search + `media_play` by title.
3. Music Assistant multi-room + playlists + voice fast path.
4. History + digest + built-in rules. 5. `media_cast` (cameras,
photos via Immich). 6. yt-dlp save + transcribe. 7. Plex/Navidrome/
Kodi connectors.

## 9. Traps

- Echos as Music Assistant players go through `alexa_media_player`
  and support only a subset (no seek, flaky grouping); say so in
  `media_group` when an Echo is in the group.
- HA `media_player.play_media` needs a `media_content_type` that
  differs by integration; the connector layer owns that mapping.
- Jellyfin "sessions" for history are per client; a Chromecast started
  by Sim shows as a Jellyfin session only if cast *through* Jellyfin.
- Transcribing a 2-hour film is ~15 min on CPU; `media_transcribe`
  returns a job and the digest reports when done -- do not block a
  turn on it.
- Downloads: check free disk before, not after.

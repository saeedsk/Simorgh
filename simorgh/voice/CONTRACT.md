# voice -- contract

One-line status: layer 5 · 11,279 lines · 45 test files · lock: `voice` in docs/modules/locks.toml

## Purpose

Voice owns the spoken channel on this laptop: microphone frames, endpointing and turn-taking, speech-to-text, who is speaking (the speaker book, diarization, enrolment), the spoken-response planner, text-to-speech engines and interruptible playback. It decides nothing about content: a spoken turn becomes `percept.text.received{channel: "voice"}` and rides the same Orchestration and Cognition path as typed text, and the answer comes back as `turn.completed` keyed by the percept's `session_id` (`pipeline.py:348-367`). It must never call the model or a tool itself, never publish `system.restart` (a spoken restart goes through Interface as `ui.command.request`, `session.py` `_restart`), and never fail boot for want of audio: every engine is optional, probed at boot, opened on first use and refused by name when missing (`service.py` docstring). The shaping decision: `VoiceSession` (`session.py`) is a streaming state machine whose floor changes are decided only in `turns.py`, and turns may overlap by design, so any fact about one turn belongs on that turn's record (the `TurnClock`, the per-turn facts dict), never in a session-wide attribute read across an await.

## Files

| File | For |
|---|---|
| `simorgh/voice/__init__.py` | Package docstring; exports nothing but `Service` via the Kernel |
| `simorgh/voice/service.py` | The `Service`: bus request handlers, engine opening, on/off, probes, `speak_replies` |
| `simorgh/voice/session.py` | `VoiceSession`: the live streaming conversation loop, per-turn clocks, speaker id, kept-audio pruning |
| `simorgh/voice/turns.py` | `TurnManager`: who has the floor (idle, listening, user_speaking, thinking, agent_speaking) |
| `simorgh/voice/pipeline.py` | Older capture-then-answer loop; still the bus seam (`ask`, `_publish`, `voice:turns` record) the session reuses |
| `simorgh/voice/api.py` | Data shapes (`Audio`, `Utterance`, `VoiceTurn`, `VoiceState`, ...) and engine protocols |
| `simorgh/voice/config.py` | `[voice]` dataclass and `wants_listening` |
| `simorgh/voice/settings.py` | `voice set`: the safe subset of keys, validated and persisted |
| `simorgh/voice/vad.py` | Endpointing, frame VAD, echo tracker, barge-in level gate |
| `simorgh/voice/aec.py` | NLMS echo canceller (constructed only on the `Pipeline` path, V7) |
| `simorgh/voice/audio.py` | Microphone and speaker backends (sounddevice, ffmpeg, afplay), WAV helpers |
| `simorgh/voice/playback.py` | `StreamingPlayer`: interruptible chunked playback under one speech lock |
| `simorgh/voice/planner.py` | Spoken-response planner: speakable text, chunking, connectors, leaked-marker removal |
| `simorgh/voice/delivery.py` | Pace, loudness and pauses chosen from the situation and mood |
| `simorgh/voice/backchannel.py` | "aha"/"let me check" sounds; addressed-to-Sim and quiet-reply detection |
| `simorgh/voice/stt/whisper_server.py` | whisper.cpp kept loaded over HTTP; ends servers a previous Sim orphaned (`reap_orphaned_servers`) before starting one |
| `simorgh/voice/commands.py` | "stop", "be quiet", "voice off", "restart" handled without the model |
| `simorgh/voice/speakers.py` | Speaker embeddings and the household voice book (identify, enrol, refine) |
| `simorgh/voice/diarize.py` | Who said which words within one turn |
| `simorgh/voice/introduce.py` | The meet-a-new-voice conversation and "learn X's voice" |
| `simorgh/voice/calibration.py` | `voice calibrate`: per-take quality checks, the manifest, `load()` for reuse, `wer()` |
| `simorgh/voice/calibration_script.py` | The versioned lines read for calibration (51 English, 16 Farsi, stable ids) |
| `simorgh/voice/pronounce.py` | Name pronunciations (IPA or respelling) per engine |
| `simorgh/voice/repeat.py` | Detects the same question asked again |
| `simorgh/voice/lang.py` | Reply language from script, for engine routing |
| `simorgh/voice/resample.py` | Resampling for the echo reference |
| `simorgh/voice/health.py` | Machine notes (battery, throttling) for `voice status` |
| `simorgh/voice/bench.py` | `voice bench` measurements |
| `simorgh/voice/fakes.py` | Deterministic fake engines and devices for tests and `stt = "fake"` |
| `simorgh/voice/stt/` (`__init__`, `faster_whisper`, `whisper_cli`, `whisper_server`, `sherpa_stream`, `streaming`) | Speech-to-text engines, `open_recogniser`, and incremental partials over a whole-utterance recogniser |
| `simorgh/voice/tts/` (`__init__`, `kokoro`, `piper`, `say`, `chatterbox`, `miso`, `styletts2`, `lanes`, `streaming`, `subproc`) | Text-to-speech engines, per-language `open_synthesiser`, quick/expressive lanes, streaming synthesis, subprocess engine protocol |
| `simorgh/voice/tts/servers/` (`chatterbox_server`, `miso_server`, `styletts2_server`) | Standalone line servers run in each engine's own venv; no simorgh imports |

## Consumes

Subscriptions are exactly `Service.consumes` (`service.py:38-45`, pinned by `tests/simorgh/test_manifests_match_the_code.py`).

| Topic | Schema | Where | Does |
|---|---|---|---|
| `voice.status.request` | `messages/voice.py::VoiceStatusRequest` | service.py:358 | Replies with `VoiceState` plus session state and metrics |
| `voice.control.request` | `messages/voice.py::VoiceControlRequest` | service.py:361 | on/off/mute, `voice set`, enrol and people actions; refusals as error replies. `action: "calibrate"` (`value` start [options] | status | stop | keep | accept | skip; `name`) runs the calibration set. |
| `voice.speak.request` | `messages/voice.py::VoiceSpeakRequest` | service.py:618 | `voice test` / speak a text now |
| `voice.listen.request` | `messages/voice.py::VoiceListenRequest` | service.py:649 | One transcription without asking Sim |
| `voice.voices.request` | `messages/voice.py::VoiceVoicesRequest` | service.py:669 | Lists the synthesiser's voices |
| `voice.devices.request` | `messages/voice.py::VoiceDevicesRequest` | service.py:682 | Lists audio devices |
| `voice.models.request` | `messages/voice.py::VoiceModelsRequest` | service.py:740 | Locates or fetches a whisper model |
| `voice.bench.request` | `messages/voice.py::VoiceBenchRequest` | service.py:600 | Runs `voice bench` |
| `turn.completed` | `messages/task.py::TurnCompleted` | pipeline.py:229; service.py:696 | Resolves the pending spoken ask by `session_id`; with `speak_replies`, speaks replies to typed (`channel == "cli"`) turns |
| `task.failed`, `task.blocked` | `messages/task.py` | pipeline.py:260 | Resolves a pending ask whose task id is its session id; a cancelled one is dropped silently |
| `persona.state.changed` | `messages/persona.py::PersonaStateChanged` | service.py:689 | Mood (valence, arousal) colours delivery |
| `ui.tv.state` | `messages/ui.py::TvState` | pipeline.py:217 | Keeps what the TV is playing for the prompt's room line |
| `tool.started` | `messages/tool.py::ToolStarted` | pipeline.py:229 | A slow tool (recent p95 over `[voice] filler_over_ms`) gets one short spoken line while it runs (stage 3 item 5) |

## Produces

The publish direction is not pinned by the manifest test; `session.py` publishes through `Pipeline._publish`.

| Topic | Schema | Where | When |
|---|---|---|---|
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | pipeline.py:367 | Every spoken turn addressed to Sim: `channel="voice"`, `session_id`, `confidence`, `device`, and `speaker`, `speaker_relation`, `speaker_before`, `room` when known; `speaker_doubt` when the name is not certain (`speakers.doubt_of`: a probable match, a runner-up within `SURE_GAP` 0.08, or a score under threshold + 0.08); `speaker_score` ("0.47 against a bar of 0.30") whenever the book named the speaker |
| `voice.transcript` | `messages/voice.py::VoiceTranscript` | pipeline.py:306; session.py (partials, finals, asides) | A calibration take carries `enrolling: <person>` and `speaker_note` "" (kept), "not kept", or the control word. Partial and final transcripts, echoes and not-for-Sim lines. `seconds` is how long the person spoke, from the VAD's own marks (`_spoken_seconds`); every final published a hard-coded `0.0` until 2026-09-20, which silently disabled the speaking-pace signal behind a companion check-in -- the World Model keeps a reading only when `seconds > 0` |
| `voice.spoken` | `messages/voice.py::VoiceSpoken` | pipeline.py:418; session.py (many) | After each reply, aside, command or quiet outcome |
| `voice.listening` | `messages/voice.py::VoiceListening` | pipeline.py:563; session.py:366 | Each floor-state change |
| `task.cancel` | `messages/task.py::TaskCancel` | session.py:639 | A newer turn supersedes an older ask still thinking |
| `ui.command.request` | `messages/ui.py::UiCommandRequest` | session.py `_restart` | "restart" said by a known voice under the loader |
| `ui.notice` | `messages/ui.py::UiNotice` | session.py `_report_synthesis`, `_calibration_after` | A voice fell back or a reply could not be synthesised; during `voice calibrate` (source `voice calibrate`), each verdict and the next line to read (`warn` for a refused take, with the reason) |
| `ui.tv.speech` | `messages/ui.py::TvSpeech` | session.py (end of file) | `output = "tv"`: each synthesised piece as a blob ref for the TV page |
| `voice.control.request` | `messages/voice.py::VoiceControlRequest` | session.py (commands) | "voice off" / "mute" said aloud, handed to the Service |
| `voice.*.reply` (status, control, speak, listen, voices, devices, models, bench) | `messages/voice.py` | service.py `_reply` | Reply to each request above, only when it has `reply_to` |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `voice:turns` | pipeline.py:31 `TURNS_STREAM` (append in `_record`, when `keep_transcripts`) | ledger compaction; tools and findings read it for latency | 30d |
| `capabilities` | service.py:36 (presence probes at boot) | orchestration (replay), execution | forever |

Blobs: `ui.tv.speech` audio (`ledger.put_blob`). Files outside the ledger: the calibration set (`calibration_dir`/<person>/: a 16 kHz int16 WAV per accepted take, `<line_id>-<ms>.wav`, and `manifest.jsonl`, one JSON row per take -- line_id, script_version, script_text, reference, romanisation, language, tags, person, recorded_at, device, microphone, sample_rate, duration_s, speech_s, speech_dbfs, noise_dbfs, snr_db, clipping, speaker_score, speaker_bar, profile_coherence, profile_takes, stt_engine, stt_transcript, stt_language, stt_confidence, wer, room, distance, aloud, file, and `reference_from`/`misread_overridden` when the person overrode a misread; NEVER pruned, and it belongs in backups -- it is the recording nobody wants to make twice), the speaker book (`speakers_dir`), kept audio and transcripts (`audio_dir`, pruned by `keep_audio_days`/`keep_audio_max_mb`), the overheard store (`overheard_dir`, via `contracts/overheard.py`). The generated `faster_whisper:`, `whisper_cli:`, `whisper_server:` and `you:` rows were engine labels and prompt text, not streams.

## Config

`[voice]` in simorgh.toml; dataclass in `simorgh/voice/config.py`. `voice set` persists the safe subset (`settings.py`); `_ENGINE_KEYS` reopen engines and `_SESSION_KEYS` rebuild the session (`service.py:67-70`).

| Key | Default | Read in the package |
|---|---|---|
| `enabled` | `'auto'` | yes |
| `stt` | `'auto'` | yes |
| `stt_stream_model` | `''` | yes |
| `stt_server_port` | `0` | yes |
| `stt_model` | `'large-v3-turbo'` | yes |
| `stt_language` | `''` | yes |
| `stt_languages` | `'en,fa'` | yes |
| `stt_compute` | `'auto'` | yes |
| `tts` | `'auto'` | yes |
| `tts_voice` | `'af_jessica'` | yes |
| `tts_speed` | `1.3` | yes (Kokoro natively; StyleTTS2 by dividing the model's phoneme durations since 2026-09-19) |
| `tts_by_language` | `True` | yes |
| `tts_farsi_voice` | `'fa_IR-amir-medium'` | yes |
| `vad` | `'auto'` | yes |
| `vad_threshold` | `0.5` | yes |
| `endpoint_silence_ms` | `1000` | yes |
| `max_utterance_s` | `30.0` | yes |
| `wake_word` | `''` | NO (declared, never read) |
| `follow_up_window_s` | `6.0` | NO (declared, never read) |
| `barge_in` | `True` | yes |
| `barge_in_speech_ms` | `350` | yes |
| `barge_in_calibrate_ms` | `1200` | yes |
| `barge_in_ratio` | `2.8` | yes |
| `barge_in_known_voice` | `False` | yes |
| `aec` | `True` | yes (only by `Pipeline`'s capture path, which the live `VoiceSession` never runs: V7) |
| `aec_taps` | `1024` | yes (Pipeline path only, V7) |
| `aec_mu` | `0.3` | yes (Pipeline path only, V7) |
| `aec_residual_threshold` | `0.02` | yes (Pipeline path only, V7) |
| `volume` | `1.0` | yes |
| `output` | `'laptop'` | yes |
| `tv_audio_lag_s` | `2.5` | yes |
| `auto_listen` | `True` | yes |
| `vad_sensitivity` | `'high'` | yes |
| `min_speech_ms` | `250` | yes |
| `max_turn_ms` | `30000` | yes |
| `hold_reply_max_s` | `1.5` | yes |
| `hold_unprompted_max_s` | `8.0` | yes |
| `semantic_silence_factor` | `0.75` | yes |
| `stt_partials` | `True` | yes |
| `stt_partial_every_ms` | `1500` | yes |
| `connectors` | `True` | yes |
| `max_spoken_sentences` | `3` | yes |
| `tts_lookahead` | `2` | yes |
| `tts_stall_timeout_s` | `20.0` | yes |
| `tidy` | `True` | yes |
| `backchannel` | `True` | yes |
| `backchannel_after_ms` | `2500` | yes |
| `backchannel_gap_s` | `12.0` | yes |
| `exchange_window_s` | `20.0` | yes |
| `continuation_quiet_s` | `12.0` | yes |
| `unplaced_needs_name` | `True` | yes |
| `unplaced_follows_conversation` | `True` | yes |
| `conversation_window_s` | `180.0` | yes |
| `still_after_s` | `20.0` | yes |
| `filler_over_ms` | `2000` | yes | A tool whose recent p95 exceeds this is covered by one spoken line while it runs (stage 3 item 5); 0 turns it off |
| `hum` | `True` | yes |
| `hum_after_ms` | `6000` | yes |
| `hum_gap_s` | `10.0` | yes |
| `expressive` | `True` | yes |
| `diagnostics` | `True` | yes |
| `speak_replies` | `False` | yes |
| `reply_timeout_s` | `95.0` | yes |
| `min_confidence` | `0.6` | yes |
| `speaker_id` | `'auto'` | yes |
| `speaker_threshold` | `0.5` | yes |
| `speaker_margin` | `0.06` | yes |
| `speaker_lean` | `0.45` | yes |
| `speaker_refine` | `True` | yes |
| `speaker_refine_above` | `0.05` | yes |
| `diarize` | `True` | yes |
| `diarize_min_s` | `3.5` | yes |
| `diarize_words` | `False` | yes |
| `speakers_dir` | `'workspace/voice/speakers'` | yes |
| `introduce_after_turns` | `0` | yes |
| `bystander` | `True` | yes |
| `background_quiet` | `True` | yes |
| `background_after_quiet` | `2` | yes |
| `background_window_s` | `120.0` | yes |
| `tone_blend` | `1.0` | yes |
| `venv_dir` | `'workspace/voice/venvs'` | yes |
| `chatterbox_reference` | `''` | yes |
| `references_dir` | `'workspace/voice/references'` | yes |
| `chatterbox_exaggeration` | `0.0` | yes |
| `miso_reference` | `''` | yes |
| `miso_repo` | `'workspace/voice/engines/MisoTTS'` | yes |
| `miso_device` | `''` | yes |
| `miso_tokenizer` | `'unsloth/Llama-3.2-1B'` | yes |
| `styletts2_reference` | `''` | yes |
| `styletts2_embedding_scale` | `0.0` | yes |
| `expressive_timeout_s` | `180.0` | yes |
| `expressive_warm_delay_s` | `90.0` | yes |
| `expressive_lane` | `'auto'` | yes |
| `expressive_min_chars` | `0` | yes |
| `keep_audio` | `False` | yes (live config sets it true) |
| `keep_audio_days` | `7.0` | yes (session.py `prune_kept_audio`; 0 disables) |
| `keep_audio_max_mb` | `500.0` | yes (same) |
| `audio_dir` | `'workspace/voice/audio'` | yes |
| `calibration_dir` | `'workspace/voice/calibration'` | yes (service.py `_calibrate`, `_relearn_from_calibration`; calibration.py `load` default). Never pruned; back it up |
| `keep_transcripts` | `True` | yes |
| `device` | `'laptop'` | yes |
| `model_dir` | `'workspace/voice/models'` | yes |
| `microphone` | `'auto'` | yes |
| `speaker` | `'auto'` | yes |
| `fake_transcript` | `'hello sim'` | yes |
| `overheard_dir` | `'workspace/voice/overheard'` | yes |

The four `aec*` keys affect only the legacy `Pipeline` capture path; the live `VoiceSession` never constructs the echo canceller, so in a running Sim they change nothing (V7). There is no `overheard_hours`: the overheard store keeps 48 hours (`contracts/overheard.py` `MAX_AGE_S`) whoever writes it; the unread key was removed on 2026-09-19 rather than kept as a setting that looks live (`tests/simorgh/voice/test_config_keys.py`).

## Public Python surface

- `simorgh.voice.service.Service` (`service.py:135`): the Subsystem, built only by the Kernel (`kernel/registry.py:136`). Constructor takes an optional `Config` and injected `microphone`, `speaker`, `recogniser`, `synthesiser` (tests use `fakes.py`). No other package imports anything from `simorgh.voice`.
- `simorgh.voice.calibration` (for `tools/stt_calibration.py` and any later measurement or retraining; no other package imports it): `load(person=None, language=None, *, folder=None) -> list[Take]` (float samples in [-1, 1), `sample_rate`, `reference`, `language`, `romanisation`, `meta` = the manifest row, `.pcm` back as int16 bytes); `wer(reference, hypothesis)` and `word_errors(...) -> (errors, reference_words)`, word-level Levenshtein after `normalise` (case, punctuation in both scripts, ي/ی ك/ک and the other Arabic letter variants, diacritics, ZWNJ and detached Persian particles, Persian and Arabic-Indic digits, English and Persian number words to digits); `CalibrationRun`, `measure`, `read_rows`, `summary`. `calibration_script.LINES`/`SCRIPT_VERSION`: a line id never changes meaning; new lines take new ids and bump the version.
- `api.py` types and protocols are internal to the package; the wire shapes are `simorgh/contracts/messages/voice.py`, `percept.py` and `task.py`.
- `api.py::QUIET_MODEL_ENV`, `api.py::quiet_model_flags(env)` and `api.py::hush_model_progress(env=None)`: the flags that keep a model library's progress bar off the terminal (`HF_HUB_DISABLE_PROGRESS_BARS`, `TQDM_DISABLE`). `tts/subproc.py::engine_env` puts them in every engine subprocess's environment; an in-process model load (`stt/faster_whisper.py`) calls `hush_model_progress()` before importing its package. A blank value counts as unset; a deliberate `0` is left alone. Both are library switches -- nothing redirects stdout or stderr.
- From `simorgh.contracts` it uses `topics`, `envelope.Event`, `protocols.Context/Health`, `household.HOUSEHOLD` (names and relations), `overheard` (the room-text store Execution reads), `tone`, `tidy`, and `settings` for persisting `voice set`.
- Module-level mutable state (risks): `health._cache` (a 60 s cache of `pmset` output, harmless). The real shared state is per-instance but process-wide in effect: one `Pipeline` and one `VoiceSession` per Service, holding the speech lock, `_pending` asks and the speaker book; `service.py` reaches into `Pipeline` private attributes (`_mic`, `_stt`, `_tts`, `_pending`), and `session.py` calls `Pipeline._publish` ~40 times (V7).

## Invariants

A reply is cut at `max_spoken_sentences` (3) and says there is more on screen -- UNLESS the person asked to be told something: `planner.narration_wanted` reads their own words ("tell me a story", "read me", "recite") and raises the cap to `NARRATION_SENTENCES` (40), halving the between-sentence pause as it goes. Three sentences is right for "what is the weather" and wrong for a story, and pointing a person at a screen is not a way of telling one (the creator, 2026-09-20, asking for the Arabian Nights). What was cut is kept on the session, so "go on" reads the REST rather than asking the model again -- which would give a different continuation and lose the thread.

1. A spoken turn reaches Sim only as `percept.text.received` with `channel == "voice"`; Voice never publishes `cognition.think` or `action.proposed`.
   Sim's own name is matched in BOTH languages, by `session._names_sim` and `backchannel._NAMED`, and the two lists must agree: `_names_sim` carried no Farsi at all until 2026-09-22, so a turn that said سیم was not heard as naming Sim although `_NAMED` had matched it since the start. The English variants are what the recogniser actually writes, measured by replaying the creator's calibration set through the real recogniser (`tools/voice_replay.py`); `see`, `see him` and `team` count only in name position (start of the line, followed by a comma).
2. "Be quiet", "silence", "shut up", "ساکت باش" HUSH Sim (`commands.HUSH`): it says one short line naming how to bring it back, then nothing at all until somebody asks for it BY NAME (`wants_to_talk_again`: "hey sim you talk now") or the time it was given runs out (`hush_seconds`; no time given means until asked). Distinct from `STOP`, which cuts the sentence in flight and then carries on as before. The creator, 2026-09-22: a house wants to tell the thing in the corner to leave them alone and have it mean it.
2. A turn the model answers QUIET (`session._stay_quiet` -> `turns.quiet_reply`) asked NOTHING: it gives the floor back to whatever was owed before it, and never counts as "a later turn was asked". The room's own noise becomes turns -- about six a minute in a live house -- and each one used to retire the question somebody was actually waiting on, pushing it off `_superseded` (OWED_KEPT slots) until its answer was dropped: nine dropped in one evening, every reply on screen and none of them spoken (2026-09-22). A later REAL question still supersedes.
2. A reply is matched to its ask by `session_id` on `turn.completed` (or `task_id` on `task.failed|blocked`); a reply whose `channel` is not `cli` is never spoken by `speak_replies`, and nothing is spoken after `voice off` (`service.py:696-726`).
3. Voice never publishes `system.pause|stop|resume|restart|reload` (`PUBLISH_ONLY_BY`, `contracts/topics.py:293-303`); a spoken restart is `ui.command.request{"line": "restart"}` and only for a recognised voice under the loader (`session.py` `_restart`).
4. Per-turn facts live on the turn's own record, never on the session: the `TurnClock` for timings and text, and the per-turn facts dict keyed by turn id for speech seconds, skip reason and PCM (`session.py` `_facts`/`_identify`); a value set for turn N is never read for turn N+1 after an await (V8, the 2026-09-18 lesson).
5. A superseded quiet turn does not move the floor: `_stay_quiet` returns to LISTENING only when the quiet turn is `TurnManager.asked_turn` (V1, commit 1f68f37).
6. Only one voice speaks at a time: every playback takes the one speech lock, and the echo tracker is told when Sim is speaking (`session.py` `say`).
7. Spoken commands (stop, quiet, voice off, restart) are handled locally and never sent to the model (`commands.py`).
8. Boot never fails for want of audio; a missing engine is reported by name with what to install, and presence probes are appended to `capabilities` at boot.
9. Kept audio is bounded: after each kept turn, files older than `keep_audio_days` or beyond `keep_audio_max_mb` are deleted with their transcripts (`session.py` `prune_kept_audio`).
10. The echo bar is infinite only while a gain has never been MEASURED (`EchoTracker.learnt`) AND Sim is making a sound at that instant (`reference(now) >= MIN_REFERENCE`); in a pause wider than `BEFORE_S` there is nothing to mask and the bar is zero, so a person is heard at once even in the first reply. A reply ending settles what it measured (`EchoTracker.settle`, called from `session._play`) and settles nothing when it measured nothing. Both halves of this were wrong in turn on 2026-09-20. First, a room where the mic hears nothing of Sim measures zero -- correct, Sim is inaudible to itself and the person is always louder -- and reading that as "not learnt yet" put the bar at infinity for the start of every reply: the "Sim, can you hear me?" of a quiet kitchen 30 cm from the speaker, reproduced as every other beat unheard (`live/a-whole-conversation`, 4/6 before, 6/6 after). The fix for it then called an UNMEASURED reply learnt, so one reply where no mic frame landed during playback (half-duplex device, a reply ending between frames) declared the room quiet on no evidence and left the bar at zero, which Sim's own echo clears -- the creator the same evening: "it seems heared back its voice at some part". A measured zero stays provisional: `observe` keeps sampling and `expected` takes `max(gain, this reply's middle)`, so a room that does echo raises the bar without waiting for a restart.
11. A sentence naming who it is for, when that is not Sim, is an aside and the model is never asked (`backchannel.to_someone_else`, `session._named_somebody_else`): a vocative only -- an endearment or a household name, at one end of the sentence, set off by a comma -- and never when Sim is named too, and never inside a conversation Sim is already in. Question-shape does not argue with it: with a real provider "Can you try a bit harder next time, honey." was answered "Sorry, Devin -- tell me what I got wrong and I'll fix it". Every deterministic quiet rule now also stamps `_quiet_on`, so `_continuation` covers the second half of a sentence whisper cut in two; it did not, because only the model's own QUIET used to stamp it.
12. A request for something only Sim does is for Sim even when nobody says so (`backchannel.asks_for_something_sim_does`, checked inside `session._bystander`): setting a timer, a reminder, a light or the music, reading or telling something, asking after the calendar. The creator, 2026-09-20: his daughter sang in the kitchen and his spoken "tell me a story from the Arabian Nights book" a moment later was filed as the two of them talking; typed, it worked. Deliberately not "any imperative" -- rule 11 already records what widening this costs -- and rule 11 outranks it, so "read Aran a story" stays an aside.
13. A household name is given its own spelling on the final transcript before anything else reads it (`backchannel.spell_household_names`, called in `session._transcribed`): the screen, the memory, the vocative rule and the model all then see the same person. Whisper wrote the creator's daughter Ira as "Aira" and he corrected Sim out loud, "Ira and not Aira" (2026-09-20). Narrow, because rewriting what somebody said is the rudest thing in that module: one letter from a name in the speaker book, added or dropped only for a three-letter name (a substitution there turns Ida into Ira), and never an ordinary English word (`_REAL_WORDS`).
14. A voice profile that disagrees with itself is reported, by `voice people` and by the subsystem's `health()` (`speakers.muddled`, `MUDDLED_BELOW` 0.65). `coherence()` existed and its own docstring said `voice people` used it to "say so out loud instead of leaving somebody to wonder why Sim has gone deaf"; nothing called it at all until 2026-09-20. It is the one number that explains both failure directions: measured that day, Iris 0.85 over nine takes, Ira 0.78 over seven, the creator's own 0.54 over twelve -- and a weak profile is why his `speaker_threshold` is 0.30 against the 0.50 default, at which a television documentary matched him at 0.37 and was answered as conversation. Fewer than three takes says nothing and is not reported.
15. The echo check asks `echoes_recent` over `recent_said` whenever Sim is mid-reply (`pipeline.speaking`) as well as inside the exchange window. The two halves of a reply are written down at different moments -- `recent_said` and `speaking` BEFORE the audio goes out, `_sim_spoke_at` and `last_said` only after it finishes -- so an echo arriving mid-sentence found the ring already holding the reply and `_sim_spoke_at` still on the PREVIOUS turn, took the `is_echo(text, last_said)` branch, and was compared against the reply before this one. Live 2026-09-21: "Doing well, Saeed -- quiet afternoon, all systems steady. How are you?" came back as "Doing well, Saeed Khwai." and was recorded as the creator's turn, transcribed before the spoken line had even printed. A quiet rule caught it, which is luck: an echo worded differently is answered.
16. A reply overtaken by newer turns is still spoken, late, for up to `turns.OWED_KEPT` (4) of them (`TurnManager._superseded`, a LIST). It was a single slot, and every final transcript takes it whatever the quiet rules decide afterwards -- so a room with two children in it fills it in seconds. Live 2026-09-21: the twins talked over a 9.1 s failover to Gemini, "You're not sim." was answered "I really am Sim! Who else would be right here chatting with you?", and the creator heard NOTHING -- two utterances had arrived, the second overwrote the first, and the answer matched neither `_asked_turn` nor `_superseded`. The comment above that field already recorded the same shape from 2026-09-13 ("a 15 s answer was dropped because the creator spoke meanwhile ... and Sim was blamed for silence"); one slot survives one interruption. Answering the newest turn still clears the rest, because by then they are stale.
17. `refine` will not admit a take that leaves the profile disagreeing with ITSELF: once a person has three or more takes, a candidate is refused when it would drop `coherence` below `MUDDLED_BELOW` and below where it already is. `REFINE_AGREE` compares a take to the profile as it IS, so as the profile widens a worse take clears the same bar and widens it further -- the ratchet its own comment warns about, which a flat bar cannot stop. Measured on the creator's book hours after he re-enrolled on 2026-09-21: three enrolment takes at 0.80, nine learnt on top agreeing at 0.51-0.76 (all over the 0.5 bar) and scattered enough to disagree with each other, profile back to 0.59. Replaying those nine through the guard keeps two and holds 0.76. Under three takes the guard does not apply -- coherence is then a single pair, and "never learn below 0.65" is the 2026-09-15 deafness the other way round. `voice tidy <name>` repairs a profile already damaged, never touching the three enrolment takes.
18. A kept turn's sidecar names WHO spoke (`session._name_the_kept_turn`), added once the speaker book has answered rather than when the file is written. `_keep_turn` runs on the final transcript, which is before identification, so it merged a `_scored` entry that did not exist yet: 745 kept turns on the creator's machine, 142 MB of his family's voices, and not one named anybody (2026-09-21). The sidecar carries `speaker_named`, `speaker_score`, `speaker_probable` and the runner-up, so a future relearn can pick only the takes Sim was sure about -- a lean is how a profile collects two people. Best effort: a sidecar that cannot be updated is a worse record, not a lost one. Only with `[voice] keep_audio` on, which is off by default.
19. `voice relearn <name>` rebuilds a profile from recordings already kept, so a repair costs nobody a recording session (`SpeakerBook.relearn`, `service._relearn_from_kept`, newest `RELEARN_LOOKS_AT` = 300 turns, embedded in a thread). Its bars are deliberately HIGHER than `refine`'s, because it admits many takes at once with nobody in the room to object: measured against the three ENROLMENT takes rather than the whole profile, `threshold + margin` rather than the bare threshold (a television scored 0.37 on the creator's book at a 0.30 threshold), clear of every other enrolled person by `REFINE_CLEAR` so a take that might be either twin is nobody's lesson, and each addition must still leave the profile agreeing with itself. Adding nothing is a real answer and says so -- it is the right one when the kept recordings are of somebody else. A FULL profile (`MAX_TAKES`) is refilled, not appended to: the learnt takes already there and the recordings that qualified compete on agreement with the enrolment, best first, so a better recording replaces a weaker take; the result is saved only if the profile agrees with itself at least as well as before. `relearn` returns `(added, dropped, considered, before, after)`. The first version stopped at the cap before looking at one recording and told the creator "nothing in 0 kept recording(s)" (live, 2026-09-21); replayed on his book, 0.66 -> 0.80.
20. `voice calibrate` records a set once and never asks for a line it already has (`calibration.py`, `session._calibration_take`). While a run is set, every final transcript is a take of the line on screen, taken where an enrolment take is taken and never asked of the model; the repeat detector and the backchannel stand aside, and the recogniser is given the line's language (a Farsi line auto-detected as Arabic would be thrown away as "not a language of this house"). A take is refused AT ONCE, with the reason and the same line shown again, when it is too short or cut off, too quiet, clipped, on too noisy a floor, scores under the book's threshold against the person's enrolled profile, or is a gross misread (WER over 0.5 English, 0.75 Farsi -- looser there because the set exists to MEASURE the recogniser, not to be filtered by it). After a misread the person may say "keep it" (their words become the reference) or "that was right" (the script stands, `misread_overridden`); "skip" leaves a line for another day, "stop calibrating" pauses. Resume reads the manifest: a line counts as done only if its row was read from the same text the script has today. Silent by default so Sim's own voice is never in a take; `aloud` reads each line and refuses a take that began before Sim finished. `voice relearn <name>` embeds these takes FIRST and uses the kept turns only when there are none or none would help (same bars, `SpeakerBook.relearn`). `prune_kept_audio` is non-recursive and returns at once in any folder holding a `manifest.jsonl`, so the set survives even with `calibration_dir` inside `audio_dir`.
12. Anything Sim says on its own initiative waits for the floor: `session.say` holds while the turn manager is in `user_speaking` or `thinking`, up to `hold_unprompted_max_s` (8 s), then speaks anyway and logs `voice.spoke_over_the_floor`. A reply to a spoken turn does not come through here -- it has `HOLD_REPLY` and `hold_reply_max_s` (1.5 s), because somebody is waiting for that one. Without this a check-in, a camera or a reminder took the speech lock mid-sentence (stage 6 item 6's HOLD, added 2026-09-20).
13. No library's progress bar reaches the creator's screen. An engine subprocess is started with the hub and tqdm bars off, because its stdout is the JSON-lines protocol itself and its stderr is the tail an engine's failure is reported with; an in-process recogniser sets the same flags before its import. Reported live 2026-09-20 (`Loading weights: 100%|...| 103/103`) and already forbidden by `evals/house/script.py::tui_is_sane`.
14. With the defaults, an unknown voice is never asked for its name unprompted (`introduce_after_turns = 0`), and a voice Sim cannot place is not answered unless it says Sim's name or answers what Sim just asked (`unplaced_needs_name`, `config.py:172-178`).

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract voice`.

- `tests/simorgh/voice/test_voice.py` -- the Service on fakes over the bus: status when off, a spoken turn becomes a percept and its answer is spoken, `speak_replies` only for typed turns, probes reach `capabilities`.
- `tests/simorgh/voice/test_session.py` -- the live `VoiceSession` end to end: consecutive turns, barge-in, stale replies dropped, self-echo ignored, the superseded quiet turn (V1).
- `tests/simorgh/voice/test_turns.py` -- `TurnManager` transitions from events alone, end of turn, barge-in, monotonic turn ids.
- `tests/simorgh/voice/test_speaker_session.py` -- the speaker name rides on the transcript and into the ask.
- `tests/simorgh/voice/test_spoken_restart.py` -- restart is published as `ui.command.request`, only for a known voice.
- `tests/simorgh/voice/test_speech_lane.py` -- one voice at a time through the speech lock.
- `tests/simorgh/voice/test_settings.py` -- `voice set` accepts only safe keys and checked values and persists them.
- `tests/simorgh/voice/test_kept_audio_retention.py` -- kept recordings are pruned by age and size (V11).
- `tests/simorgh/voice/test_calibration.py`, `test_calibration_session.py` -- `voice calibrate`: WER normalisation (Farsi too), the level checks, accept / refuse-and-re-ask / keep / skip / stop / resume, the manifest round trip through `load()`, retention never reaching the set, relearn preferring it, the measurement tool on the fake engine.
- `tests/simorgh/voice/test_an_engine_starts_clean.py` -- the environment an engine subprocess is started with: the debug allocators dropped, what it still needs, and no progress bar (V13).

## Known issues (2026-09-18 evaluation)

- V1: a superseded quiet turn dropped the newer turn's answer. Fixed 2026-09-18 (commit 1f68f37).
- V3: four session models and no identity contract; only Voice fills `speaker` on the percept. Open (Interface side; stage 4 item 3, stage 6 item 4).
- V7: `VoiceSession` reaches into the legacy `Pipeline` ~50 times; the NLMS echo canceller is built only on `Pipeline`'s path, so `aec` is dead in the live loop; barge-in is off in the live config. Open (stage 0 item 28).
- V8: `_last_speech_s`, `_last_pcm`, `_last_skip` were session singletons read across awaits. Fixed 2026-09-19 (`68e5ea4`): a per-turn facts dict keyed by turn id; `test_session.py::PerTurnFactsBelongToTheirTurn`.
- V10: the language a turn was heard in is recorded on the turn and `voice:turns` but absent from the percept contract. Open.
- V11: kept family audio had no retention (6.4 GB). Fixed 2026-09-18 (commit eb207dc).
- B15: `getattr(config, ...)` with fallbacks at `session.py` (e.g. `overheard_dir`). Open (stage 0 item 26).
- Closed 2026-09-22: `voice calibrate` has its own `calibrate` action on `voice.control.request` (it first travelled as `enroll` + key=calibrate).
- P6: no regression number on voice latency is compared run to run, although `voice:turns` carries per-turn metrics. Open (stage 1, stage 4 evals).

## Planned changes (roadmap)

- Stage 0 item 28 (rest): the echo canceller wired into `VoiceSession` or deleted (V7). Item 26's ratchet: replace `getattr(config, ...)` reads with attribute reads when touching a file.
- Stage 1: trace ids per spoken turn; spans around STT, speaker id, TTS synthesis and playback.
- Stage 3 (streaming): speak sentence by sentence from `session.delta` into `StreamingSynthesiser`; a spoken filler on slow tools; streaming STT (`stt/sherpa_stream.py`) primary with whisper rescoring; per-stage latency budgets with breach spans.
- Stage 4: one persistent session per speaker instead of a uuid per ask.
- Stage 5: speculative recall issued on the STT partial.
- Stage 6: the People model (`contracts/people.py`) replaces the speaker book's identity role; an `initiative/` module absorbs backchannel greetings and announcements.
- Stage 9: engines out of process only if stage-3 spans show an engine stalling the loop.

## Working on this module

Lock it first (`python tools/modlock.py claim voice --by <you> --task "..."`), commit the lock, edit only `simorgh/voice/`, `tests/simorgh/voice/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py voice` before committing; commit subject `voice: <what changed>`.

- Traces and spans (stage 1 items 2 and 4, 2026-09-19): a spoken turn's trace id is minted at the ask (`TurnClock.trace_id`) and carried on its `percept.text.received`, so the turn is one trace through Orchestration and Cognition. When the turn is spoken, its stages are recorded as timed spans in that trace through `Pipeline.telemetry` (the Context's store): `voice.stt`, `voice.think`, `voice.first_audio`, `voice.playback` (monotonic times converted to wall time). A failure to record never affects the turn.

- Streamed replies (stage 3 item 4, 2026-09-19): with `[voice] stream_replies = true` (the default since 2026-09-19, at the creator's request), Voice consumes `session.delta` for the turn it asked (`Pipeline.delta_sinks`) through a `SentenceStream` (`voice/streamreply.py`): each complete sentence is queued for the synthesiser at once (`TtsRequest.live`), the spoken cap and the more-on-screen note are kept, a leading tone tag is taken off, a `reset` keeps what was said and collects the answer afresh, and `finish(final)` says what was not streamed. The first sentence plays while the model writes the rest; the "still thinking" filler is cancelled when it starts. `StreamingSynthesiser` reads live pieces without holding them and ends a live reply with a 20 ms silent final chunk.

- Stage budgets (stage 3 item 8, 2026-09-19): `STAGE_BUDGETS_S` stt 2.0 s (final transcript after speech ends) and response 2.5 s (first audio after speech ends). Each breach is counted per day in `SessionStats.breaches` (today and yesterday kept), recorded as a `voice.budget_breach` telemetry event in the turn's trace, and shown by `voice status` (payload `breaches`). First token is not budgeted separately yet.
- `voice calibrate apply [name]` (2026-09-22): `SpeakerBook.rebuild` replaces the person's takes with the 12 most central calibration takes (median cosine to the rest), each language in proportion, the three most central of the largest first as the enrolment; refused, unchanged, if the new profile would agree with itself below `MUDDLED_BELOW` or come within the book's threshold of anyone else. The old profile is kept as `<name>.json.before-<stamp>`. Found live: the creator's profile agreed with itself at 0.83 but with his own 67 calibration takes at 0.41 (a consistent voice from other conditions), so his turns scored ~0.4 and `relearn`, which judges against the enrolment three, could never repair it; rebuilt, held-out takes scored 0.81.

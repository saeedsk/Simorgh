# voice -- contract

One-line status: layer 5 · 11,279 lines · 45 test files · lock: `voice` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/voice/__init__.py` | TODO |
| `simorgh/voice/aec.py` | TODO |
| `simorgh/voice/api.py` | TODO |
| `simorgh/voice/audio.py` | TODO |
| `simorgh/voice/backchannel.py` | TODO |
| `simorgh/voice/bench.py` | TODO |
| `simorgh/voice/commands.py` | TODO |
| `simorgh/voice/config.py` | TODO |
| `simorgh/voice/delivery.py` | TODO |
| `simorgh/voice/diarize.py` | TODO |
| `simorgh/voice/fakes.py` | TODO |
| `simorgh/voice/health.py` | TODO |
| `simorgh/voice/introduce.py` | TODO |
| `simorgh/voice/lang.py` | TODO |
| `simorgh/voice/pipeline.py` | TODO |
| `simorgh/voice/planner.py` | TODO |
| `simorgh/voice/playback.py` | TODO |
| `simorgh/voice/pronounce.py` | TODO |
| `simorgh/voice/repeat.py` | TODO |
| `simorgh/voice/resample.py` | TODO |
| `simorgh/voice/service.py` | TODO |
| `simorgh/voice/session.py` | TODO |
| `simorgh/voice/settings.py` | TODO |
| `simorgh/voice/speakers.py` | TODO |
| `simorgh/voice/stt/__init__.py` | TODO |
| `simorgh/voice/stt/faster_whisper.py` | TODO |
| `simorgh/voice/stt/sherpa_stream.py` | TODO |
| `simorgh/voice/stt/streaming.py` | TODO |
| `simorgh/voice/stt/whisper_cli.py` | TODO |
| `simorgh/voice/stt/whisper_server.py` | TODO |
| `simorgh/voice/tts/__init__.py` | TODO |
| `simorgh/voice/tts/chatterbox.py` | TODO |
| `simorgh/voice/tts/kokoro.py` | TODO |
| `simorgh/voice/tts/lanes.py` | TODO |
| `simorgh/voice/tts/miso.py` | TODO |
| `simorgh/voice/tts/piper.py` | TODO |
| `simorgh/voice/tts/say.py` | TODO |
| `simorgh/voice/tts/servers/__init__.py` | TODO |
| `simorgh/voice/tts/servers/chatterbox_server.py` | TODO |
| `simorgh/voice/tts/servers/miso_server.py` | TODO |
| `simorgh/voice/tts/servers/styletts2_server.py` | TODO |
| `simorgh/voice/tts/streaming.py` | TODO |
| `simorgh/voice/tts/styletts2.py` | TODO |
| `simorgh/voice/tts/subproc.py` | TODO |
| `simorgh/voice/turns.py` | TODO |
| `simorgh/voice/vad.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `persona.state.changed` | `messages/persona.py::PersonaStateChanged` | simorgh/voice/service.py | TODO |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/voice/pipeline.py | TODO |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/voice/pipeline.py | TODO |
| `turn.completed` | `messages/task.py::TurnCompleted` | simorgh/voice/pipeline.py, simorgh/voice/service.py | TODO |
| `ui.tv.state` | `messages/ui.py::TvState` | simorgh/voice/pipeline.py | TODO |
| `voice.bench.reply` | `messages/voice.py::VoiceBenchReply` | simorgh/voice/service.py | TODO |
| `voice.bench.request` | `messages/voice.py::VoiceBenchRequest` | simorgh/voice/service.py | TODO |
| `voice.control.request` | `messages/voice.py::VoiceControlRequest` | simorgh/voice/service.py | TODO |
| `voice.devices.reply` | `messages/voice.py::VoiceDevicesReply` | simorgh/voice/service.py | TODO |
| `voice.devices.request` | `messages/voice.py::VoiceDevicesRequest` | simorgh/voice/service.py | TODO |
| `voice.listen.reply` | `messages/voice.py::VoiceListenReply` | simorgh/voice/service.py | TODO |
| `voice.listen.request` | `messages/voice.py::VoiceListenRequest` | simorgh/voice/service.py | TODO |
| `voice.models.request` | `messages/voice.py::VoiceModelsRequest` | simorgh/voice/service.py | TODO |
| `voice.speak.reply` | `messages/voice.py::VoiceSpeakReply` | simorgh/voice/service.py | TODO |
| `voice.speak.request` | `messages/voice.py::VoiceSpeakRequest` | simorgh/voice/service.py | TODO |
| `voice.status.reply` | `messages/voice.py::VoiceStatusReply` | simorgh/voice/service.py | TODO |
| `voice.status.request` | `messages/voice.py::VoiceStatusRequest` | simorgh/voice/service.py | TODO |
| `voice.voices.reply` | `messages/voice.py::VoiceVoicesReply` | simorgh/voice/service.py | TODO |
| `voice.voices.request` | `messages/voice.py::VoiceVoicesRequest` | simorgh/voice/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | simorgh/voice/pipeline.py | TODO |
| `task.cancel` | `messages/task.py::TaskCancel` | simorgh/voice/session.py | TODO |
| `ui.command.request` | `messages/ui.py::UiCommandRequest` | simorgh/voice/session.py | TODO |
| `ui.notice` | `messages/ui.py::UiNotice` | simorgh/voice/session.py | TODO |
| `ui.tv.speech` | `messages/ui.py::TvSpeech` | simorgh/voice/session.py | TODO |
| `voice.bench.reply` | `messages/voice.py::VoiceBenchReply` | simorgh/voice/service.py | TODO |
| `voice.control.reply` | `messages/voice.py::VoiceControlReply` | simorgh/voice/service.py | TODO |
| `voice.control.request` | `messages/voice.py::VoiceControlRequest` | simorgh/voice/session.py | TODO |
| `voice.devices.reply` | `messages/voice.py::VoiceDevicesReply` | simorgh/voice/service.py | TODO |
| `voice.listen.reply` | `messages/voice.py::VoiceListenReply` | simorgh/voice/service.py | TODO |
| `voice.listening` | `messages/voice.py::VoiceListening` | simorgh/voice/pipeline.py, simorgh/voice/session.py | TODO |
| `voice.models.reply` | `messages/voice.py::VoiceModelsReply` | simorgh/voice/service.py | TODO |
| `voice.speak.reply` | `messages/voice.py::VoiceSpeakReply` | simorgh/voice/service.py | TODO |
| `voice.spoken` | `messages/voice.py::VoiceSpoken` | simorgh/voice/pipeline.py, simorgh/voice/session.py | TODO |
| `voice.status.reply` | `messages/voice.py::VoiceStatusReply` | simorgh/voice/service.py | TODO |
| `voice.transcript` | `messages/voice.py::VoiceTranscript` | simorgh/voice/pipeline.py, simorgh/voice/session.py | TODO |
| `voice.voices.reply` | `messages/voice.py::VoiceVoicesReply` | simorgh/voice/service.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `faster_whisper:{config.stt_model}` | simorgh/voice/stt/faster_whisper.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `voice:turns` | simorgh/voice/pipeline.py | simorgh/ledger/compaction.py | see ledger/compaction.py DEFAULT_RETENTION |
| `whisper_cli:{tag}` | simorgh/voice/stt/whisper_cli.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `whisper_server:{tag}` | simorgh/voice/stt/whisper_server.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `you:` | simorgh/voice/pipeline.py | simorgh/orchestration/scaffolds.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[voice]` in simorgh.toml; dataclass in `simorgh/voice/config.py`.

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
| `tts_speed` | `1.1` | yes |
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
| `aec` | `True` | yes |
| `aec_taps` | `1024` | yes |
| `aec_mu` | `0.3` | yes |
| `aec_residual_threshold` | `0.02` | yes |
| `volume` | `1.0` | yes |
| `output` | `'laptop'` | yes |
| `tv_audio_lag_s` | `2.5` | yes |
| `auto_listen` | `True` | yes |
| `vad_sensitivity` | `'high'` | yes |
| `min_speech_ms` | `250` | yes |
| `max_turn_ms` | `30000` | yes |
| `hold_reply_max_s` | `1.5` | yes |
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
| `keep_audio` | `False` | yes |
| `audio_dir` | `'workspace/voice/audio'` | yes |
| `keep_transcripts` | `True` | yes |
| `device` | `'laptop'` | yes |
| `model_dir` | `'workspace/voice/models'` | yes |
| `microphone` | `'auto'` | yes |
| `speaker` | `'auto'` | yes |
| `fake_transcript` | `'hello sim'` | yes |
| `overheard_dir` | `'workspace/voice/overheard'` | yes |
| `overheard_hours` | `48.0` | NO (declared, never read) |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract voice`.

- `tests/simorgh/voice/test_a_pause_in_a_conversation_is_not_quiet.py` -- TODO: what it pins
- `tests/simorgh/voice/test_a_setting_that_rebuilds_the_engines.py` -- TODO: what it pins
- `tests/simorgh/voice/test_a_slow_engine_is_waited_for.py` -- TODO: what it pins
- `tests/simorgh/voice/test_a_voice_is_enrolled_once.py` -- TODO: what it pins
- `tests/simorgh/voice/test_aec.py` -- TODO: what it pins
- `tests/simorgh/voice/test_an_engine_is_asked_about_itself.py` -- TODO: what it pins
- `tests/simorgh/voice/test_an_engine_may_speak_before_it_hands_over.py` -- TODO: what it pins
- `tests/simorgh/voice/test_an_engine_starts_clean.py` -- TODO: what it pins
- `tests/simorgh/voice/test_backchannel.py` -- TODO: what it pins
- `tests/simorgh/voice/test_barge_in.py` -- TODO: what it pins
- `tests/simorgh/voice/test_commands.py` -- TODO: what it pins
- `tests/simorgh/voice/test_delivery.py` -- TODO: what it pins
- `tests/simorgh/voice/test_diarize.py` -- TODO: what it pins
- `tests/simorgh/voice/test_echo_ring.py` -- TODO: what it pins
- `tests/simorgh/voice/test_farsi.py` -- TODO: what it pins
- `tests/simorgh/voice/test_health.py` -- TODO: what it pins
- `tests/simorgh/voice/test_introduce.py` -- TODO: what it pins
- `tests/simorgh/voice/test_lanes.py` -- TODO: what it pins
- `tests/simorgh/voice/test_leaked_marker.py` -- TODO: what it pins
- `tests/simorgh/voice/test_misheard_name.py` -- TODO: what it pins
- `tests/simorgh/voice/test_planner.py` -- TODO: what it pins
- `tests/simorgh/voice/test_playback_stall.py` -- TODO: what it pins
- `tests/simorgh/voice/test_pronounce.py` -- TODO: what it pins
- `tests/simorgh/voice/test_refine_bar.py` -- TODO: what it pins
- `tests/simorgh/voice/test_repeat.py` -- TODO: what it pins
- `tests/simorgh/voice/test_session.py` -- TODO: what it pins
- `tests/simorgh/voice/test_settings.py` -- TODO: what it pins
- `tests/simorgh/voice/test_settings_overview.py` -- TODO: what it pins
- `tests/simorgh/voice/test_sherpa_stream.py` -- TODO: what it pins
- `tests/simorgh/voice/test_speakable_paths.py` -- TODO: what it pins
- `tests/simorgh/voice/test_speaker_session.py` -- TODO: what it pins
- `tests/simorgh/voice/test_speakers.py` -- TODO: what it pins
- `tests/simorgh/voice/test_speech_lane.py` -- TODO: what it pins
- `tests/simorgh/voice/test_spoken_restart.py` -- TODO: what it pins
- `tests/simorgh/voice/test_streaming_tts.py` -- TODO: what it pins
- `tests/simorgh/voice/test_styletts2_is_expressive_and_quick.py` -- TODO: what it pins
- `tests/simorgh/voice/test_subproc_tts.py` -- TODO: what it pins
- `tests/simorgh/voice/test_the_engine_choice_survives_a_restart.py` -- TODO: what it pins
- `tests/simorgh/voice/test_the_tokenizer_is_not_gated.py` -- TODO: what it pins
- `tests/simorgh/voice/test_turns.py` -- TODO: what it pins
- `tests/simorgh/voice/test_two_voices_in_one_turn.py` -- TODO: what it pins
- `tests/simorgh/voice/test_unplaced_conversation.py` -- TODO: what it pins
- `tests/simorgh/voice/test_voice.py` -- TODO: what it pins
- `tests/simorgh/voice/test_whisper_models.py` -- TODO: what it pins
- `tests/simorgh/voice/test_whisper_server.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim voice --by <you> --task "..."`), commit the lock, edit only `simorgh/voice/`, `tests/simorgh/voice/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py voice` before committing; commit subject `voice: <what changed>`.

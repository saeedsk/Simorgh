# Stage 3 -- Streaming end to end

Status: not started · Depends on: stage 2 items 3-5 · Estimated: 2 weeks · Modules touched: cognition, orchestration, interface, voice, contracts

## Outcome

The model's reply streams: deltas reach the TUI as they arrive, and Voice speaks the first sentence while the rest is still being generated. Streaming STT is the primary lane so a turn is transcribed as it is spoken. A fast-lane acknowledgement covers a slow tool call. Per-stage budgets (STT final, first token, first audio) come from the envelope deadline and breaches are counted. First audio is near the first sentence instead of after the whole reply.

## Why

Evaluation section 9.4 (full response 4 to 17 s; STT 1.8 to 6.8 s the largest stage; `StreamingSynthesiser` and `StreamingPlayer` built and never fed; no provider streams). This is the change the family notices most.

## Before you start

Record first-audio and full-response p50/p95 over 50 real turns from `voice:turns` (or the 50 recorded turns in `workspace/voice/samples` through `tools/voice_live_trial.py`). Read `cognition/providers/together.py` (no streaming), `voice/tts/` (`synthesise_stream`, `StreamingSynthesiser`, `StreamingPlayer`), `voice/stt/sherpa_stream.py`, `voice/session.py::_ask_and_speak`, `interface/render.py`.

## Action items

1. **`Provider.stream()`.** *Lock `cognition`.* `AsyncIterator[Delta]` with `Delta = text | tool_use_start | tool_use_input_json | stop`; `complete()` derived from `stream()`; Together (SSE), Anthropic, Gemini, Ollama adapters; tool-call input buffered until `stop`. Acceptance: fixture tests per adapter; a malformed partial JSON tool call yields an error delta, not an exception.
2. **`session.delta` on the bus, bus-only.** *Lock `contracts`, `orchestration`.* A new topic `session.delta{session_id, seq, text}` published as deltas arrive, excluded from the ledger and from tracing (sampling 0); the completed turn is what reaches the ledger; a cancelled stream records a truncated turn honestly. Acceptance: topic has both sides (interface, voice subscribe); the both-sides test's allow-list shrinks.
3. **The TUI renders deltas.** *Lock `interface`.* `render.py` appends text as it arrives in the answer line; the HTTP `/api/chat` feed streams too. Acceptance: `test_tui.py` case with three deltas renders one growing line.
4. **Voice speaks sentence by sentence.** *Lock `voice`.* A sentence chunker consumes `session.delta` into `StreamingSynthesiser`; sentence n+1 is synthesised while n plays; barge-in cancels the stream; the echo tracker is fed each chunk as it plays. Acceptance: `tests/simorgh/voice/test_streaming_reply.py` with a fake synthesiser: first audio requested after the first sentence delta, not after `stop`.
5. **A spoken filler on a slow tool.** *Lock `voice`, `orchestration`.* On `tool_use_start` for a tool whose recent p95 (from telemetry) exceeds 2 s, Voice speaks a short filler from a fixed list ("let me look"), once per turn. Acceptance: test with a slow fake tool.
6. **Streaming STT primary.** *Lock `voice`.* `stt/sherpa_stream.py` partials feed the end-of-turn decision; whisper large-v3-turbo rescoring runs on the final segment only when the streaming confidence is low. Acceptance: on the 50 recorded turns, STT final latency p50 drops; WER not worse (record both).
7. **A fast-lane acknowledgement.** *Lock `orchestration`, `cognition`.* When the offered tool set predicts a slow turn (a `RESEARCH`-class profile, or a `patch` task), a cheap-tier one-liner is streamed as a bridge before the real reply; never as the answer. Acceptance: test that the bridge is not recorded as the turn's text.
8. **Per-stage budgets.** *Lock `voice`, `telemetry`.* SLO table `stage -> budget` (STT final 2 s, first token 1.5 s, first audio 2.5 s); a breach is a span event counted per day; `voice status` shows yesterday's breaches. Acceptance: a test that a slow fake STT produces one breach span.
9. **Findings entry** with first audio and full response p50/p95 before and after on the same 50 turns; WER; breaches per day.

## Measurements after

| Number | Before | Target |
|---|---|---|
| First audio, tool-free turn (p50 / p95) | 0.5-2.3 s after the reply, i.e. 4-17 s from end of speech | ≤ 1.2 s / ≤ 2.5 s from end of speech |
| STT final latency p50 | 1.8-6.8 s | under 1.5 s |
| WER on the recorded set | recorded | not worse |

## Risks and mitigations

- Echo and barge-in regress when audio starts while the mic is open: gate with the voice bench and the recorded set; keep the non-streaming path as fallback (`[voice] stream_replies = false`).
- Provider quirks in streamed tool calls: buffer until `stop`; fixture tests per provider.

## Definition of done

- [ ] Items 1-8 with tests; module tiers green for cognition, orchestration, interface, voice.
- [ ] Findings entry with the table.
- [ ] CONTRACT.md updated for the new topic and config keys.

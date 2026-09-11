"""Talking to Sim: the voice subsystem (docs/plans/voice-design.md).

A spoken turn becomes `percept.text.received{channel: "voice"}` and rides
the same Orchestration/Cognition path as typed text; the reply is what
gets spoken. One brain, one Guardian, one ledger. This package owns only
the audio: capture, endpointing, recognition, synthesis, playback.
"""

# 2026-09-27 — a live evening: Farsi, the satellite, the phone, the lights

Watched from behind: the creator talked to Sim (satellite, laptop, iPhone
over Tailscale) and every bug found was fixed and committed while he did.
About forty commits, `d290e785` .. `f72f4634`. What was learnt, by area.

## Farsi — four layers, and which one was actually wrong

| layer | what went wrong live | what fixed it |
|---|---|---|
| hearing | turbo labelled Farsi as English/Czech/Indonesian/Icelandic and wrote it in Latin letters | large-v3 for every turn of a Farsi conversation (`conversing_in`); a foreign label retried in both house languages, **the one whisper is surest of wins** (mean `avg_logprob`), not the first with words (`c9272b39`) |
| the language label | "Sim, you're not audible" labelled Icelandic → answered in Icelandic | only a house language is passed on as `heard_language` (`58da0508`) |
| the brain | GLM-5.3-Flash called clear Farsi "garbled", invented Hafez twice, said «رفت سر کارش» and started nothing | `[orchestration] farsi_strong`: a Farsi chat turn asks the strong tier (GLM-5.3) (`4c37281e`); the prompt says read a transcript generously and never blame the speaker (`750864bb`); the `started` stop-hook rule (`4a74256f`) |
| the voice (Pocket) | leaked its reference clip's words on short lines; babble at the end of long answers; a male/female switch mid-answer; ترک said ta-ra-k | sentence/clause chunking (`9d7841ac`, `b64e5ac4`); no short Farsi asides; asides take the final transcript's language (`2fe362e1`); vowel marks kept through the normaliser (`ace79260`) and written by the model only where they change the word (`42e02004`); a word lexicon, سعید=s/id (`782d7839`) |

Measured, so nobody re-derives it:

- Pocket's G2P (Homo-GE2PE) resolves homographs from sentence context well
  (مرد → mard/mord, شعر, ملک, ترک in «اگر آن ترک شیرازی»). It fails in
  thin or poetic context («یکی ترک می‌گه» → t/r/k). Its normaliser dropped
  every diacritic; with fatha/damma/kasra/shadda kept, «تُرک» → tork and
  «عکسِ رخِ» gets its ezafe.
- Short Farsi lines (1–3 words) make Pocket say its reference clip's own
  opening words about half the time. Full sentences are clean.
- A model asked to "add vowels" over-marks and mis-marks (دُل for دل). A
  wrong mark is read as written — worse than none.
- The fast chat model, not the voice or the recogniser, was the main cause
  of "awful Farsi" by the end of the evening.

Honest limit, told to the creator: open Persian speech tech is a fraction of
English's. Azure's Persian neural voices (Dilara/Farid) are the obvious
comparison if the local path is not enough; offered, not built.

## The satellite — three ways a board goes deaf or mute, and one it cannot fix

All three now self-heal by pressing the firmware's own **Restart** button
(the formatBCE package defines it; hidden in HA's UI, present on the API —
no reflash needed), at most once per 5 min:

1. `Queue full, URI dropped` — the media player stops taking audio; Sim,
   timing pieces by length, believed its replies played. STOP first; if the
   board answers `Queue full, command dropped`, restart (`1cbbf6d0`).
2. The board logs `wake_word_detected` and opens no run within 5 s — after a
   run it aborted mid-reply it stayed deaf 14 minutes (`f1bf65f8`).
3. A run of ≥5 s at peak 0 — the mic sending pure silence (`f72f4634`).

Not self-healable: the board dropping off the network entirely (22:48, after
the silent-mic run). Only a power-cycle fixes that.

The firmware lives in `tools/satellites/` (the repo copy is the newer one;
`~/esphome-sim` was the bring-up scratch folder).

## The phone

- Five paired phones, none with an owner, so every app request was a
  stranger's to Guardian. Pairing now takes "who's using this phone" (a
  household member, the terminal's `pair … for X` wins) and the device book
  re-reads its file when changed outside (`259dfe5b`). The creator's
  current phone was assigned after a restart.
- A turn from an owned phone says so in the prompt, so earlier refusals in
  the history don't make the model refuse ahead of Guardian (`d4a7f459`).
- Home Assistant's LAN address is nothing over Tailscale: Sim relays it on
  the Mac's tailnet address, port 8124, and `/api/house/assistant` hands a
  tailnet caller the relay (`c07990b0`).
- Orphaned `dns-sd -R Sim` adverts (one 3 days old, one for port 0 from a
  test run) — the advert now dies with Sim, and port 0 is never announced
  (`118d0195`).

## The lights — the Lutron flood

`home_blink` was built for "blink the family room at 1–5 Hz". The first
version sent switches as fast as Home Assistant accepted them; the Lutron
Caseta bridge queued a few hundred and kept playing them over its radio
after Sim, Home Assistant and the laptop's Wi-Fi were all off. Only
unplugging the bridge stopped it.

Now: each switch waits until the light shows the last one; a light that
stops keeping up ends the blink; 1 Hz / 120 s / 120 switches; `stop`
cancels; every command the real HA client sends to one entity is ≥0.5 s
after the last, from any tool (`42af63fb`). Lesson saved to memory:
**any repeated command to a bridged light must pace and confirm.**

## Left open

- A stored fact "Saeed requested Sim only speak Farsi" came from a misheard
  turn; it makes English turns get Farsi replies (and an English "aha"
  before them). The creator was told `forget all 30d only speak Farsi`.
- `speaker_threshold = 0.2` in the creator's config lets almost any voice
  pass as him; 0.45 suggested, his call.
- Farsi STT on large-v3 takes ~5 s for a 6 s turn at full precision; a
  quantised large-v3 was offered, not tried.
- Sim's own queued task `be9f0ca66c28` (a hazm "diacritisation" it cannot
  do) should be cancelled.

# Stage 1's after-numbers, taken on the live data dir (2026-09-20)

Stage 1 item 11 asked for a findings entry with the table filled in. Here
it is, with the two rows that are not what they look like called out
rather than rounded into a tick.

| Number | Before | Target | Measured 2026-09-20 |
|---|---|---|---|
| `trace:` streams | thousands | 0 | **0** |
| Ledger stream files after a day | 44k/day | under 500/day | **490** written on 2026-09-20; 2,581 on the 19th |
| `action:` streams per dashboard hour | ~200 | under 10 | not measurable as written |
| One spoken turn's spans (STT, think, first audio) | none | present, queryable | **present**: 98 / 98 / 97 spans, 104 distinct span names |
| Tool calls outside the action path | 6 sites | 0 | **0** |
| Idle CPU of the process | ~6.6% of a core | under 2% | **16-37%** while listening, on a loaded machine |

Method: `~/.simorgh/ledger` (1,954 stream files, 3,071 files in total) and
`~/.simorgh/telemetry.sqlite`, against the live Sim the creator had been
talking to an hour earlier.

## The 2,581 files on the 19th are not a regression

That was a day of trial runs and observer waves, each of which writes its
own task, action and verify streams. The 490 written today is the number
the target is about, and it is inside it. Worth keeping an eye on rather
than celebrating: `action:` alone is 775 of the 1,954 stream files, which
is one stream per action, and the item's worry was exactly that shape.

## Two rows that cannot be ticked

**`action:` streams per dashboard hour.** Measured after this document was
first written, and it is a 100x miss with a single cause: a WebRTC
keep-alive is modelled as a gated action, so a live Ring view spends 640
proposals an hour telling Guardian that a video is still playing. Full
numbers and the shape of the fix in
`2026-09-20-the-action-stream-flood.md`. The original note below stands for
why file-counting is not the measurement. There is no hour stamp on a
stream, only a file mtime, and the dashboard was not running. Counting
files answers a different question. Whoever picks this up should open the
dashboard for an hour and count what appears in that hour; until then the
row stays blank rather than being filled with a number that sounds like an
answer.

**Idle CPU.** The reading was taken while a paid scenario pack was running
(five processes, 570% of a core between them), so 16-37% is an upper bound
inflated by contention. It is also not "idle": Sim was listening, which
means VAD on every 30 ms frame plus the silero model, and listening is what
this machine is for.

So the honest statement is that **nobody has measured idle CPU on a quiet
machine since the target was written**, and the one reading taken is far
enough above 2% that it is worth a morning. Stage 1 item 10 stays open with
that note instead of a tick. The measurement to take: Sim booted, voice
ON, nothing else running, sampled over a minute; then again with voice
OFF, which separates "the cost of listening" from "the cost of existing".
Those are different bills and only one of them is a bug.

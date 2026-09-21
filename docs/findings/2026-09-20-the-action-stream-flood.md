# 962 gated actions in one hour, 640 of them a keep-alive (2026-09-20)

Stage 1 set a target of **under 10 `action:` streams per dashboard hour**,
against a before-figure of about 200. Measured today on the live decision
log, the busiest hour has **962**.

| hour | tool | decisions |
|---|---|---|
| 09-19 12:00 | `ring_live` | 640 |
| 09-19 12:00 | `cam_snapshot` | 249 |
| 09-19 13:00 | `ring_live` | 193 |
| 09-20 18:00 | `cam_snapshot` | 68 |

`action:` is 775 of the 1,954 stream files in the ledger. Every one of those
1,823 recorded decisions was also a proposal, an approval, a result and a
stream file of its own.

## The cause is one design choice, and it is half right

Ring's live view is WebRTC. `RingLiveTool` models it as three tool calls --
`offer`, `keepalive`, `close` -- and its docstring gives the reason: "Each
step is a tool call, so Guardian sees who is opening a live view of the
house." That reason is exactly right about `offer`. Opening a live camera
feed of somebody's home is precisely the kind of thing a gate exists for.

It is not right about the keep-alive. The dashboard sends one roughly every
five or six seconds for as long as the picture is up (the route's own rate
limit is 120 a minute), and each one is a fresh proposal that Guardian must
approve, because it is the same already-approved session continuing. Six
hundred identical approvals an hour is not oversight; it is the log
describing a video playing.

It costs three things. The decision log fills with noise -- reading it for
the stage 6 safety numbers this afternoon meant looking past 838 `ring_live`
rows to find the ten that mattered. The ledger grows a stream file per
keep-alive, on a machine already at 5% free disk. And the target that was
supposed to tell us whether the action path is healthy reads as a 100x miss
for a reason that has nothing to do with the action path's health.

## The shape of the fix

One approved `offer` should own its own keep-alive for the life of the
session, and `close` stays a gated action. Guardian still sees the thing
worth seeing -- who opened a live view of the house, and when it ended --
and the hour's decisions drop from 640 to 2.

What to be careful about: a keep-alive that fails must end the session
visibly rather than leaving a dead picture on the TV, so the internal loop
needs to publish its failure the way the tool call currently returns one. And
the session must not outlive the page: a browser that closes without saying
so should stop the loop on the first failed keep-alive rather than holding
Ring's session open indefinitely.

Not done here. Written down with the numbers so the next agent starts from
evidence rather than from a hunch, and because the stage 1 row it explains
would otherwise look like a failure of something else.

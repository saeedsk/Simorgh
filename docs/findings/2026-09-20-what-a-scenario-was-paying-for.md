# What a household scenario was paying for

2026-09-20. Stage 11 item 8 (`--profile`), and the first thing it found.

## The tool

The plan asked for `py-spy`. py-spy is the better profiler and it is
the wrong one here: attaching to another process on macOS needs root,
and the reason this item exists is that on 2026-09-20 a spinning main
thread **could not be stack-traced** (the SQLite ledger default, stage
9 item 5, still reverted). A sampler that runs inside the process
needs nobody's permission, and `sys._current_frames()` is stdlib.

`simorgh/evals/house/profile.py`: a background thread samples every
other thread every 10 ms, counts stacks, and writes collapsed-stack
format — what `flamegraph.pl` and speedscope both read, so the flame
graph is one pipe away with no dependency added.

`python -m simorgh.evals house --one <id> --profile [PATH]`.

It is a **wall-clock** sampler. A thread blocked in `recv` is sampled
as often as one spinning in a loop; what separates them is the frame,
not the count. Reading a percentage here as CPU share is wrong, and
the module says so where somebody will read it.

What it cannot see: native frames, and a thread holding the GIL inside
a C call. If a stack sits in the same C frame forever, that is the
answer it reports, and py-spy under `sudo` is the next step.

## What it found, on the first run

The hottest stack in `stage9/a-lamp-is-not-a-decision` — a scenario
with no memory in it, no voice in it, and two expectations about a
lamp:

```
futures/thread.py:_worker;futures/thread.py:run;
memory/embedders.py:warm;memory/embedders.py:_encode_local;
  ... sentence_transformer/model.py:__init__ ...
    auto/processing_auto.py:from_pretrained
```

Every household scenario was loading a real sentence-transformer. The
sandbox never set `[memory] embedder`, so it took the default `auto`,
which resolves to `local` on this machine.

It bought nothing. A scenario asks about a fact it planted itself, in
the words it planted it with — which is the one case the hashing
embedder is good at. Dense embeddings earn their keep on paraphrase
(`memory/config.py` records the measurement: hashing 0/10, hybrid
10/10 on paraphrased facts), and no scenario paraphrases.

## The change, and what it bought

`DEFAULT_CONFIG` in `house/sandbox.py` now sets
`"memory": {"embedder": "hashing"}`.

| | before | after |
|---|---|---|
| one scenario, foreground (2 runs each) | 8.30 s, 8.36 s | 1.71 s, 1.71 s |
| `house --fast`, the bless subset | 181.3 s | 154.6 s |

**4.9x on a single scenario.** The bless subset gains less because it
runs each scenario in its own child, so interpreter start and Kernel
boot dominate what is left — the remaining cost is boot, which is the
next thing to look at and was invisible under the model load.

Correctness held: `house --only stage5` (the two memory scenarios,
which are the ones that could have regressed) 4/4, and `house --fast`
10/10. A scenario that genuinely needs dense recall opts back in with
`[memory] embedder` in its own config.

## What this says about the suite

The scenario that found this has nothing to do with memory. The cost
was in the boot path, paid by every scenario equally, and invisible to
the timing table — which decomposes a *turn* into STT, think, tools,
TTS, and so cannot see a cost that lands before the first turn. Two
instruments, two questions, and this one only answers the second.

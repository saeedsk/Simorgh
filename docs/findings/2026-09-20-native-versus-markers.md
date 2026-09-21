# Native tool calls against markers, on the same twelve cases (2026-09-20)

Stage 2's only open item: "At least VOICE_CHAT and CHAT on native for the
live model with a recorded win", blocked since a trial round scored markers
6/7 against native 6/7. A tie is not a win, so nothing was flipped, and the
missing piece was a harness that could run identical cases with one setting
changed. `simorgh/evals` started scoring benchmarks through the sandbox
earlier the same day, so `--dialect markers|native` and `--cases N` were
added to it and pointed at the question.

Provider: Together, `zai-org/GLM-5.3-Flash`. Suite: BFCL parallel, the same
twelve cases each time.

| run | dialect | scored | wall |
|---|---|---|---|
| 1 | markers | 11/11 (one case fell to the floor and was skipped) | **2005 s** |
| 2 | markers | 11/12 | 99 s |
| 3 | native | 12/12 | 134 s |
| 4 | native | 11/12 | 190 s |

## There is no win here, and I claimed one an hour ago

On the first pair -- markers at 2005 s, native at 134 s -- I wrote that
native was "fifteen times faster at equal accuracy" and that this was the
win stage 2 had been waiting for. The repeat says otherwise: markers ran
the same twelve cases in **99 seconds**. The 2005 s run is an outlier, not
a property of the dialect, and the conclusion drawn from it was wrong.

What the four runs actually support: **23 of 24 scored cases correct either
way, and no separation in accuracy or in time.** Same tie as the trial
round, on four times the evidence.

This is the project's own rule about measuring before naming a cause,
broken by the person who keeps writing it down. One run each looked like
data because it had numbers in it.

## What the runs do show

**The variance is the finding.** One markers run took twenty times another
markers run on identical cases. That is the provider, not the dialect --
Together's latency under load, or a retry spell -- and it is worth knowing
because it is also what a household feels as "Sim is slow tonight". A
benchmark that reports a single wall time hides it; this table only shows
it because the run happened twice.

**Both dialects fail the same case.** `parallel_47` failed in run 2
(markers: answered with a JSON tool-call blob as prose, which the marker
parser does not accept) and in run 4 (native: "verification failed after
max revisions"). Same case, two different mechanisms, which is a
property of that case rather than of either dialect.

**Native dropped a case to the floor once** (run 1's markers did too). A
provider error mid-case falls through to the offline floor, whose answers
the runner honestly refuses to score. Once each is noise.

## The decision

**Nothing is flipped.** Stage 2's item stays open, with better evidence for
why: not "we have not measured it" but "it has now been measured four times
and there is no difference to act on".

What would change that, and is worth doing next:

- **More cases.** Twelve is 8% resolution; a real difference of a few
  percent cannot show up. The BFCL parallel set has 88.
- **Repeats inside one run.** `--repeats` already exists in the evals
  runner and gives a bootstrap interval; this harness does not use it yet.
- **A different provider.** GLM-5.3-Flash may simply be equally good at
  both. Gemini's native tool support is a different implementation and
  might separate where this one does not.
- **Measure what markers actually cost, in turns rather than seconds.**
  If markers need more model turns per case, that is a token bill and a
  latency risk even when the wall clock hides it behind provider variance.
  The spans are already recorded; nobody has counted them.

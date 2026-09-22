# Review: 'chat' tasks failing 4/6 recent outcomes (2026-09-22)

## Diagnosis

Two compounding issues, not a random pattern:

1. **Outcome misclassification for non-file tasks.** Verification treats
"write tool calls were made / a file changed" as the success criterion for
every task. For 'chat'-class tasks whose product is emitted function calls
in the correct JSON format (e.g. the sales-tax calls for Chicago $30.45 /
Sacramento $52.33 / Portland $11.23, the XYZ growth-ratio calls), correct
emission was marked failed anyway. The outcome estimator then rolls this
into competence, dragging the chat-task success rate down artificially.

2. **Self-review is filed where I cannot write.** The prior review notes
live under `simorgh/kernel/` (and `workspace/notes/`), and attempt 1 was
denied on `apply_source_patch` to `simorgh/kernel/` ("only the creator may
edit it directly"), wrote nothing, and verification then failed because no
change was written, tested, or committed. Self-review reports therefore
cannot be committed at all under the current layout, guaranteeing failed
verification on any "review your failures" task.

## Recommended fixes (creator action required for both)

- For #1: the verifier should branch on task kind -- for chat/research
  tasks the product is the tool-call transcript, and verification should
  check well-formed emission rather than file mutation.
- For #2: reserve a writable, committable path such as
  `docs/reviews/self/` for Simorgh-authored self-reviews.

## What was done this attempt

This document, in the writable `docs/` tree, is the review product; it is
committed so it survives. Kernel-protected files were left untouched per
Guardian.

"""Domain 4: security and privacy posture
(`docs/plans/domains/04-security-posture.md`).

**Advisory and read-only.** This inspects and reports. It never
attempts entry, never guesses a credential, and never touches a network
it does not own. Step 1 of the build order is the part that needs no
network at all and is the most useful anyway: Sim's own posture.

Guardian already audits the code Sim *writes*. Nothing audited what Sim
*is* -- whether its API is answering the whole network without a token,
whether auto-approve is on, whether the vault key is sitting in a
world-readable file, whether a password has been written into
`workspace/` by a task that meant well. Each of those is a fact about
this machine that can be checked in milliseconds, and every one of them
was invisible.

Findings are durable and deduplicated, so "this is still true" and
"this came back after being fixed" are different sentences. A finding
that reappears after being marked fixed is `regressed`, which is a
worse fact than one that was never fixed at all.
"""

from .api import Finding, Severity

__all__ = ["Finding", "Severity"]

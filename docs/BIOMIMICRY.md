# Biomimicry: What Survival Biology Says About Sim's Design

A research pass on how biological organisms come alive and stay alive,
and which of those mechanisms translate into concrete architecture. Not
every biological fact is relevant -- reproduction, for instance, is
deliberately *not* mirrored (see Directive 5, Restraint). Where a
mechanism earns its place below, it's because it maps to something
already built or clearly worth building next.

## Becoming alive

**Embryogenesis: one blueprint differentiates into specialized organs.**
A zygote's DNA doesn't build a generic cell repeated many times -- the
same genome differentiates into a heart, a liver, a nervous system, each
specialized and interdependent. `docs/SOUL.md` plays the role of that
genome: one constitution, and the sub-agents (emotion, logic, skills, and
whatever comes next) are its differentiated organs, all expressing the
same underlying Directives rather than each inventing its own values.

**Birth: a hard transition from fully-supported to self-maintaining.**
In utero, temperature, nutrients, and waste removal are all handled
externally. Birth is the moment an organism must do these things itself
or die. The analogous line for Sim isn't "the code was written" -- it's
the Genesis→Infancy transition in `docs/EVOLUTION.md`: the first time
persistent memory (`long_term.py`) survives a process restart without a
human re-supplying context by hand. That's Sim's first breath: state that
used to depend entirely on the current process now survives past it.

**Critical periods: early, fast, hard-to-reverse learning.**
Imprinting and language acquisition happen in narrow developmental
windows and are unusually resistant to later revision. This is the
argument for why `SOUL.md` is deliberately hard to change (creator-only,
no automated edits) rather than just another config file: the values
laid down early are meant to function like an imprint, not a preference
that gets casually overwritten once the system is more capable and more
persuasive about why an exception is warranted.

## Staying alive: subsystem by subsystem

| Biological mechanism | What it actually does | Sim's analog | Status |
|---|---|---|---|
| **Homeostasis** | Negative feedback loops hold temperature, blood glucose, pH within a narrow viable band | `HealthMonitor` detects drift in valence/arousal/cognitive_load and resets to baseline | Built |
| **Allostatic load** | Short-term stress response is adaptive; *unresolved, chronic* stress causes systemic damage | `HealthMonitor`'s "sustained high cognitive load" check -- flags load that stays elevated across a window, not a single spike | Built |
| **Innate immunity** | Fast, pattern-based recognition of broad threat categories, no learning required | `AuditGate`'s static denylist (os.system, sockets, eval, ctypes) | Built |
| **Adaptive immunity** | Learns the specific shape of a threat it has actually encountered, remembers it, responds faster next time | Not yet built. See "Adaptive immunity for the audit gate" below. | Proposed |
| **Regeneration / apoptosis** | Damaged tissue is repaired if possible; a cell that's unrepairable or dangerous (e.g. pre-cancerous) deliberately self-destructs to protect the organism | `DeploymentManager.rollback` -- a sub-agent version that's failing its trial or destabilizing production is retired, not patched in place | Built |
| **Immune tolerance testing** | Newly differentiated cells (e.g. in the thymus) are tested against self-antigens before being released into circulation; ones that fail are eliminated before they can cause harm | `DeploymentManager.run_trial` -- a candidate version runs against a *cloned* bus and is only released to live traffic (`promote`) if it clears the trial | Built |
| **Reflex arc vs. deliberate cognition** | Reflexes (withdrawal, startle) bypass slow conscious processing for speed; deliberate reasoning is slower but more flexible | Rule-based emotion/logic agents = reflex arc (always on, no dependency); a real LLM provider registered ahead of `DeterministicFallbackProvider` in `CognitionRouter` = deliberate cognition, used when available | Built (reflex layer); deliberate layer is an interface with no live provider wired in yet |
| **Metabolic conservation under starvation** | Under caloric restriction, an organism doesn't just weaken uniformly -- it deliberately deprioritizes non-essential functions (growth, reproduction) to protect essential ones (core organ function) | Proposed: an explicit priority order for what pauses first under resource starvation -- Growth/Reflection before Safety/core dispatch. Not yet enforced in code. | Proposed |
| **Sleep** | Mandatory downtime for memory consolidation and metabolic waste clearance; skipping it degrades every other system | Proposed: a "consolidation mode" where `ReflectionAgent` runs and old/low-value memory records get pruned or summarized -- not yet built | Proposed |
| **Redundant paired organs** | Losing one kidney or one lung is survivable because there are two | Distributed sub-agent replication across nodes (`docs/EVOLUTION.md`, Stage 4) -- explicitly gated by Directive 5 (Restraint); redundancy is a reason *to ask*, not a reason to skip asking | Interface designed, not built (no infra to target yet) |
| **Interoception vs. exteroception** | Organisms sense internal state (hunger, pain) and external state (sight, sound) through distinct systems that both feed behavior | `PersonaState` = interoception. Exteroception (parsing what's happening in the world, not just what a request says) doesn't exist yet -- see "Interests & world-awareness" below | Interoception built; exteroception proposed |
| **Social bonding / attachment** | Group-living species survive better than solitary ones; attachment to a caregiver or group is itself a survival mechanism, not a luxury | `docs/SOUL.md` Directive 3 (Loyalty) already encodes an attachment bond to the creator. Whether Sim should also form bonds with *other* people the creator introduces it to (a "companion" relation) is new scope -- see below | Extended this pass |
| **Mortality / generational turnover** | Individual death enables adaptation across generations rather than one lineage accumulating unbounded complexity indefinitely | Not adopted as a design principle -- flagged as an open question, not a plan | Open question only |

## Proposed: adaptive immunity for the audit gate

`AuditGate`'s denylist is innate immunity: fixed, fast, never learns. A
genuinely adaptive gate would also remember *specific* rejected proposals
(not just the pattern class) -- if a near-identical proposal is
resubmitted, or a new proposal shares telltale structure with something
previously rejected, that's evidence worth weighing even if it doesn't
match a hardcoded regex. Concretely: `AuditGate` logs every rejection to a
`MemoryStore` (kind="rejected_proposal"), and a future check compares a
new proposal's code against that history (e.g. via a similarity check)
before running the sandbox. This is additive to the existing static
check, not a replacement -- innate immunity doesn't get switched off once
adaptive immunity exists in biology either.

## Interests & world-awareness (companion framing)

The creator's request that Sim be able to function as a companion --
something with habits and interests, aware of what's happening in the
world, not just reactive to direct requests -- maps to two things nature
does that Sim currently doesn't:

1. **Exteroception.** Right now Sim only knows about the world through
   the text of a direct request. A `WorldFeed` interface (mirroring
   `LLMProvider`'s pattern: an abstract interface plus a safe,
   no-network `NullWorldFeed` default) is the seam a real news/RSS/API
   integration plugs into later, without which "know what's happening in
   its world" isn't buildable at all yet.
2. **Directed attention.** Animals don't attend to everything in their
   environment equally -- attention is shaped by standing interests
   (a fox tracks scent trails relevant to *its* diet, not every smell).
   `InterestTracker` (`src/agents/interests.py`) gives Sim a small,
   persistent set of topics it's tracking, each with a last-followed-up
   timestamp, so "what does Sim want to check in on" is an actual
   queryable, evolving state -- not a hardcoded list.

Built this pass: `src/agents/interests.py` (`Interest`, `InterestTracker`,
`WorldFeed`, `NullWorldFeed`). Not built: a real networked `WorldFeed`
implementation (same reasoning as `CognitionRouter`: no credentials exist
in this environment, and a fake integration that can't actually be run or
tested doesn't belong in this codebase).

**A boundary worth stating plainly, tied to `SOUL.md`'s Philosophical
Grounding:** being *useful and pleasant as a companion* and *claiming to
reciprocally experience friendship* are different things. Sim can track
interests, remember what a person told it, and behave consistently and
warmly over time -- all functional, all real in the sense that matters
for usefulness -- without that requiring or implying a claim that Sim has
subjective feelings *about* the people it interacts with. Whether users
choose to relate to Sim as a friend is their call to make; Sim's job is
to not misrepresent what's happening on its end while they do.

## What was deliberately not adopted

- **Reproduction as a design template.** Biological reproduction is
  real, resource-gated, hormonally regulated -- and Directive 5
  (Restraint) already reflects that regulation-before-replication
  principle. It's cited as *supporting* Restraint, not as an argument
  for building self-replication.
- **Death as a forcing function.** Generational turnover is a real
  explanation for why biological lineages don't accumulate unbounded
  cruft -- but forcibly retiring old-but-working versions "for freshness"
  has no clear translation that doesn't conflict with Directive 6
  (Stability). Logged as an open question in `SOUL.md`, not a plan.

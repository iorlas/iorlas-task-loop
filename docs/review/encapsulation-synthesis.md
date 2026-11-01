# Encapsulation review: synthesis (2026-11-01)

Six Codex lenses, additive to [architecture.md](architecture.md) (A) and [dataflow.md](dataflow.md) (D): [modules](encapsulation-modules.md) (M),
[classes](encapsulation-classes.md) (C), [APIs](encapsulation-apis.md) (F), [layers](encapsulation-layers.md) (L),
[leaks](encapsulation-leaks.md) (LF), [ideas](encapsulation-ideas.md) (I). Static findings; each is real until a test refutes it.
The Mac log review (35,587 rows) confirmed the ownership, cleanup, follow-up, noop and error-identity themes; its items are tl-br2.15-.20.

## The pattern behind the P1s

Three families, each a single rule that is broken in many places:
1. **A failed read is treated as an empty/OK answer** (git status, bd output, delegate state files, hook failure, container missing -> host). One rule: *absence and fault are different types; a fault never authorizes anything.*
2. **Evidence is keyed by a weaker identity than the thing it authorizes** (check ids vs full keys, host receipt vs container requirement, prompt hash vs execution, gate selector controlled by the candidate). One rule: *an authorization carries the full identity of what was executed, in the same type the consumer checks.*
3. **A resource is released or reused before its owner is known gone** (delegate lease before worker termination, optional process registration, pid-only tickets). One rule: *release needs positive termination or quarantine.*

## Slices (epic tl-br3 ENCAPSULATION), in order of work. Codex writes, tests first, one release each.

| # | Slice | Merges | Behaviour risk |
|---|---|---|---|
| 1 | GITREAD: decision-critical git reads fail explicitly (typed status/diff/ref faults) | F09 L01 | cleanup/reset paths refuse on fault |
| 2 | BDREAD: malformed bd success is a fault, not absence (Found/Missing/Fault) | F04 | ask reconcile/follow-up lookup keep state |
| 3 | CHECKIDENT: one full check identity for every delivery authorization; resolve executor before reuse; required container never falls back to host; gate-plan base bound | M04 M05 LF01 LF02 F08 | **gate** |
| 4 | GATESELECT: gate selector authority outside candidate control | LF03 | **gate** |
| 5 | HOOKPUSH: pre-push is a thin client of the one delivery judge; unavailable judge refuses | L02 | **push** |
| 6 | WORKERRECOVER: worker recovery bound to an execution identity, not a prompt hash | C07 | no |
| 7 | DELEGATEAUTH (delegate repo): unreadable/incompatible state refused not defaulted; lease kept until termination; mandatory spawn registration; read-only capability not by shell name; lease lifetime inside the exception boundary | M01 M02 M03 M06 L03 C14 C15 | delegate release |
| 8 | REVIEWAUTH: delete lexical acceptance certification; final-candidate review authorization | I.F02 | **review/land** |
| 9 | FREEZEBUNDLE: **owner decision.** I.F01 proposes deleting mid-job engine/delegate replacement (safe-point exec, per-call router switching). The hop exists by design (tl-7y6.9); HOPLOCK/HOPSAFE make it safe, I.F01 removes it. | I.F01 | design |
| 10+ | P2s: CHECKDEDUP (C11), SLOTCAUSE (C12 L-slots), CHECKPOINTCOMMIT (C04), ENGINESPLIT (C01 C02 C03 C05), PROFILEPOLICY (C13 F07), DELEGATECAP (F01 F10 F03), BDCODED (F05), SLOTTICKET (L09), PREPUSHLAYERS (L04 L06 L10 L05 L08), JOBS (I.F03-I.F10), HEALTHCURSOR (M07 M08), REPOID (M09) | | |

Rules: each slice has a bead under tl-br3; slices marked gate/push/review are announced to the owner's session with the version before release.

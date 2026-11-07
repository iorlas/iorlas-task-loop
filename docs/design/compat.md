# COMPAT: no backward compatibility (tl-e5t0.58)

Policy, decided by the owner on 2026-11-07: "I don't care about old runs and backward compatibility. Burn things with fire and move on." The rule is in CLAUDE.md (top section); this note is its detail.

## Policy

- A change to a stored format (a record's fields or `V`, a table, a config shape, a log layout) is made directly, in one release. Nothing reads the old shape.
- Not kept: N-1 or N+1 readers, two-release add/remove steps, compat shims, deprecation periods, "legacy" code paths, dual reads or writes, fallbacks to files.
- Delegate live events use the codec default `kind` tag. Lines carrying only the former `k` tag are refused or skipped as undecodable records; readers never translate it.
- Old data is discarded. When a migration tool exists (a database migration; later a file-storage one) it migrates; until then there is nothing to migrate.
- Exceptions: data in git history, and anything the owner names.

## What stays: loud refusal

A record of a foreign version is refused, never guessed at. `wire.load` raises `StaleRecord` on a `v` it does not know, and `Rec` refuses unknown keys. This is a rule, not compatibility: it keeps a wrong read from becoming a silent wrong act. A refused record does not crash the engine; the run starts over.

## On a version change

An in-flight run whose checkpoint the new install refuses starts over. Rollback to an older install does the same. The effects of an unfinished close (record, bd close, branch cleanup) may need manual cleanup; that is accepted.

## What we gave up

- An in-flight close can be lost at an upgrade or a rollback.
- A running engine that execs into a newer install mid-run may restart its bead from the start.
- Old logs and runs are not readable after a layout change.

The choice is deliberate: the release cadence is high, the cost of keeping old shapes readable was larger than the cost of redoing a run.

## Acceptance

One test: a record with a foreign version is refused loudly (`StaleRecord`) and does not crash the engine.

# core

Records, run state, config, git/proc seams. Every folder may import it; it imports no folder.

- `enginelock.py`: `EngineLock` and `LOCK` (the worktree's engine lock the run notes its workers into; O1 replaces it with the Lease).
- `fmt.py`: `clip`.

The child-process code is `src/taskloop/adapters/procs.py` (stream-proc). Allowed imports: tests/test_rules.py.

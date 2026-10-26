# core

Contracts, records, run state, config, git/proc seams. Every folder may import it; it imports no folder.

- `procs.py`: `child_env`; `run_proc` (one delegate call as a child process); the stop and kill helpers (`stop_tree`, `stop_and_prove`,
  `prove_dead`, `kill_tree`, `send_group`, `send_pid` ...); `EngineLock` and `LOCK` (the worktree's engine lock they note into).
- `fmt.py`: `clip`.

Moved here by E1 (child_env, clip: checks/lint.py needs them) and E2 (process code: lanes/ needs it). Allowed imports: tests/test_rules.py.

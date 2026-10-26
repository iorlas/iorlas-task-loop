# core

Contracts, records, run state, config, git/proc seams. Every folder may import it; it imports no folder.

- `procs.py`: `child_env` (the env a child process gets).
- `fmt.py`: `clip`.

Moved here by E1 because checks/lint.py needs them and may import only core. Allowed imports: tests/test_layers.py.

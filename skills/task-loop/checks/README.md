# checks

Command lint, schedule, trim, gate cache, flakes, fix rounds (E1).

- `lint.py`: the plan's checks and whether they can run (`plan_checks`, `dry_check`, `command_problems`, `timeout_problems` ...).
- `speed.py`: input cache, cheap-first order, duplicate runs, hang watchdog.
- `trim.py`: a check's output trimmed before an agent prompt carries it.

Has an `__init__.py` (no flat `checks.py` to shadow). Imported as `from checks import lint` from the skill directory, which is
`sys.path[0]` when a script runs and the same in an installed copy. Allowed imports: tests/test_rules.py.

# Shadow test selection

`tools/select_tests.py` prints the tests a change should run. It is **shadow-only**: no
gate, CI workflow, release command, hook or engine path calls it. The gate stays
`python3 -m unittest discover -s tests` in `.task-loop.json`.

## Selector

```sh
python3 tools/select_tests.py --base origin/main --list
```

It reads only local Git state for the diff: staged, unstaged, untracked, deleted and renamed
paths. Global/system Git config and external diff helpers are disabled, and no network or
`~/.config` file is read.

Paths under `skills/task-loop/<feature>/` and `tests/<feature>/` map to that feature through
`tests/feature_tests.py`; features that depend on a changed one are added from
`tests/test_layers.py`. Test modules that are not assigned to a feature are always kept
because they are integration coverage. Any unmapped path, Core, `tools/`, `.task-loop.json`,
a `plugin.json`, shared fixtures, a flat hub module, or an incomplete mapping selects the
whole suite. The output is sorted unique unittest ids and no test body runs.

## Replay checker

```sh
python3 tools/replay_select_tests.py RECORDS.json [--json]
```

`RECORDS.json` is an explicit worktree-local file. Its resolved path must stay inside this
worktree; a path outside it, including a symlink that escapes, is rejected before reading.
The checker is offline: it needs no Git, network or user configuration. It requires
**exactly 50 landings**, one per landing of the window, ordered 1..50 without gaps. Each
landing must carry its identity, base and landed SHAs, changed paths, the historical full
test inventory, and the observed failures and errors. A missing outcome is rejected, not
treated as green.

```json
{
  "landings": [
    {
      "id": "landing-001",
      "order": 1,
      "base": "0123456789abcdef0123456789abcdef01234567",
      "landed": "89abcdef0123456789abcdef0123456789abcdef",
      "paths": ["skills/task-loop/checks/trim.py", "tests/test_check_trim.py"],
      "inventory": ["test_check_trim.Trim.test_a", "test_tl.Tl.test_b"],
      "failures": ["test_check_trim.Trim.test_a"],
      "errors": []
    }
  ]
}
```

All 50 objects use the same fields:

| field | meaning |
|---|---|
| `id` | unique landing identity |
| `order` | landing order in the window, exactly 1..50 |
| `base`, `landed` | hexadecimal commit SHAs (7-40 characters); `landed` is unique |
| `paths` | non-empty changed paths as `git diff --name-status` would report them, including both sides of a rename |
| `inventory` | non-empty unique list of every test id the full suite had at that landing |
| `failures` | observed failing test ids; may be empty |
| `errors` | observed erroring test ids; may be empty |

Every failure and error id must be in `inventory`. Duplicate landing ids, orders or landed
SHAs (compared case-insensitively), duplicate inventory ids, and inventories that omit an
observed outcome are rejected.

For each landing the checker recomputes selection with `tools/select_tests.py` and reports:

- the selected count and share of the full inventory;
- every recorded failure or error that the selection missed;
- the median selected share over the 50 landings.

Exit status is `0` only if no selected set missed a recorded failure or error, `1` if one
was missed (the report is still printed), and `2` for an unreadable or invalid record file.

## Missing real input

There is no 50-landing manifest with historical test inventories and full-suite outcomes in
this worktree. Local Git history alone does not hold the old inventories or failures, and
production records under `~/.config` are outside the permitted worktree and are not read.
The historical replay therefore remains a follow-up: supply a sanitized, provenance-linked
50-landing records file inside the worktree, then run the checker and save the input,
per-landing output, zero-miss result and median selected share under
`.task/tl-7y6.7.25/evidence/`.

Synthetic records used by `tests/test_select_tests_replay.py` exercise the checker only.
They are not historical evidence and must never be presented as a replay of real landings.

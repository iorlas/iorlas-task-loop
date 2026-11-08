# Consumer API: contract

For repositories whose commands task-loop runs, these names are stable; everything else is private.
Source of truth: `packages/kernel/src/tlkernel/envvars.py` (`CONSUMER`).

| Environment name | Meaning |
| --- | --- |
| `TL_ARTIFACT_DIR` | Where this attempt writes evidence |
| `TL_ARTIFACT_STEP` | The id of the running check |
| `TL_RUN_ID` | The id of the run this command belongs to |
| `TL_RUN_DIR` | The run's folder |
| `TL_ATTEMPT` | The number of this attempt |
| `TL_WORKTREE` | The worktree the run works in |
| `TL_BRANCH` | The branch checked out in the worktree |
| `TL_SLOT` | The slot's name |
| `TL_CHECK_LOG_<ID>` | The log file of earlier check <ID>; upper-case id with each non-word run replaced by _ |
| `TL_CHECK_RC_<ID>` | The exit code of earlier check <ID>; upper-case id with each non-word run replaced by _ |

The two families expose earlier checks. `<ID>` is the check id upper-cased after replacing each run of non-word characters
with one underscore, as the engine builds it (for example, `editor-test` becomes `EDITOR_TEST`).

`TL_ARTIFACT_DIR` is the documented evidence path: write evidence there. There is no path-helper verb.
`runtime.json` and the run/receipt layout, including the contents of the run folder, are private to task-loop.
Consumers use the environment names above and `tl check` and `tl match` only.

## Matching paths

`tl match GLOB... -- PATH...` prints each supplied path that matches any glob, in supplied order.
It uses the engine's own glob dialect: `**` crosses folders, `*` and `?` stay within a folder, and `{a,b}` selects alternatives.
Quote globs so the shell passes them unchanged. The command exits 0 when something matched, or 1 when nothing matched.

Example: `tl match 'src/**/{a,b}.py' -- src/a.py src/deep/b.py other.py` prints the first two paths.

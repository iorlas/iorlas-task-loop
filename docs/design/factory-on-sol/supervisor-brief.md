# Factory supervisor brief (for the session that runs the factory on sol)

Status: handoff from the coordinator session that ran the factory on the Mac VM (2026-11-13/14). Read `AGENTS.md`,
`docs/glossary.md` and `docs/design/factory-on-sol/design.md` first. The owner (Denis) is mostly away and controls
sessions from the Claude iOS app: state situations and decisions in words, with a recommended option; never ask him to
run a CLI command.

## What you run

| Thing | Where on sol |
|---|---|
| Owner checkout = tracker root (`bd`) | `~/Workspaces/iorlas-task-loop` (single writer from the cut-over; the Mac stops writing) |
| Factory checkout (code that runs) | `~/.local/share/task-loop/checkouts/iorlas-task-loop` (`just install` there only after a drain) |
| Slots | `~/.local/share/task-loop/slots/iorlas-task-loop/s1..sN` (detached worktrees; keep paths within 64 bytes) |
| State, artifacts, rounds log | `~/.local/state/task-loop/` (`factory.db`, `artifacts/rounds.log`); disposable by design |
| Machine config | `~/.config/task-loop/config.toml` (`slot_count`, `round_seconds`, `agent_sandbox` after .170) |
| Dashboard | `127.0.0.1:8765` (read-only); a proxy with sign-in comes later |

Start: `cd $CK && nohup uv run --frozen --no-sync python -I -m taskloop step rounds --backlog tl --tracker-root
~/Workspaces/iorlas-task-loop --checkout $CK --model gpt-6.1-sol --effort high --label real-run-1 --max-running N
--minutes 240 --retake-lapsed > ~/.local/state/task-loop/rounds.out 2>&1 &` with `MISE_TRUSTED_CONFIG_PATHS` set.
Stop only a confirmed python pid with SIGTERM; never kill by name. A reboot of sol stops everything: restart then.

## The loop (every 10 minutes, a `/loop 10m` in your session; recreate it weekly, it expires after 7 days)

1. Rounds alive, dashboard 200, last `rounds.log` line fresh. If dead: restart (after a schema bump: drain first).
2. Board (`/api/board`): for every held task read the agent's answer (`execution.answer_path` under `artifacts/`) and the
   hold cause. Missing prerequisite, sandbox/prompt problem, conflict: file a bead under `tl-8bh9.14` (with
   `--acceptance`), fix it yourself or by a session, then answer the hold: a tracker comment saying why (a comment is a
   must), remove label `held`, add label `real-run-1`.
3. Feed: with fewer tasks in flight than slots, label independent open beads `real-run-1`. Do not label two tasks that
   edit the same files; dashboard tasks one at a time.
4. Tell the owner only what changed or needs him.

## Hard-won rules

* Factory agents have no `bd` and no network (offline sandbox) and cannot read tracker comments: put decisions in the
  task description. `.165` will pass comments into the prompt.
* A task branch cut from an older main is refused `branch_diverged` (.168) and a land conflict (`land:conflict`)
  restarts the task: set the old branch aside (`git branch -f old/<id>-<sha12> origin/task/<id>`, delete local and remote
  `task/<id>`, `tl step release <id> --backlog tl --abandon`), comment, swap labels. `.155` makes the agent resolve
  conflicts.
* Free slots must be clean and detached at main's tip (`git -C <slot> switch --detach main`) or starts are refused.
* A held attempt's unsaved work is saved by the factory as a commit on `task/<id>`; when the factory cannot commit it
  (a false `unsafe` listing, still open), merge that saved commit onto current main yourself in a worktree, run
  `just check` and the full `just test`, PR and merge.
* Schema bump (a landed change to `factory_schema.py`): drain (stop rounds, wait until no `taskloop.attempt_entry`
  runs), save any dirty slot as a WIP commit on a `wip/` branch, `just install` in the factory checkout, move the old
  `factory.db*` aside to `old-vN/` (never delete), `tl slot adopt <checkout> --count N`, restart rounds.
* Never run the whole suite on a factory slot. Before merging anything here run `just check` AND the full `just test`.
* Never delete slots, worktrees, artifacts or old homes; only the owner does.
* Shelf (github.com/yoselabs/shelf) changes go through the shelf session or a worktree: branch, PR, merge, tag on the
  squash merge commit, then a pin bump PR here (`pyproject.toml`, `uv.lock`, `tests/rules/test_isolation.py` SHARED).
* A host sleep or clock jump times attempts out (`run:timeout`): not a task fault, re-queue with a comment (.167).

## Open P0/P1 beads to know

`.170` sandbox mode (sol runs without the sandbox: machine config), `.155` conflict resolution by the agent, `.168` branch
rule, `.165` comments reach the agent, `.162`/`.145` stored causes, `.152` dashboard shows what needs the owner, `.163`
tokens in the dashboard, `.164` sandbox socket tests (landed), `.166` run:killed cause, `.167` clock jumps, `.169`
dashboard bind address.

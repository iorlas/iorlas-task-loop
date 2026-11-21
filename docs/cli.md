# The `tl` command line

Status: **built** (2026-11-19, epic tl-3lpg). Every command, grouped by the layer of the system it belongs to. The
words are the glossary's ([glossary](glossary.md)): a *task* lives in the tracker, a *step* is plan, implement or check, an
*attempt* is one try at a step, a *slot* is a managed worktree, *land* delivers a checked task to origin's `main`.
Each command's own `--help` is the reference for its flags.

## Categories

| | Category | What it is |
|---|---|---|
| A | Setup | What this machine and repository are set up with: config file, slots, starter files, installed version |
| B | Inputs (read-only) | What the factory reads before it works: repository, profile, workflow file, tracker task |
| C | Scheduling | Rounds: pick tasks, move them forward, serve the dashboard |
| D | Step execution by hand | Drive one named task by one attempt: start, factory commit, release, abandon, publish |
| E | Delivery | Land a checked task on origin's `main` and close it |
| F | Factory state inspection | Read `factory.db` and evidence: what each task's attempt is doing |
| G | Stop and upgrade | Block new work and prove the factory idle |

## Commands

| command | cat | purpose | job (reads / writes) | writes? | who uses it |
|---|---|---|---|---|---|
| `tl init` | A | Write the starter `.task-loop.json` (the gate) and `.task-loop/workflows/NAME.toml` (the strategy) a repository lacks, uncommitted; `--workflow NAME` adds another workflow | writes the absent files only, never over one; no Git write; checks and `required` start empty so a task is refused until you name them | yes (files) | you, once per repository and once per extra A/B workflow |
| `tl version` | A | Say which package runs | reads installed package metadata | no | you |
| `tl config show` | A | Show each effective setting and where it came from (flag, file or default), including per-backlog bindings | reads the config file and flags | no | you |
| `tl slot adopt` | A | Register hand-made worktrees as slots | reads Git worktrees; writes slot rows; creates `factory.db`; adds slots only | yes | you |
| `tl slot list` | A | Show the adopted slots and whether a reservation holds each | reads `factory.db` | no | you |
| `tl repo show` | B | Show a checkout's repository identity | reads Git | no | you |
| `tl profile show` | B | Show the resolved profile `.task-loop.json` (setup and checks at a commit; required, target and land from the target) | reads Git | no | you |
| `tl workflow show` | B | Show a workflow file as the factory would read it: digest, agent choice and prompt sections per step, feedback section count and ordered kinds (`text` or renderer, including `attempt_budget`), or why it is refused; JSON includes the ordered `feedback` list | reads Git | no | you |
| `tl task show` | B | Show a task as the tracker holds it | reads the tracker | no | you |
| `tl rounds once` | C | Run one scheduling round over the whole backlog | settles, advances and starts tasks; publishes; holds; under `land: auto` lands one | yes | you |
| `tl rounds start` | C | The factory's long-running process: rounds on a timer and the read-only dashboard; reopens a completed drain | as `rounds once`, repeated | yes | you, in the background |
| `tl step start` | D | Move one named task forward by one launch: admit, relaunch, repeat, advance or re-run checks. `--from` and `--workflow` apply to a task's first attempt only | one application operation, also called by a round | yes | you (A/B arms, manual runs) |
| `tl step commit` | D | Finish the factory commit when the entry did not, then release the slot and publish | writes the verdict, releases, pushes | yes | you; rounds do it too |
| `tl step release` | D | Park the slot of an ended step; the claim stays | writes the release | yes | you |
| `tl step abandon` | D | Throw an attempt away and return the tracker claim | writes the release and the claim | yes | you |
| `tl step publish` | D | Retry the push of an accepted commit to origin's `task/<id>`, never forced | pushes | yes | you; rounds do it too |
| `tl land run` | E | Squash the checked commit onto origin's `main`, re-check if needed, push, close the task | pushes; closes the task in the local tracker | yes | you; a round under `land: auto` |
| `tl land show` | E | Show the facts to read before landing | reads | no | you |
| `tl land withdraw` | E | Give up a validated, undelivered land candidate | writes | yes | you |
| `tl attempt show` | F | Explain a task's current attempt as the factory holds it: entry, setup, result, hold and what happens next | reads `factory.db`, evidence, Git; includes what the harness reported it ran | no | you; the dashboard reads the same |
| `tl attempt list` | F | One line per task: where everything stands | reads `factory.db` | no | you; the dashboard |
| `tl attempt setup-times` | F | Recent implement setup durations | reads `factory.db` | no | you |
| `tl attempt export` | F | One comparison row per agent attempt as CSV or JSON: task/backlog and repeat-chain identifiers, base commit, factory-commit verdict, hold cause, terminal result, setup and latest check durations, repeat count (earlier attempts of the chain that were repeats, answer repairs excluded), time to green, wall time, digests, requested/reported agent settings and token counts (`c_*` are cumulative tokens; NULL means unknown; incomplete usage is a lower bound; no dollars). Time to green spans chain admission to this row's latest passed checks; check durations use their latest block (a JSON object in CSV). The final launched-input digest is not stored in `factory.db`; `input_digest` is the admitted input. | reads `factory.db` | no | you |
| `tl drain` | G | Block new work, let executions finish and verify the factory idle before an upgrade or restart; a completed drain stays until `tl rounds start` runs again | writes a durable drain request | yes | you |

`tl task show` is the tracker's view of a task; `tl attempt show` is the factory's view of its attempt.

## Rules the commands follow

- A command is one application operation behind a thin parser; a round and the dashboard call the same operations.
- Messages state the situation and the decision in words. They never ask you to run a command or name a flag, and the
  tracker's and Git's own command names stay inside their adapters.
- A flag is named like its machine-config key (`--slots-root`, `--slot-count`, `--round-seconds`). A backlog's tracker
  root, checkout and label can live in the machine config as `[backlogs.<key>]`; the flags override them.
- Old spellings are deleted, not aliased.

## Stopping rounds

There is no `tl rounds stop`. Stopping rounds from another shell is `tl drain`: rounds poll the drain request and end when it is
set, and running attempts finish in their own processes. Drain also refuses hand `tl step start` and `tl rounds once` until
`tl rounds start` reopens it. No signal is sent, so the one signal owner stays `interrupts.py`.

## Not built

- Slot retirement (`slot adopt` adds slots only).

# tl-8bh9.14.156: the factory at conventional locations

Status: built (code) with a cut-over runbook for the coordinator (not yet run). Owner decision 2026-11-13: convention
over configuration; no hand-made factory home, no hash folder. Supersedes tl-8bh9.14.141.

## What the code does now

| Fact | Convention |
|---|---|
| Machine config | `~/.config/task-loop/config.toml`; absent means all defaults; `--config FILE` overrides. |
| Database and evidence | `~/.local/state/task-loop/factory.db`, `~/.local/state/task-loop/artifacts/`. |
| Slots | `~/.local/share/task-loop/slots/<repo name>/sN`. The repo name is the last path part of the origin URL without `.git` (else the checkout folder's name), cleaned to `[A-Za-z0-9._-]`. |
| Name collision | Only when another repository's adopted slots already sit in `<repo name>`, the repo's key (the internal hash) joins it: `<repo name>-<key>`. A repository keeps the folder it adopted under. |
| Dashboard | `tl step rounds` serves it on `127.0.0.1:8765`; `--dash-port PORT` changes the port (0: a free port); `--no-dashboard` serves none (a second rounds on one machine, and tests). A port already in use is a warning, rounds go on. |

The hash stays internal (the `repo_id` column and reservations); `slots.folder_name` is the one place a folder name is
derived and `slots.adopt` the only place a slot path is made. `tl slot adopt` still prints the path it wants for a slot
Git does not list yet.

## Cut-over runbook (coordinator)

Rules: do not kill anything by name; stop only a process whose identity (pid, command line, start time) you have
confirmed as the live rounds. Do not delete or touch any old slot: the old `s2` and `s4` hold unsaved work, and only the
owner removes old slots. `OLD` below is the current factory home that holds `config.toml`, `state/`, `slots/` and the
rounds log; `CHECKOUT` is the owner's own checkout of the repository on `main` (not a folder inside `OLD`, so `OLD` can be
retired by the owner later without breaking the new slots). The old slots stay linked to the repository they were made
from and keep working as plain folders.

1. Install the merged code where the new factory will run (from `CHECKOUT`, on up-to-date `main`):

   ```bash
   cd "$CHECKOUT" && git pull --ff-only && just install
   TL="uv run --frozen --no-sync python -I -m taskloop"
   ```

2. Drain. Stop new work first: stop the rounds process (confirm its pid from the start line of `OLD`'s rounds output and
   `ps -o pid,lstart,args -p <pid>`), then send that pid `SIGTERM` (the abrupt stop; a rounds started with SIGINT ignored
   takes only this). Launched steps keep running. Wait until none runs and nothing is in flight:

   ```bash
   $TL --config "$OLD/config.toml" step list --backlog <backlog> --tracker-root <tracker root>
   ```

   Repeat until every task is done, held or waiting, none `running`. Anything still waiting to land: land it with
   `tl step land TASK` (or leave it: schema v16 discards `OLD/state/factory.db`, so unlanded work is recovered from its
   published `task/<id>` branch by normal reevaluation; do not discard before every needed branch is pushed).

3. Look before moving anything: every old slot's state, so nothing unsaved is lost.

   ```bash
   for slot in "$OLD"/slots/*/s*; do echo "== $slot"; git -C "$slot" status --short --branch; done
   ```

   Do not clean, reset or remove any of them. `s2` and `s4` are known to hold unsaved work; they stay where they are.

4. Create the conventional config (only the keys that differ from the defaults; the old file also named paths, which the
   defaults replace):

   ```bash
   mkdir -p ~/.config/task-loop
   printf 'slot_count = 4\nround_seconds = 15\n' > ~/.config/task-loop/config.toml
   ```

   Leave out `db`, `artifacts` and `slots_root`: they default to `~/.local/state/task-loop/factory.db`,
   `~/.local/state/task-loop/artifacts` and `~/.local/share/task-loop/slots`.

5. State: nothing to copy. The first command that opens the store creates `~/.local/state/task-loop/factory.db` at schema
   v16; the old `OLD/state/factory.db` (an older schema) is never read, it only stays on disk until the owner deletes
   `OLD`. Past artifacts and logs stay in `OLD/state/artifacts`; the new rounds log starts in the new artifacts folder.

6. Slots: make fresh worktrees at the new place, detached, from the owner's checkout, then adopt them (the name
   `iorlas-task-loop` is the origin's repo name; `slot adopt` prints the exact path if one is wrong):

   ```bash
   SLOTS=~/.local/share/task-loop/slots/iorlas-task-loop
   mkdir -p "$SLOTS"
   for n in 1 2 3 4; do git -C "$CHECKOUT" worktree add --detach "$SLOTS/s$n" origin/main; done
   $TL slot adopt "$CHECKOUT"
   ```

   Expect four `adopted` lines. If a slot is `not_listed`, make it with the `git worktree add --detach` path printed.

7. Start the rounds as before but without `--config` and `--dash-port` (the dashboard comes up on 8765 by itself), with
   the same backlog, tracker root, label and checkout, in the owner's terminal or the process manager the owner uses:

   ```bash
   cd "$CHECKOUT" && $TL step rounds --backlog <backlog> --tracker-root <tracker root> --label <label> --checkout "$CHECKOUT" --max-running 4
   ```

   Check: the start line names `~/.local/state/task-loop/artifacts/rounds.log`; `http://127.0.0.1:8765/` answers; the
   first round starts a task in a new slot under `~/.local/share/task-loop/slots/iorlas-task-loop/`.

8. Afterwards: nothing in `~/.config`, `~/.local/state` or `~/.local/share` refers to `OLD`. Tell the owner that `OLD`
   (its old slots `s1`..`s4` under the hash folder, its repo clone, the old database and artifacts) can be removed by them
   after they have saved what `s2` and `s4` hold; the coordinator removes none of it.

Rollback before step 7 is just not starting: `OLD` is untouched, its rounds can be started again with its `--config`.

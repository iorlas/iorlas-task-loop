# tl-8bh9.14.156: the factory at conventional locations

Status: built; the cut-over ran 2026-11-13 (runbook below, as run). Owner decision 2026-11-13: convention
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

## Cut-over runbook (as run 2026-11-13)

Rules: never kill by name; stop only a process whose identity (pid, command line, start time) is confirmed. Touch no old
slot: the old `s1`..`s4` all held unsaved work, and only the owner removes them. `OLD` is the previous factory home
(`config.toml`, `state/`, `slots/<hash>/`, its repo clone); it is never read again and the owner deletes it later.

1. Drain the old factory. Rounds stopped first (only `SIGTERM` stops a rounds started with SIGINT ignored); launched steps
   keep running, so wait for each, or stop the one confirmed pid. Check with the old config (the command takes `--config`
   before `step`, and only `--db`, `--stuck`, `--json` after it):

   ```bash
   tl --config "$OLD/config.toml" step list
   ```

   Anything unlanded is recovered from its published `task/<id>` branch by normal reevaluation; schema v16 discards the
   old `factory.db`, which is never read.

2. Config: `~/.config/task-loop/config.toml` holds only what differs from the defaults (`slot_count = 4`,
   `round_seconds = 15`). `db`, `artifacts` and `slots_root` default to `~/.local/state/task-loop/factory.db`,
   `~/.local/state/task-loop/artifacts` and `~/.local/share/task-loop/slots`.

3. A dedicated checkout the factory owns, so the owner's own checkout is never the rounds' checkout:
   `~/.local/share/task-loop/checkouts/<repo name>`, a clone of the origin on `main`, then `just install` there.

4. Slots, detached, from that checkout, then adopt (the folder is the origin's repo name; `tl slot adopt` prints the exact
   path for one Git does not list yet):

   ```bash
   C=~/.local/share/task-loop/checkouts/iorlas-task-loop
   for n in 1 2 3 4; do git -C "$C" worktree add --detach ~/.local/share/task-loop/slots/iorlas-task-loop/s$n origin/main; done
   tl slot adopt "$C"
   ```

5. Start rounds from that checkout without `--config` or `--dash-port` (the dashboard is on 8765 by itself), with the same
   backlog, tracker root, label and flags as before and `--checkout "$C"`. The start line names
   `~/.local/state/task-loop/artifacts/rounds.log`, and `http://127.0.0.1:8765/` answers.

6. Afterwards nothing under `~/.config`, `~/.local/state` or `~/.local/share` refers to `OLD`. The owner removes `OLD` once
   they have saved what its slots hold.

Result: rounds run from `~/.local/share/task-loop/checkouts/iorlas-task-loop`, slots at
`~/.local/share/task-loop/slots/iorlas-task-loop/s1..s4`, state under `~/.local/state/task-loop`, dashboard on 8765.

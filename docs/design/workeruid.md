# WORKERUID: workers and checks run as a separate unix user (tl-7i9k.54, R9-59 / M-060 / DQ-07)

Status: design, no code. Docs only until the lead answers. DQ-07 is answered in the synthesis: **yes, devbox gate host first, Mac later**.

## Acceptance (from the bead)

The gate host's checks and workers run as `tlgate`; the owner's SSH key and config are unreadable to them.

## What runs as whom today

One uid runs the owner's sessions, the loop, the engine, delegate (a library inside the engine process), every worker and every check
(SEC-FABLE-32, SEC-OPUS-40; `gate-host.md` §3.3). Consequences: a worker or check can read `~/.ssh`, `~/.config/task-loop` (the factory
store, bd), the vendor logins in `~/.claude`/`~/.codex`, and can rewrite the shim, hooks and the installed engine (SEC-FABLE-06/23).
Text filters (SECRET_RE, hooks, Landlock for codex) are tripwires, not a boundary.

## What `tlgate` must be able to do

| need | how | open |
|---|---|---|
| read/write a worktree | worktrees live under a group-writable parent (`~/gate/...`) or are owned by `tlgate` and created by it | the bare repo `~/gate/lifesim.git` (GATEHOST-DEVBOX) is the natural owner |
| call a vendor | its **own** logins (`codex login`, `claude` OAuth, OpenCode keys) under `/home/tlgate`; **not** the owner's | a second subscription login or a shared API key: money/ToS question for the owner |
| push/fetch git | a per-repo **deploy key** held by `tlgate`; no agent socket forwarded (`SSH_AUTH_SOCK` is in `childenv.ALLOWED` and must not be set for tlgate) | which repos get push, who rotates |
| talk to the engine | engine (owner) starts the work: `sudo -n -u tlgate -- <launcher>` limited by a sudoers line to one launcher, or `ssh tlgate@localhost` | sudo vs ssh; the launcher must accept an argv and a cwd and nothing else |
| write results | a per-run folder owned by `tlgate`, group-readable by the owner; the owner copies/reads, never executes from it | |

## Where it plugs in (devbox first)

The `where: linux` path already exists: `app/checks/linux.py` pushes the committed tree to `engine.executor` over ssh and runs the check
there. For the devbox that executor becomes `tlgate@devbox`: no task-loop code change for **checks**, only the host's account and its
`authorized_keys` command restriction (provisioning, `homelab`). Receipt signing (gate-host §3.3, "later") needs `tlgate`'s key unreadable to
the checks, which a separate uid gives: the signer is a root-owned or owner-owned helper the check cannot read.

**Workers** are the new part. `delegate.api.run` launches the CLI inside the engine's uid. The seam is the one ISOLATION already proposes
(`docs/design/isolation.md`, `Agent.start/stop`): a launcher that runs the worker as `tlgate`. Until that surface exists (tl-hwv5.2/.3),
the honest first slice is **checks only**; workers follow when `start` can be pointed at a different uid without the engine reading the
worker's pids (the pid protocol is exactly what ISOLATION removes).

## Mac

macOS has no cheap second uid for GUI-less work (`sysadminctl` user, no Docker): out of scope for this note; DQ-07 says later.

## Steps (each its own bead/PR, tests first)

1. `tlgate` on the devbox: account, deploy key, `authorized_keys` forced command, sudoers none (homelab; nothing in this repo).
2. `engine.executor` points at `tlgate@devbox` for the lifesim gate; test: the existing `tests/checks/` linux-executor tests over a fake ssh
   already cover the argv; add one real test (devbox only, skipped elsewhere) that a check cannot `cat ~owner/.ssh/id_*` (acceptance).
3. A doctor line: `executor account: tlgate (not the owner)`; WARN when the executor's user equals the engine's.
4. Workers: after ISOLATION A/B land; design then.

## Decisions for the owner

1. Vendor logins for `tlgate`: a second subscription login (cost, ToS) or API keys for gate-host workers only? Without it workers cannot move.
2. Sudo or ssh as the hand-over (recommendation: ssh forced command; no sudoers rule on the engine's account).
3. Is "checks only" an acceptable first closing of the bead's acceptance ("checks **and workers**")? Recommendation: split the bead.

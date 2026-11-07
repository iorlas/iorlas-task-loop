# NETISO: checks run with no network (tl-7i9k.59, follow-up of CHECKENV R9-02)

Status: design, no code. Docs only until the lead answers. Read from origin/main; one fact measured on pix (below).

## Why

A check is the candidate's code: a test, a build, a script the writer or planner chose. With the owner's network it can fetch, upload and
push. CHECKENV (0.23.317) cleaned the environment (`tlkernel/childenv.py` `ALLOWED`); the network was left open because no host could
remove it. The bead's acceptance is: no network for a check unless the repo's profile says `network: true`; refuse (never silently
run with network) where a host cannot remove it; one real test per host.

## What is true today (measured)

| host | tool | state |
|---|---|---|
| macOS (the owner's Mac, the gate) | `sandbox-exec -p '(version 1)(allow default)(deny network*)' CMD` | present on every macOS; deprecated by Apple but works; not tested here (pix is Linux) |
| pix (this host, NixOS in OrbStack) | `unshare -rn CMD` | **works**: `unshare -rn true` exits 0, a TCP connect inside fails with `Network is unreachable`, outside succeeds; no `bwrap`, no `firejail` |
| the devbox container | `unshare -rn` | the bead says it fails (`Operation not permitted`, user namespaces off). Unchanged: needs the container definition (homelab), not a task-loop change |

So the bead's blocker "no current host can run it" is already false for pix. A per-host test needs a Linux host with userns and a Mac.

## Where the change goes

One place builds a check's argv: `app/checks/shell.py` `RunShell.stream`, the branch `what in {"check", "check fix"}`, which already prefixes
`check_nice(PATH)`. The new prefix goes next to it, from a pure function in `adapters/` (a new `check_net.py`):

```
check_net(os_name, network: bool, tools: Which) -> Prefix | Refusal
  network true                      -> []                                     (declared in the profile)
  Darwin, sandbox-exec found        -> ["sandbox-exec", "-p", DENY_NETWORK]
  Linux, `unshare -rn true` works   -> ["unshare", "-rn"]
  anything else                     -> Refusal("no way to remove the network here: <why>")
```

Not covered by that prefix, and each needs its own line in the PR that implements it:

- `where: linux` checks (`app/checks/linux.py`) run over ssh on the executor: the same prefix must be applied on the executor side (the argv
  after `env -C work`), with the executor's own tool test. A down executor already fails the check; a missing tool fails it the same way.
- The planner's own gate-plan producer (`gateplan.py` `host.spawner.run([...argv, "--base", ...])`): runs repo code too; it takes the prefix.
- Network-needing steps that are not checks (git fetch/push in land, `uv` sync in `prepare`): they are not `check`/`check fix`, so they are
  untouched. A check that needs a package install must declare `network: true` (or the install moves to `prepare`).

## Profile key

`CheckSpec.network: bool = False` (`contracts/config.py`, next to `env`). Per the repo rule a new `.task-loop.json` key ships one release
after the code that reads it: release N reads the key (default false = deny), release N+1 lets profiles set it. A consumer repo whose checks use the network (restore, a registry) breaks at release N until N+1, hence decision 1 below (warn-only for
one release).

## How it degrades

Single path, no fallback (the bead): a host with no tool refuses the check with the reason, and the gate is red with that sentence. The only
switch is the per-check `network: true`. `tl doctor` gains one line: `check network isolation: sandbox-exec | unshare -rn | NONE (checks refuse)`.

## How to test on pix

- Unit (no process): `check_net` over a table of (os, tools found, network flag) -> prefix or refusal; the `RunShell.stream` argv for a check
  carries the prefix and for a non-check does not (fake spawner, procsim).
- Real, Linux (`tests/checks/real/`, `@real_proc`): run `["unshare","-rn","python3","-c", connect]` through `RealSpawner`: red; with `network: true`:
  the same connect runs (to a local socket the test listens on, so the sandboxed loopback is also checked: `unshare -rn` has `lo` down, a
  check that talks to localhost needs `ip link set lo up`; note in the doctor line). Skipped with a stated reason where `unshare -rn true` fails.
- Real, macOS: the same test with `sandbox-exec`; runs only on the Mac gate.

## Decisions for the owner

1. Default for existing repos at release N: deny with the red sentence (breaks network checks until profiles say `network: true`), or
   **warn-only for one release** (log "would be refused") then deny? Recommendation: warn-only first, because the key cannot be set before N+1.
2. Loopback: bring `lo` up inside the namespace (`unshare -rn sh -c 'ip link set lo up; exec "$@"'`) so local test servers work.
   Recommendation: yes; sandbox-exec can allow `(allow network* (remote ip "localhost:*"))`.
3. Devbox: the container definition change is the homelab owner's; this repo does not wait on it (the devbox check refuses with the reason).

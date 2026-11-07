# Windows audit: what blocks task-loop on native Windows

Date 2026-11-05. Read-only audit by grep and reading; no code run on Windows, no test suite run.
Scope: `src/`, `dev/`, `hooks/`, `justfile`, `mise.toml`, `skills/task-loop/_vendor/` (the vendored shelf packages), `tests/` (counts only).
Beads: tl-w7lt.38.12 (WINEXEC, Windows executor over OpenSSH), tl-w7lt.38.13 (WINENGINE, engine native), tl-6vb (POSIX-only ruling, superseded for the engine by `docs/design/topology.md` "Windows and Unity" 2026-11-05).
Earlier input: the 2026-11-04 audit named five items (process_lock fcntl, stream_proc tree kill, SIGTERM stop, symlink pid index, sh shims). All five are confirmed below; this audit finds more.

Sizes: S = under a day, one file; M = days, one module and its tests; L = a design plus a new backend, weeks.
"Not tested" means read from the code, not run on Windows.

Verdict in one line: the engine is not close. Three foundations (process groups and signals, `flock`, `/proc`/libproc process table) are POSIX in the vendored shelf packages and are used by every layer above them. Everything else is smaller and mostly mechanical.

```
layer                        POSIX coupling                      Windows work
---------------------------  ----------------------------------  ------------------
shelf: process_lock          fcntl.flock                         L (new backend)
shelf: stream_proc           killpg, getpgid, setsid, /proc       L (Job Objects)
shelf: any_lease             flock probe, os.link, preexec_fn    M
engine: stop channel         SIGTERM handlers in ~12 places      L (design)
engine: launch/factory       setsid detach, symlink pid index    M
shims + hooks                #!/bin/sh, #!/usr/bin/env -S        M
delegate sandbox/policy      sandbox-exec, zsh, shlex rules      L (or drop on Win)
dev / release / justfile     bash recipes, xargs, grep           M
tests                        ~76 files use POSIX primitives      M-L
```

---

## 0. Requirement (Denis, 2026-11-05): all four, natively, for now

The engine, delegate and dashboard must run natively on macOS, Linux, WSL and native Windows. Isolation (executor, runner, separate dashboard) may relax this later; until then every host runs everything. This replaces the framing "Windows later, POSIX engine" and the WSL-versus-native question: WSL is a required platform, not a fallback.

Where each platform stands today (read from the code; not tested except where tl-6vb says):

| Area | macOS | Linux | WSL2 | Windows native |
|---|---|---|---|---|
| Process table (P3) | libproc, done | `/proc`, done | `/proc`, same code as Linux | missing |
| Tree kill, groups (P1, P2) | done | done | done (Linux kernel) | missing (Job Objects) |
| `flock` (L1) | done | done | done on the Linux filesystem; on `/mnt/c` (9p) unknown | missing |
| Stop by SIGTERM (P5, P6) | done | done | done inside WSL; a Windows-side `tl stop` cannot signal a WSL process | missing |
| Shim and hooks (H1-H4) | sh | sh | sh | missing |
| Sandbox for OpenCode (H5) | `sandbox-exec` | **none** | **none** | none |
| Keep-awake, RAM (P9, F17) | caffeinate, vm_stat | RAM via cgroup; no keep-awake | as Linux | missing |
| Test suite | green (Mac is the reference) | **red: 6 failures, 8 errors (tl-6vb, 2026-10-27)** | not run | not run |

What this changes against the first draft:

- Linux and WSL are not "free". The suite is red on Linux today (tl-6vb), and OpenCode already works on macOS only (`opencode.py:103`, `onboard.py:35-51`): the four-platform requirement is already broken for Linux. Fixing Linux first is the cheapest step toward all four, and WSL then needs only its own checks.
- WSL-specific risks (each not tested):
  - W1. A checkout or `~/.config/task-loop` on `/mnt/c` (9p/drvfs): flock, SQLite WAL, `os.replace` and mtime-based invalidation behave differently, and every file touch is slow. `_vendor/sqlite_store/filesystem.py:19-45` reads `/proc/mounts` but refuses only `nfs`, `cifs`, `fuse`, `smb` prefixes, so `9p` and `drvfs` pass as safe. Add them, and make setup warn when the repo or the state dir is on `/mnt/*` (S).
  - W2. A WSL distro and Windows on one PC are two machines to task-loop: each has its own `~/.config/task-loop`, its own factory, its own lease table. Denis 2026-11-05: fine. Consequence: they share the hardware (RAM, disk, GPU) without seeing each other, so a Unity lease or a RAM floor is counted per side; a user running Unity in Windows and a heavy job in WSL must keep that in mind. No code is needed; `host.json` (`unity` resource) is set only on the Windows side.
  - W3. A WSL engine cannot start Unity or a GUI game on the Windows side except by calling `*.exe` through interop or ssh to the Windows executor; this is the original reason for the native Windows engine (tl-w7lt.38). Path translation (`wslpath`) is needed wherever a path crosses the boundary (S-M).
  - W4. `/dev/null`, `/tmp`, symlinks, `chmod` and shell policies all work as on Linux inside WSL; the only change is W1.
- Because four platforms share one code base, the unit of work is a **platform seam**, not "Windows patches": one interface per primitive (`FileLock`, `TreeKiller`, `ProcessTable`, `StopChannel`, `ShimWriter`, `HostResources`), one implementation per platform family (posix+libproc, posix+procfs, win32), and one contract test per interface that runs unchanged on all four hosts. The POSIX implementations are what ships today, moved behind the interface with no behavior change (the "no-regret" item in section 7). The Windows work is then one new implementation per interface, not edits spread over 40 files.
- There is no hosted CI ("the factory is the CI"). Four platforms need four hosts running the same contract tests. Cheapest order: Linux in a container (tl-6vb, already designed), WSL on the Windows box (the Linux code path, plus W1), Windows native on the same box.

---

## 1. Process control

| # | Where | What it does | Windows equivalent / design choice | Size |
|---|---|---|---|---|
| P1 | `skills/task-loop/_vendor/stream_proc/tree.py:29-101` | `stop_tree`: `os.getpgid`, `os.killpg`, `os.kill(SIGTERM/SIGKILL)`, a sweep of descendants that left the group, then a proof of death | Job Object per child (`CreateJobObject` + `AssignProcessToJobObject`, kill-on-close); a graceful "SIGTERM" has no equal: `CTRL_BREAK_EVENT` to a `CREATE_NEW_PROCESS_GROUP` child, or `TerminateJobObject` only. Decision: is a grace period still promised? | L |
| P2 | `stream_proc/runner.py:139`, `capture.py:128`, `src/taskloop/adapters/procs.py:78`, `adapters/spawner.py:93`, `src/delegate/adapters/procs.py:46`, `dev/race.py:200` | `start_new_session=True` (setsid) so the child leads its own group | `creationflags=CREATE_NEW_PROCESS_GROUP \| CREATE_BREAKAWAY_FROM_JOB` plus a Job Object; `start_new_session` is ignored/invalid on Windows. One helper in stream_proc fixes all callers if they go through it (they mostly do). | M |
| P3 | `stream_proc/procfs.py:18-85`, `procmac.py` (libproc via ctypes), `proctable.py:19` (selector by `sys.platform`) | Process table from `/proc/<pid>/stat` or libproc; start token = start time, so a reused pid is detected | A third backend: `CreateToolhelp32Snapshot` / `NtQuerySystemInformation` via ctypes, or `psutil` (a new dependency, which the "stdlib only" vendored style avoids). Start token = process creation time (`GetProcessTimes`). The `else` branch of `proctable.py` falls to `procfs.has_proc() == False`: no table, so `stop_pid` "touches nothing" (`pid.py` docstring) and a leaked tree is never reaped. Silent failure, not a crash. | L |
| P4 | `stream_proc/procfs.py:85`, `process_lock/__init__.py:229`, `stream_proc/proctable.py:61-69` | `os.kill(pid, 0)` and `os.killpg(pgid, 0)` as a liveness probe | On Windows `os.kill(pid, 0)` is not a probe: signal 0 is not CTRL_C/CTRL_BREAK, so it calls `TerminateProcess` with exit code 0 and kills the target. Must be replaced by `OpenProcess` + `GetExitCodeProcess` (or the P3 table). Dangerous if ported without a change. | S |
| P5 | `src/taskloop/adapters/halt.py:24,40`, `app/run/closer.py:98-107`, `app/run/entry.py:308-314`, `adapters/landlock.py:75-92`, `cli/loop.py:117-122`, `src/delegate/app/supervisor.py:252-278`, `dev/runtests.py:73`, `skills/task-loop/_vendor/any_lease/__main__.py:17-89`, `stream_proc/hold.py:21-56` | `signal.signal(SIGTERM)` handlers set the stop flag; `SIG_IGN` around give-back; `SIGHUP` in delegate | Windows Python has `SIGINT`, `SIGBREAK`, `SIGTERM` (the constant exists, but nothing delivers it from another process). `signal.SIGHUP` does not exist: `supervisor.py:252` raises `AttributeError`. Cross-process stop must move to a different channel (below, P6). | M |
| P6 | `src/taskloop/app/loop/run.py:52-53` ("stop now: SIGTERM through stream-proc"), `app/run/requests.py:102`, `skills/task-loop/tl.py:41,263` (`tl stop --now`) | The owner stops a running bead by sending SIGTERM to the engine | No cross-process SIGTERM on Windows. The code already has a file channel (`requests.stop` read at the step boundary, `requests.py:102`: "The file stays for the step boundary to take"); `--now` needs a second channel with immediate effect: a named event (`CreateEventW`), a loopback socket, or polling the file inside `halt`. Design choice. | M |
| P7 | `src/delegate/app/supervisor.py:268-287`, `src/delegate/app/run.py:227,251`, `app/lease.py:22-28`, `app/publish.py:92` (`os.getpgid(pid)`) | Delegate keeps the worker in its own group (pgid = pid); `rc = -signal.SIGKILL`; orphans of a SIGKILLed route.py are found by pid + group | Job Object ownership replaces group ownership; an orphan survives the parent only if the job lacks kill-on-close, so the "orphan reap at claim" logic is partly moot but must be redesigned, not deleted. `os.getpgid` has no Windows equivalent. | L |
| P8 | `src/taskloop/app/launch/factory.py:55-66`, `app/loop/exits.py:27`, `app/launch/factory.py:47` | `factory-lane-N.log` is a symlink to `factory-<pid>.log`; the pid is read back with `readlink()` | Symlinks need Developer Mode or admin on Windows. Replace the symlink with a small file (`factory-lane-N.json` holding the pid and log name). The 2026-11-04 audit's "symlink pid index". | S |
| P9 | `src/taskloop/adapters/factory.py:1-8`, `app/launch/factory.py:120` | `caffeinate` keep-awake, already gated by `platform.system() == "Darwin"` | Safe as is (returns no argv elsewhere). Windows equivalent is `SetThreadExecutionState(ES_SYSTEM_REQUIRED)` via ctypes in the factory process; optional. | S |
| P10 | `src/taskloop/app/track/outcome_line.py:30` | `fcntl.fcntl(fd, F_SETFL, ... \| O_APPEND)` on a log fd that was opened without append | `import fcntl` at module top (`outcome_line.py:2`) is an `ImportError` on Windows: the whole run entry module cannot be imported. Fix: reopen with `os.fdopen(os.dup(fd), "ab")` or have the spawner open logs append-only (`open(path, "ab")` already gives `O_APPEND`). | S |
| P11 | `src/delegate/app/codex_policy.py:112` | `os.waitpid(os.posix_spawnp(...))` | `posix_spawnp` does not exist on Windows; use `subprocess.run`. | S |
| P12 | `src/delegate/adapters/procs.py:23,80`, `src/taskloop/adapters/runner.py:162-177` | Stop = SIGTERM, 5 s grace (`DELEGATE_STOP_GRACE`), SIGKILL | Same as P1; the "term_sent/kill_sent" report fields lose meaning (Windows has one hard kill). Contract change in `docs/contracts/delegate-api.md` if the report keeps both flags. | M |
| P13 | `skills/task-loop/_vendor/any_lease/__main__.py:77` | `preexec_fn=lambda: signal.pthread_sigmask(...)` | `preexec_fn` is not supported on Windows (raises `ValueError`); `pthread_sigmask` does not exist. Drop on Windows (no signal mask is inherited there). | S |
| P14 | `stream_proc/runner.py:67`, `capture.py:56,72,76`, `src/delegate/adapters/codex_account.py:43`; `tree.py:27` (`os.getpgrp`) | Worker stdout/stderr are pumped with `select.select([fd])` + `os.read`; `os.set_blocking(fd, False)` on pipes; `os.getpgrp()` in the stop sweep | Windows `select` accepts sockets only, and non-blocking pipes via `set_blocking` do not work: no worker output reaches a log. Needs reader threads (simplest) or overlapped I/O. `os.getpgrp` is an AttributeError. Missed in the first draft (found in review, lines checked). | M-L |

## 2. Locking

| # | Where | What it does | Windows equivalent / design choice | Size |
|---|---|---|---|---|
| L1 | `skills/task-loop/_vendor/process_lock/__init__.py:20,187` | `fcntl.flock(fd, LOCK_EX \| LOCK_NB)`; the kernel drops it when the holder dies (kill -9 included); one open file description per holder; same-process reentry is guarded separately | `msvcrt.locking(fd, LK_NBLCK, 1)` or `LockFileEx` via ctypes with `LOCKFILE_EXCLUSIVE_LOCK \| LOCKFILE_FAIL_IMMEDIATELY`. Semantics match well: Windows also releases byte-range locks when the process ends (promptly, but not instantly like flock). Differences: the lock is mandatory (other handles cannot read the locked bytes: lock a byte beyond EOF, as `msvcrt` docs allow), and a file opened by another process cannot be deleted/renamed. This is the foundation: `guard.py`, `lander.py`, `slots/lease.py`, `any_lease`, the land lock all stand on it. | L |
| L2 | `_vendor/any_lease/leases.py:6,198-254` | Counting lease: a unit "counts only while its flock is held", found by a shared probe `LOCK_SH \| LOCK_NB` on a separate descriptor | `LockFileEx` without the exclusive flag gives a shared lock; but a shared probe on a byte another handle holds exclusively fails, which is what the probe wants. Same-process probe semantics differ (Windows locks are per handle, flock is per open file description), so the "separate descriptor" trick should hold. Not tested. | M |
| L3 | `_vendor/any_lease/leases.py:181` | `os.link(tmp, path)` for atomic create-with-content, first declarer wins | `os.link` works on NTFS (hard links) but not on FAT/exFAT or some network shares. Use `os.open(path, O_CREAT\|O_EXCL)` + write, or `os.replace` with a `FileExistsError`-style check; `O_EXCL` write is not atomic against readers (a reader may see it empty): read side must tolerate an empty file. | S |
| L4 | `src/taskloop/stores/files.py:60`, `src/taskloop/app/artifacts/keep.py:22-113` | `os.link` for tickets and for artifact dedup by `(st_dev, st_ino)` and `st_nlink` | Windows `st_ino`/`st_dev` are populated on NTFS since Python 3.5 (file index, volume serial), so dedup works on NTFS only. Ticket link: same as L3. | S |
| L5 | `_vendor/sqlite_store/quarantine.py:5,30-40` | `fcntl.flock` to retire a corrupt DB file once | Use process_lock's new backend (L1). | S |
| L6 | `_vendor/sqlite_store/connections.py:42`, `store.py:115`, `src/taskloop_dash/index/__init__.py:99,143`, `readers/wake.py:46`, `src/taskloop/adapters/gitrepo.py:43-52` | `(st_dev, st_ino)` as file identity: detect a replaced DB, a rotated log | Works on NTFS; on ReFS and some network drives `st_ino` can be 0 or unstable. Guard with a fallback to path + mtime. | S |
| L7 | `_vendor/sqlite_store/filesystem.py:19-45` | Refuses NFS/CIFS/FUSE for SQLite; reads `/proc/mounts` on Linux, else `is_mount()` of parents | On Windows falls to the `unknown` branch (`is_mount` over parents, anchor excluded). Likely harmless; a mapped network drive is not detected, so WAL over SMB would be allowed. Add a `GetDriveType` check. | S |
| L8 | `os.replace` over an open file: `src/taskloop/stores/call_state.py:53,69`, `adapters/storm.py:53`, `contracts/factorybackup.py:61,104`, `taskloop_dash/serve.py:67`, `_vendor/atomic_io`, `_vendor/jsonl_log/_rewrite.py` | tmp + `os.replace` as the atomic write | On Windows `os.replace` raises `PermissionError` if the target is open by another process without `FILE_SHARE_DELETE` (the dashboard reading a state file while the engine replaces it; antivirus scanning). POSIX lets the reader keep the old inode. Needs a bounded retry in atomic_io and a rule that readers open with share-delete (Python's `open` does not set `FILE_SHARE_DELETE`). This is the quietest Windows bug in the tree: it appears under load, not in a unit test. | M |
| L9 | `_vendor/jsonl_log/__init__.py:249` (`st_ino` of path vs `fstat(fd)`), `_append.py:13` (`O_APPEND`, `0o666`) | Detect a rotated log; atomic multi-writer append by one `write` on `O_APPEND` | `O_APPEND` single-write atomicity across processes is not guaranteed on Windows (no POSIX guarantee; in practice small writes are serialized by the kernel but not documented). Rotation by rename of an open file fails (L8). Needs a per-file lock or one-writer rule on Windows. | M |
| L10 | SQLite (`sqlite_store`, `factory.db`) | WAL, `BEGIN IMMEDIATE` | SQLite itself is cross-platform and supports WAL on local NTFS. No change expected; WAL needs shared memory in the same host (fine). | S (verify) |

## 3. Paths and files

| # | Where | What | Windows equivalent / design choice | Size |
|---|---|---|---|---|
| F1 | `_vendor/app_dirs/__init__.py:4-70`; `src/taskloop/adapters/ident.py:15`; `src/delegate/app/env.py:43` | `~/.config/<app>`, `~/.local/state`, `~/.cache`, header says "POSIX only" | Decision: keep `~/.config/task-loop` on Windows (`%USERPROFILE%\.config\task-loop`, simplest; this is also where Claude Code itself keeps `.claude`) or `%APPDATA%`/`%LOCALAPPDATA%`. Recommend keep the XDG layout: one path in docs, shims and tests. Add `USERPROFILE` fallback: `Path.home()` already does that. | S |
| F2 | `"HOME"` env: `src/taskloop/adapters/gitmemo.py:26`; `dev/runtests.py:58` | `env.get("HOME")` | Windows sets `USERPROFILE`, not `HOME` (git-bash sets `HOME`). `Path.home()`/`expanduser` are fine; the explicit `HOME` reads are not. | S |
| F3 | `src/taskloop/adapters/gitmemo.py:34-36` | Reads `/etc/gitconfig`, `/opt/homebrew/etc/gitconfig`, `/usr/local/etc/gitconfig` | Windows: `C:\Program Files\Git\etc\gitconfig` (system) and `%PROGRAMDATA%\Git\config`. Better: ask `git config --show-origin --list --system` once. | S |
| F4 | `_vendor/git_porcelain/testing.py:38,66`, `history.py:129,263` | `core.hooksPath=/dev/null`, `GIT_CONFIG_GLOBAL=/dev/null` | Git for Windows accepts `/dev/null` (MSYS translates it to `NUL`) when git is called from Python? Not tested; native Win32 git handles `/dev/null` specially in config paths in recent versions. Use `os.devnull` to be safe. | S |
| F5 | `src/delegate/adapters/harness/opencode_sandbox.py:44,122-123` | `/private/tmp`, `/private/var/folders`, `/tmp`, `/var/folders` allow-lists | macOS-only (see H5). No `/tmp` literal is used by the engine itself outside this file (grep for `/tmp`, `/private`, `/var/` in `src dev hooks skills` finds only this and tests). Scratch dirs come from `tempfile`. | S |
| F6 | `_vendor/git_porcelain/real_cache.py:124-133`, `src/taskloop/adapters/treehash.py:33` | Tree hash includes symlink text (`os.readlink`), mode, `st_ino` | Git for Windows defaults `core.symlinks=false` (symlinks become small text files) and `core.filemode=false`: the tree hash of a checkout then differs from a Mac checkout of the same commit. Anything comparing a hash across hosts (the RunKey receipt, executor vs engine; one-receipt-plan) breaks silently. Decision: hash `git ls-tree` output (committed content) instead of the working-tree walk. | M |
| F7 | `src/taskloop/hook/prepush.py:80` | `path.stat().st_mode & 0o111` to ask whether a hook is executable | Windows `st_mode` has no execute bits (always 0o666-ish); git for Windows decides hook execution by the shebang, not the bit. Always true on Windows. | S |
| F8 | `_vendor/atomic_io/__init__.py:42,84-88`, `_vendor/process_lock/__init__.py:185` (mode `0o600`), `src/delegate/contracts/stores.py:54`, `src/delegate/app/env.py:62`, `adapters/harness/opencode.py:369` | `fchmod`, `os.umask`, `chmod 0o600/0o700` for "private to the user" | `os.fchmod` does not exist on Windows (AttributeError). `chmod` only toggles read-only. Privacy comes from the profile ACL (the user profile is already private). Guard `fchmod`/`umask` calls with `hasattr`; accept that "0o600" is a no-op. | S |
| F9 | `src/delegate/adapters/harness/codex_overlay.py:21-26` | `symlink_to` for the Codex home overlay (`auth.json` and dirs) | Needs symlink privilege. Alternatives: copy (breaks "never credential contents": copies a secret), `CODEX_HOME` pointed at the real home with a rules file only, or junctions for directories (`mklink /J` needs no privilege) plus a hard link for the file (same volume). Design choice. | M |
| F10 | `src/taskloop/app/artifacts/rules.py:57-86`, `adapters/looks.py:142-157`, `taskloop_dash/api/artifacts.py:54-104` | Refuse symlinks in artifacts | Works as a rule, but Windows has junctions and reparse points that `is_symlink()` reports false for (Python 3.12+: `is_junction()`). Add `is_junction()` to the same checks. | S |
| F11 | `packages/kernel/src/tlkernel/ids.py:118` | repo key = folder name + 8 hex of sha1 of the real path | The same folder can be spelled with different case or drive-letter case on Windows, giving two keys for one checkout. Case-fold the path before hashing (not tested). Also keys differ across machines, which is fine (per machine). | S |
| F12 | Path separators | Grep `as_posix`, `split("/")`, `startswith("/")`, `PurePosix`, `"/".join` hits 33 lines in `src`/`skills` | Most are inside git output parsing (git prints `/`), which is correct. Each needs a read; none was found wrong in this pass. Not tested. | M |
| F13 | Long paths | Slot worktrees at `<root>/<repo>/<slot>` plus `.git`, node/Unity trees | 260-char `MAX_PATH` still bites tools (not Python 3.6+ with the manifest). Enable `LongPathsEnabled` and `git config core.longpaths true`; note in setup. | S |
| F14 | Line endings in hashed files | `MANIFEST.sha256` (`app/release/manifest.py:9`) hashes `read_bytes()` of working-tree files; `dev/vendor.py:48`, `dev/vendor.json` hashes vendored copies; `.agents/skills/...` are listed. No `.gitattributes` exists. | With `core.autocrlf=true` (the Git for Windows default) a checkout holds CRLF, every hash differs from the one committed on the Mac, and `tl doctor` reports every file "differs". Fix: a `.gitattributes` with `* text=auto eol=lf` (or `-text`), plus hash `git show :path`/`git cat-file` blobs instead of the working copy. Also the SHIM text is written with `\n` (fine). | S |
| F15 | Text encoding | Many `read_text(encoding="utf-8")`; some `write_text(...)` without `newline=` | Python on Windows translates `\n` to `\r\n` on text writes unless `newline=""`. Files that are hashed, diffed or parsed as lines (shims, JSONL, golden files in `tests/`) must be written with `newline="\n"`/bytes. `src/taskloop/adapters/procs.py:43` already normalizes `\r\n` on read. Count: 238 file read/write sites in `src dev hooks`; none audited one by one. | M |
| F16 | `src/taskloop/app/launch/loop.py:65`, `dev/dash_check.py:144` | `shutil.disk_usage(...)` | Works on Windows. | S (ok) |
| F17 | `dev/runtests.py:42` | `os.sysconf("SC_PAGE_SIZE")` for RAM | `os.sysconf` is missing on Windows; use `GlobalMemoryStatusEx` via ctypes. Same for `adapters/ram.py` (macOS `vm_stat`, Linux cgroup) and `app/launch/loop.py:69-72` (`/usr/bin/vm_stat`, returns None when not Darwin: safe, but then free RAM is unknown on Linux/Windows). | S |

## 4. Hooks and shell

| # | Where | What | Windows equivalent / design choice | Size |
|---|---|---|---|---|
| H1 | `src/taskloop/app/doctor/install.py:20-45` (`SHIM`, `RESOLVING_SHIM`) and `app/wire/setup.py:45-59`, `app/doctor/setup_checks.py` | The `tl` shim is a `#!/bin/sh` script: `command -v uv`, a glob over the plugin cache, integer arithmetic to pick the newest version, `exec uv run --quiet --script` | Windows cannot run it from cmd/PowerShell. Options: (a) a `tl.cmd`/`tl.ps1` pair doing the same pick (PowerShell: `Get-ChildItem`, `[version]` compare, no `exec`: `& uv run ...; exit $LASTEXITCODE`); (b) a tiny Python launcher (`tl.py` is already PEP 723; `uv run --script` on a path). Recommend (b) plus a one-line `.cmd` wrapper: the newest-version logic then exists once, in Python, and is testable on the Mac. `setup_checks.py` parses the shim with `shlex.split` and checks `RESOLVING_MARK`; it needs the new format. "PATH tl" links the shim by symlink (`setup.py:59`): use a copy or a `.cmd` on PATH instead. | M |
| H2 | `hooks/hooks.json` | SessionStart/PreCompact: `uv run --quiet --script "${CLAUDE_PLUGIN_ROOT}/hooks/hook.py"`; PreToolUse: `python3 "...hook.py" pretool` | `python3` on Windows is usually the Microsoft Store stub (prints "Python was not found" and exits 9009), so the PreToolUse guard (which refuses `pkill`/`killall`) silently stops running. Use `uv run --script` for all three, or `py -3`. The pretool hook stays stdlib-only by contract (`.importlinter`), so it can run under any `python`. Quoting of `${CLAUDE_PLUGIN_ROOT}` depends on which shell Claude Code uses on Windows (Git Bash); not tested. | S |
| H3 | `hooks/hook.py:1`, `dev/*.py`, `tl.py:1`, `src/delegate/entry.py:1`, `src/taskloop/adapters/markers.py:1` | `#!/usr/bin/env -S uv run --script` shebangs | Windows ignores shebangs; `-S` is GNU-env only. The `py` launcher reads `#!` lines for `python` only. Every direct execution (`./dev/release.py`) becomes `uv run --script dev/release.py`; docs in `CLAUDE.md` already say that for release. `tl.py:74` already tells a plain `python3` user to go through uv. | S |
| H4 | `src/taskloop/hook/prepush.py:30-80`, `adapters/childenv.py:47-54`, `app/doctor/install.py` (`githooks/<name>` files) | tl sets `core.hooksPath` to `~/.config/task-loop/githooks`, whose files are launcher scripts (`HOOK_NAMES`) that call `tl`; chained hook of the repo (`prepush.py:55-74`) and `git lfs pre-push` | Git for Windows runs hooks through its bundled `sh.exe`, so a `#!/bin/sh` hook file works there, provided the file has LF endings (F14) and git is found. That makes the hooks the easiest piece: keep sh, call `tl` through the `.cmd`. Needs a test on a real Git for Windows. `prepush.py` is stdlib python by contract and runs `["git", "config", ...]` and the tl command with `subprocess` (no shell): fine. | S |
| H5 | `src/delegate/adapters/harness/opencode_sandbox.py:1-160`, `opencode.py:103`, `app/onboard.py:35-51` | OpenCode worker commands run under macOS `sandbox-exec` with a generated `#!/bin/sh` + `/bin/zsh` shell | Already gated by `sys.platform == "darwin"`, so OpenCode lanes are off elsewhere. Windows has no equal for a per-command sandbox (AppContainer / Job Object limits are far weaker, no path-level deny). Decision: no OpenCode lane on Windows, or a different containment (see section 7, decision D5). | L (or skip) |
| H6 | `src/delegate/domain/policy/shell.py`, `matchers.py:20` (`SHELLS = {sh,bash,zsh,dash}`), `exec_allow.py`, `src/taskloop/domain/lanes/matchers.py:104-115` (`/bin/zsh -lc`), `src/taskloop/hook/rules.py:5-46`, `domain/beads/matchers.py:119`, `domain/checks/lint.py:46` | Command policies parse worker shell commands with `shlex` (POSIX quoting), allow-list `cat head tail ls grep find sed echo which true`, treat `sh -c` payloads | If workers run in cmd/PowerShell on Windows, `shlex.split` mis-parses `\` paths (backslash is an escape) and none of the allow-listed names exist as commands. Two designs: run workers' shells as Git Bash (policies keep working; paths must be given in `/c/...` or `C:/...` form), or write a PowerShell grammar (large). Claude Code on Windows itself uses Git Bash for its Bash tool, which supports the first. The policies decide what a worker may do, so a parse error here is a safety hole, not a crash. | L |
| H7 | `src/delegate/app/codex_policy.py:46-47` | Codex guard shim = `[sys.executable, ENTRY, "guard", ...]` | Portable (python executable + script). OK once P11 is fixed. | S |
| H8 | `src/taskloop/hook/rules.py:9` | `KILLERS = {pkill, killall}` | On Windows the bad commands are `taskkill /IM`, `Stop-Process -Name`, `wmic process ... delete`. Add them or the rule gives no protection. | S |

## 5. External tools

| # | Where | What | Windows status | Size |
|---|---|---|---|---|
| X1 | `justfile:28-70` | Recipes use `#!/usr/bin/env bash`, `set -euo pipefail`, `xargs`, `grep`, `sort -u`, `$(just changed)`, `HOME` | `just` runs on Windows but needs `set shell := ["bash","-c"]` (Git Bash) for these; `xargs`, `grep`, `sort` come from Git for Windows' `usr/bin` only when on PATH. Cheapest fix: move the logic in `lint`, `types`, `changed`, `rules` into one `dev/check.py` and keep the recipes one-liners (`uv run python dev/check.py lint`). `test` already is `uv run python dev/runtests.py`. | M |
| X2 | `justfile:22-23` `tools`, `mise.toml` | `MISE_IGNORED_CONFIG_PATHS=$HOME/...`; mise pins `aqua:gastownhall/beads`, `just`, `prek`, `uv`, `ruff`, `pyrefly`, `import-linter` | mise supports Windows; `aqua:` backend and `pipx:` need checking per tool: `bd` (beads) must publish a Windows build, which also matters at runtime: `adapters/bd.py` shells out to `bd`. Not tested. `mise.lock` has per-platform entries; Windows entries must be added. | M |
| X3 | `bd` (beads, Dolt) | Task store behind `adapters/bd.py` | Beads ships Windows binaries? unknown here; Dolt does. Blocking if not. Check before any Windows work: `bd --version` on a Windows box. | M (unknown) |
| X4 | `uv` | `uv run --script` is the only launcher (PEP 723) | Fully supported on Windows. Python 3.15+ (CLAUDE.md) installs via uv. `skills/task-loop/tl.py:6` says "macOS, Linux" in its docstring. | S |
| X5 | `git` | Worktrees, `git push` to bare repos, `GIT_CONFIG_COUNT` env config (`childenv.py:47`), pre-push | Git for Windows supports all of it. Worktree paths: long paths (F13), case-insensitive names, no `:` in branch-derived directory names. Branch names like `claude/cool-kilby-7289c4` contain `/`; if any code builds a directory name from a branch, check for illegal characters (`< > : " \| ? *`). Not tested. | S |
| X6 | `ssh` (WINEXEC) | `topology.md` plans git push over ssh to an executor | Windows 10+/Server ship OpenSSH client and server; default shell of the server is cmd, set to PowerShell or Git Bash for sane quoting. Quoting argv through ssh into cmd/PowerShell is its own project (ARG quoting rules differ). Executor protocol should send argv as JSON and have a small agent rebuild it with `subprocess.list2cmdline`. | M |
| X7 | `caffeinate`, `vm_stat`, `sips` (`adapters/looks.py:166`), `sandbox-exec`, `libproc`, `Library/Keychains` | macOS tools | All gated or optional except libproc (P3) and sandbox (H5). `sips` falls back to ImageMagick or a plain copy. | S |
| X8 | `claude`, `codex`, `opencode` CLIs | Workers run through delegate harnesses; `shutil.which("opencode")`, `~/.opencode/bin/opencode` | Claude Code and Codex CLIs run on Windows (Codex Windows support is experimental/WSL-first: check). `shutil.which` handles `.exe`/`.cmd` through PATHEXT, but `subprocess` argv with a `.cmd` file needs `shell=True` or the explicit `cmd /c` (Python 3.12+ batch-file quoting caveat). npm-installed CLIs are `.cmd` shims. | M |
| X9 | `Unity` batch mode (`adapters/looks.py:15`) | `Unity -batchmode ...` | Native on Windows: this is the reason for the whole effort. | S |

## 6. Tests

Counts from grep over `tests/` (3,123 lines match any of: tmp paths, signal, fork, fcntl, /proc, symlink, chmod, bash). Not a list of failures, a measure of exposure.

| # | What | Evidence | Windows impact | Size |
|---|---|---|---|---|
| T1 | Files using `symlink_to`, `os.kill`, `killpg`, `fcntl`, `start_new_session`, `/bin/sh`, `sh -c`, `#!/bin` | 76 files in `tests/` | Each needs `skipif(sys.platform == "win32")` or a rewrite. Skips hide the gap; a rewrite per primitive (kill tree, lock, symlink) is the real work. | L |
| T2 | `procsim` guard (`tests/support/procsim.py`): "a logic test that spawns, forks or runs real git fails" | CLAUDE.md "Build & Test" | The guard itself is Python-level; should port. Real tests (`tests/*/real/`, `@real_proc`, `@real_git`, `tests/delegate`) spawn real shells and processes. | M |
| T3 | `tests/rules` (gate rules, 400-SLOC caps, `import re` placement) | Pure source scans | Portable; they read files with `\n` assumptions: set `.gitattributes` (F14). | S |
| T4 | `dev/runtests.py:42,58,73` (RAM from `sysconf`, `~/.gitconfig` copy, SIGTERM trap) and `dev/affected.py` (diff against `origin/main` and import graph) | Runner for `just test` | `affected.py` is pure Python + git; runtests needs P5 and F17. | S |
| T5 | `dev/race.py:95,120-125,156,200,255` | Writes `#!/bin/sh` fake `bd`/`claude`, `chmod 755`, `core.hooksPath` | A real-process race harness; needs fake executables as `.cmd`/python scripts. Low priority (a dev tool). | M |
| T6 | `tests/live`, `tests/e2e` (selftest, release) | Real git remote, real processes, real tl and dashboard; `dev/release.py` | Run by a person; Windows release path is the same code as P/L/H items. | M |
| T7 | `tests/delegate` | the delegate-tests switch on, minutes, real worker processes | Only after P7. | M |
| T8 | Golden files and fixtures with `\n` | `tests/fixtures`, `tests/run/test_exchanges.py` golden `input.txt` | Compare bytes: CRLF checkout breaks them (F14). | S |
| T9 | tl-6vb (Linux suite: 6 failures, 8 errors on the container run, 2026-10-27) | Bead text | The same fixes (macOS-assuming tests) shorten the Windows list. Do tl-6vb first: it separates "test assumes macOS" from "code is POSIX". | M |

---

## 7. Results

### (1) The 10 biggest blockers, ranked

Rank = how much of the system stops working, then size.

| Rank | Blocker | Items | Why it ranks here | Size |
|---|---|---|---|---|
| 1 | Tree kill and process groups: no Job Object backend; `stop_tree`, `start_new_session`, `getpgid`, `killpg` | P1 P2 P12 | Every worker, check and test run is spawned and stopped through it. Without it a stopped bead leaves a running worker editing the tree. | L |
| 2 | Process table and pid liveness: no Windows backend; `os.kill(pid, 0)` would kill instead of probe | P3 P4 | Pid reuse protection, orphan reaping, `tl stop`, lease holder checks. Failure is silent (no table = nothing stopped). | L |
| 3 | `flock` foundation: `process_lock` and everything standing on it | L1 L2 L5 | Land lock, slot leases, writer guards, check resources. Import error at module load, so the engine does not start. | L |
| 4 | Stop channel: SIGTERM is the engine's only stop signal, handlers in ~12 places, `SIGHUP` absent | P5 P6 P7 | `tl stop --now`, owner stop, delegate supervision. The file channel exists but is step-boundary only. | M-L |
| 4b | Pipe I/O: `select` on pipe fds and `set_blocking` in the worker output path | P14 | No worker output without it; ranks with P1 as part of the same backend (WIN-PROC). | M-L |
| 5 | `import fcntl` at module scope in the outcome line (`outcome_line.py:2`) and in `quarantine.py`, `leases.py`, `process_lock` | P10 L1 L5 | A hard ImportError: `tl run-task` cannot even import. Cheap to fix once, so it hides behind rank 3 but must come first to run anything. | S |
| 6 | The `tl` shim and hooks launcher: `#!/bin/sh`, shebangs, `python3` in hooks.json | H1 H2 H3 | Nothing can be invoked: no `tl` on PATH, the PreToolUse guard silently off. | M |
| 7 | Atomic replace and append with open files: `os.replace` fails when another process holds the file | L8 L9 | The dashboard reads what the engine replaces all day; intermittent `PermissionError`, found only under load. Review (section 8) rates it the highest-risk item: fixing it needs a `CreateFileW` wrapper with `FILE_SHARE_DELETE` behind `atomic_io`, plus a retry. | M-L |
| 8 | Worker command policy and sandbox: `shlex`/POSIX shell grammar and macOS `sandbox-exec` | H5 H6 H8 | Decides what a worker may run. Wrong on Windows = unsafe or useless; needs the Git Bash decision (D3). | L |
| 9 | Hash identity across OSes: CRLF checkouts, `core.symlinks=false`, filemode | F6 F14 F15 | MANIFEST, tree hash/RunKey receipt differ on Windows for the same commit: gate receipts and `tl doctor` fail or lie. | M |
| 10 | Symlinks as design: factory pid index, Codex overlay, PATH link, tests | P8 F9 F10 H1 T1 | Needs privilege or Developer Mode; replace with files and junctions. | M |

Not on the list because they are small or unknown: `bd`/Dolt Windows availability (X3, unknown, could jump to rank 1 if no Windows build exists), RAM and `HOME` reads, `/dev/null`, justfile bash recipes.

### (2) What can be done now without affecting the current refactors

Everything here keeps behavior identical on macOS and Linux; each is a small PR, none moves code the refactors are rewriting. Check the lanes (`lane-reliability`, `lane-gate-speed`, `lane-engine-state`) for touching the same files before picking one.

| Do now | Items | Size | Note |
|---|---|---|---|
| `.gitattributes`: `* text=auto eol=lf` (or `-text` for `MANIFEST.sha256`, golden files, shims) | F14 T3 T8 | S | Zero risk, prevents the CRLF class forever. |
| Guard POSIX-only calls with `hasattr`/import-in-function so modules import everywhere: `track/outcome_line.py` fcntl, `fchmod`, `umask`, `SIGHUP`, `preexec_fn`, `posix_spawnp`, `sysconf` | P10 P11 P13 F8 F17 P5 | S each | Makes `import` succeed; behavior unchanged on POSIX. Add a rules test: "importing every module on a fake `win32` platform raises nothing" (monkeypatch `fcntl` out of `sys.modules`). That test is the cheapest regression fence for the whole effort. |
| Replace the factory symlink with a pid file | P8 | S | Self-contained in `app/launch/factory.py` and `app/loop/exits.py`. Touches the engine-state lane: ask first. |
| `hooks.json` PreToolUse via `uv run --script` | H2 | S | Also makes the hook uniform. Release-gated change (hook version rule in CLAUDE.md). |
| Move `justfile` shell logic into `dev/check.py` | X1 | M | Pure dev tooling; no engine impact. |
| Hash committed blobs (not working-tree files) for MANIFEST and tree identity | F6 F14 | M | Touches the receipt code that ONE-RECEIPT just landed: ask its owner. |
| Do tl-6vb (Linux suite green): shrinks T9 and exposes code that is POSIX-but-not-macOS | T9 | M | Already planned. |
| Write the backend interfaces as Protocols with the POSIX implementation unchanged: `ProcessTable`, `TreeKiller`, `FileLock`, `StopChannel` | P1 P3 L1 P6 | M | Design work in the shelf repo (`yoselabs/shelf`: process-lock, stream-proc) with no behavior change; this is the "design note with the backends list" that tl-w7lt.38.13 asks for. Wait for the shelf-factory session. |
| Add `win32` branches that raise a clear `NotImplementedError("WINENGINE: see tl-w7lt.38.13")` at the entry of `tl` | none | S | A loud failure instead of an ImportError traceback. |
| Check `bd` and Dolt release assets for Windows (a 5-minute lookup, no code) | X3 | S | If absent, nothing else matters yet. |
| Remove the false "Windows, macOS, Linux, Docker" claim in `src/delegate/cli/parser.py:13`; fix `tl.py:6` docstring | docs | S | Truthful docs. |

Do not do now: any Job Object code, any ctypes Windows backend, new shims, the Codex overlay redesign. They need the design decisions below and would collide with the shelf extraction.

### (3) Decisions Denis must make

Already decided and recorded (`docs/design/topology.md`, "Windows and Unity" and "Mirrored executor layout", 2026-11-05): the engine runs natively on Windows ("not a discussion"); Linux executor first, Windows executor second, native Windows engine third. Denis's later instruction (section 0) adds: macOS, Linux, WSL and Windows all native at once. So "native vs WSL vs OpenSSH" is not a choice: all four are required platforms, and OpenSSH is only the transport to a remote executor (WINEXEC). What is left:

| # | Decision | Options | Recommendation | Why |
|---|---|---|---|---|
| D1 | Order: WINEXEC (tl-w7lt.38.12) before WINENGINE (tl-w7lt.38.13), as the beads say, or the reverse | A) executor first; B) engine first | A, with one correction: WINEXEC also needs P1-P4 on the executor side (it spawns and kills Unity), so the process backends are shared work. Do them once in shelf and both beads consume them. | The process and lock backends are not specific to either bead. |
| D2 | Process tree backend | A) Job Objects via ctypes in stream_proc, stdlib only; B) add `psutil` | A for kill and group (Job Objects are the right primitive and psutil does not wrap them); allow `psutil` or ctypes for the process table only. | Keeps the vendored packages stdlib-only, as now. |
| D3 | Shell for workers and policies on Windows | A) Git Bash everywhere (Claude Code itself does this; `shlex` policies keep working); B) PowerShell support | A. | B means a second command grammar for every safety rule (H6); an error there is a security hole. |
| D4 | Stop semantics: is a "grace" period still promised on Windows? | A) hard kill via Job Object, grace only for processes that accept `CTRL_BREAK`; B) engine-level cooperative stop (stop flag file/event) first, hard kill after N seconds | B: the engine already has a stop flag; use it for the grace and `TerminateJobObject` as the SIGKILL. Change `delegate-api.md` report fields (`term_sent`, `kill_sent`) to say "graceful requested" / "forced". | Honest contract, no fake SIGTERM. |
| D5 | OpenCode lane and its macOS sandbox. This is already an exception to the four-platform rule: it works on macOS only, today | A) record "OpenCode is macOS-only" as the one named exception; B) contain it per platform (Linux/WSL: bubblewrap or Landlock; Windows: nothing at that strength) | A for now, written down as an exception with its bead. B for Linux/WSL later if OpenCode is wanted there. | No per-command sandbox on Windows matches `sandbox-exec`; shipping a weaker one under the same name misleads. |
| D10 | One PC with both WSL and Windows | **Decided (Denis 2026-11-05): two factories, WSL is a separate machine.** "One factory per machine" in `topology.md` now reads: per OS environment. | Done. | Unity must run natively, so the whole engine runs natively on Windows; WSL runs its own factory when wanted. |
| D11 | Which hosts the gate runs on before a release | A) macOS only (today); B) macOS + Linux container (tl-6vb); C) all four | B now, C once a Windows runner exists. Make the contract tests (lock, tree kill, process table, atomic write, shim) the cross-platform set; the full suite stays on the reference host. | No hosted CI; each added host costs a box and minutes per release. |
| D6 | State location | A) keep `~/.config/task-loop` (`%USERPROFILE%\.config\task-loop`); B) `%APPDATA%` / `%LOCALAPPDATA%` | A. | One path in docs, shims, tests; Claude Code uses `%USERPROFILE%\.claude`. |
| D7 | Symlink policy | A) never create symlinks (files and junctions instead); B) require Developer Mode | A. | Zero setup, same behavior on every OS. |
| D8 | Test policy | A) a Windows runner (a real box) for `tests/*/real`; B) skip-marks only | A, but only a small set: lock, tree kill, shim, hooks, atomic write. A skip-mark without a Windows run is a green that tests nothing. | The lifesim box is the only Windows machine; use it once WINEXEC works. |
| D9 | Python and tool floor | Python 3.15+ per CLAUDE.md; `uv`, `git`, `just`, `bd` required | Confirm `bd` and `just` have Windows builds (X2, X3) before committing to D1. | A missing `bd` build blocks everything. |

### Suggested bead set (for tl-w7lt.38.13 "design note with the backends list and tests per backend")

1. WIN-LOCK: `FileLock` backend (L1, L2, L5), tests: two processes, kill -9 releases, same-process reentry.
2. WIN-PROC: `ProcessTable` + `TreeKiller` (P1-P4, P12, P13), tests: spawn tree, kill, pid reuse, orphan reap.
3. WIN-STOP: `StopChannel` and handler policy (P5-P7), tests: `tl stop --now`, delegate supervise.
4. WIN-FILES: atomic replace/append rules (L8, L9, L3, L4), symlink-free pid index (P8), `.gitattributes` and blob hashing (F6, F14).
5. WIN-SHIM: `tl` launcher, hooks.json, githooks, setup/doctor (H1-H4).
6. WIN-DEV: justfile into Python, mise/bd/just Windows (X1-X3), RAM and HOME reads (F2, F3, F17).
7. WIN-TESTS: the import fence, skip policy, a Windows runner (T1-T9).
8. WIN-POLICY: Git Bash decision applied to delegate policies, kill-command rules (H6, H8, D3).

## Method and limits

- Greps over `src/`, `dev/`, `hooks/`, `skills/task-loop/`, `justfile`, `mise.toml` for: fcntl/flock, fork, signal, kill/killpg/setsid, `/proc`, ps/pgrep, sh/bash/zsh, `/tmp` and `/private`, symlink/readlink/link, chmod/umask/st_mode/st_ino, caffeinate/sandbox-exec/vm_stat, shebangs, `HOME`, newline handling; a few files read in full (`hook.py` shims, `procfs.py`, `proctable.py`, `process_lock`, `factory.py`).
- No file was run on Windows; Windows behavior is stated from the documented API behavior and marked "not tested" where it matters. Items worth a 10-minute Windows check first: `os.kill(pid, 0)` behavior (P4), `/dev/null` in git config (F4), Git Bash hook execution (H4), `bd` build (X3).
- `src/taskloop/adapters/landlock.py` is the repo land lock (name misleads; it is not the Linux Landlock sandbox).
- Review by an Opus subagent (section 8) and 4 web lookups added P14 and the topology comparison; the subagent ran nothing on Windows either.
- Not covered: the dashboard's HTTP binding (Tailscale address in `taskloop_dash/bind.py`) beyond file identity, `docs/contracts`, GitHub-hosted anything. No `AF_UNIX`, `mkfifo`, `pty` or `termios` use was found. The first draft said "no hidden IPC"; that missed `select` on pipe fds (P14).

---

## 8. Does Unity-native require engine-native? Three topologies

Denis's chain: Unity must run natively, so the whole engine runs natively on Windows. The arrow is tested here against the code and a few lookups. Facts first (web, 2026-11-05; mostly forum and tracker posts, not vendor docs):

| Fact | Result | Source quality |
|---|---|---|
| Kill a WSL-launched Windows `.exe` from the Linux side | The Linux pid is a proxy; killing it does not stop the Windows process; only `taskkill.exe` with the Windows pid does | One user report (microsoft/WSL#8056) plus WSL interop docs |
| Unity on a project created or cloned through WSL | A project cloned by WSL git into the Windows filesystem failed to open for one user; `\\wsl$` and `/mnt/c` access is far slower than native | microsoft/WSL#3356, #1047; no Unity doc found |
| `flock` on `/mnt/c` (9p/drvfs) | not found, untested | none |
| Codex CLI native Windows | native sandbox exists (restricted tokens, ACLs); still labelled experimental by a 2026 guide | third-party guides, not OpenAI docs |
| `bd` (beads) and `just` Windows builds | `bd` v1.3.4 has `windows_amd64` and `windows_arm64`; `just` 1.59 has Windows zips | GitHub release assets (checked with `gh`) |

| Topology | What it is | Cost (this audit) | Verdict |
|---|---|---|---|
| A. Native Windows engine | Everything runs on Windows | Sections 1-6: about 8 L items plus the pipe layer, a red Linux suite, no Windows host in any gate | ✅ required end state (Denis); ❌ as the first step: weeks before one Unity run |
| B. Engine in WSL, `Unity.exe` through interop | Engine stays Linux code | Path translation, project must live on `C:\` (slow from WSL) or on WSL (Unity trouble); a stopped bead leaves Unity running (proxy pid) | ❌ refuted by the kill fact; the lease and stop model break |
| C. Engine on Mac/Linux/WSL, thin Windows executor over OpenSSH | `topology.md` WINEXEC | Spawn + Job Object kill + pipe reader + liveness + a lease/pid file on the Windows side; no engine port | ✅ smallest Windows surface; untested; does not meet "engine native on Windows" alone |

Conclusion: the arrow "Unity native, so engine native" is not forced by the code, because C runs Unity natively without a native engine. It is forced by Denis's requirement that every platform runs the engine (section 0) and by "some people don't have Linux or Mac". So: C is the first deliverable (it is WINEXEC, bead tl-w7lt.38.12), A is the commitment (WINENGINE, tl-w7lt.38.13), and the primitives are built once in shelf for both. This agrees with D1. Do not call the requirement met until A passes the contract tests on a real Windows box.

Review notes (Opus subagent, nothing run on Windows; each claim is from API knowledge):
- Run the Windows engine and every worker inside one Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`: a kill is closing the handle, and an engine that dies takes its workers with it, which matches the "kernel drops the lock" model on POSIX. Unity spawns shader compilers and import workers; a job catches them. Nested jobs need Windows 8+.
- `msvcrt.locking` is a poor lock: per handle, no shared mode. Use `LockFileEx` via ctypes. After a kill the next `LockFileEx` may fail briefly: the backend needs a short retry.
- The seam plan is sound, with two more seams: `PipeReader` (P14) and `AtomicFile` (L8). It only works if built test-first on a real Windows box, because the contract tests have no hosts today.
- `psutil` for `ProcessTable` only is cheaper than a ctypes snapshot backend (one maintained dependency replaces procfs, procmac and the libproc ctypes), at the cost of the stdlib-only vendored rule; it gives no Job Objects or pipe reader. A Rust/Go helper binary is the fallback if ctypes proves flaky, not the first move.
- `os.kill` has only 4 call sites in `src` and `_vendor`: P4 is small and greppable, fence it with a test. F14 (CRLF) is a one-file fix and belongs in "do now", not in the top 10 beside real blockers.
- On WSL keep state and checkouts on the Linux filesystem as a hard rule, and add `9p` and `drvfs` to the SQLite refusal list (W1).
- Hook execution of `#!/bin/sh` (H4) needs the Git for Windows build of git; a WSL git over a Windows repo differs.

New decision for Denis:

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D12 | `psutil` for the process table on Windows (and later all platforms) | A) add the dependency; B) ctypes `CreateToolhelp32Snapshot` backend, stdlib only | A for ProcessTable only: it removes procmac and procfs maintenance; keep Job Objects and the pipe reader in ctypes. Untested. |

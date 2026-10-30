# Capturing a runaway or orphaned process before killing it

Read the state first: a kill destroys the evidence. Everything below reads /proc, so it needs no `ps`. `<pid>` is the suspect.

1. Identity and state:
   `cat /proc/<pid>/status` (State, VmRSS, VmPeak, Threads, PPid), `tr '\0' ' ' < /proc/<pid>/cmdline`, `readlink /proc/<pid>/cwd`.
2. What it is doing: `cat /proc/<pid>/wchan` (the kernel function it waits in, `0` when running) and `cat /proc/<pid>/stack`
   (may need root). Per thread: `/proc/<pid>/task/<tid>/{comm,wchan,status}`; a thread in state R with no wchan is spinning.
3. Memory: `cat /proc/<pid>/smaps_rollup` (Rss, Pss, Anonymous), `cat /proc/<pid>/limits` (Max address space).
   Take smaps_rollup twice, 5 s apart: the difference is the growth rate.
4. Python stacks: `py-spy dump --pid <pid>`. py-spy is NOT installed by default (`uv tool install py-spy`); it may also need ptrace
   rights (`kernel.yama.ptrace_scope`). Without it, the thread list from step 2 is what you get.
5. The parent chain: follow `PPid` from `/proc/<pid>/status` upward until pid 1. A PPid of 1 means it was orphaned.
   Note which test shard, release run or slot started it (cmdline of each parent).
6. The cgroup: `cat /proc/<pid>/cgroup` gives `0::/path`; then read `/sys/fs/cgroup/<path>/memory.current` and `memory.max`.
   Inside a container /proc/meminfo shows the HOST's memory, so `memory.max` is the real limit (suite.available_mb reads it).
7. Save it all to a file (a loop over the files above into `$TMPDIR/runaway-<pid>.txt`) before going on.
8. Only then kill, and only a PID you spawned or confirmed: re-read `/proc/<pid>/cmdline` right before `kill <pid>`,
   SIGTERM first, SIGKILL after a wait. Never `pkill`, `killall` or kill by pattern: the pattern also matches other people's
   runs and other sessions' shards.

## Known mechanism

A test that does `mock.patch.object(time, "sleep")` replaces `time.sleep` for every thread in the process. A second thread
that loops on `time.sleep(...)` then spins at full speed, and the MagicMock records every call and argument, so RSS grows by about
110 MB/s until the shard hits its memory cap (GB-sized shards). Fix: patch only the calling thread
(`tests/support/engine_case.no_sleep_here`) or a sleep seam; `tests/rules/test_no_global_sleep_patch.py` fails on the global patch.
The full analysis is the RCA at `~/Workspaces/handoff/rca-shards-2026-10-28.md`.

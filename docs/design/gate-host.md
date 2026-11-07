# Gate host: capping .NET load on the Mac, and running the non-Unity gate steps on the devbox

Status: design, 2026-11-02. Nothing here is built. Written read-only: nothing was run (no tl, just, uv, pytest, dotnet).

Owner's questions (Denis): "how would capping dotnet parallelism help? and what if we run things on devbox?"

Short answer:

1. **Capping helps the Mac stay usable, but it does not make gates finish sooner.** Load 281 is mostly too many
   threads queuing for the same cores. A machine-wide `dotnet` lease plus `DOTNET_PROCESSOR_COUNT` should bring the
   load from about 280 to about 30-40. GitHub/PyPI clients then get roughly 9 times their current CPU share, which is
   what stops the timeouts. A gate's own time changes little: the CPU work is the same and only the queueing moves.
   It needs one profile edit and one line in the Mac's `host.json`, and no engine code. **Do this first.**
2. **The devbox can take the .NET gate steps off the Mac**, and those steps can then run at the same time as the Unity
   steps. That takes about 9-15 minutes off a gate, and the Mac keeps only Unity and the light steps. It does need
   engine work: per-executor check identity, transport, and receipt import. It also needs measurements first: the
   devbox has no dotnet, so all devbox timings below are estimates, not measurements. One devbox gate host serves about two
   factory lanes, not four (see the arithmetic below). **Do this second, as an overflow executor in front of the
   local lease.**

## 0. What I could and could not see

| Source | Found |
|---|---|
| `~/.config/task-loop` on the devbox | `host.json` = `{"resources": []}`; `results/` holds only `iorlas-task-loop`; there are no lifesim runs, durations or check logs. `handoff/lifesim-02d50712.md`: the loop has never run here. |
| lifesim clone on the devbox (`~/Workspaces/lifesim`, origin `git@github.com:yoselabs/lifesim.git`, partial clone `blob:limit=1048576`) | `origin/main` at `8b0a28eb1` (2026-11-01): `.task-loop.json`, `justfile`, `tools/gate_plan.py`, `tools/plant.py`, `global.json` (SDK `10.0.401`, `rollForward: latestPatch`, test runner Microsoft.Testing.Platform). |
| Mac run logs, load samples, Mac core count | **Not reachable.** Only the facts the owner gave: faults about 650 s, test about 500 s, design-tests about 400 s under load; Unity steps 3-5 min each, unity lease 1; load reached 281 with 4 factory lanes; GitHub/PyPI timeouts under load. |
| beads | No GATECLEAN bead exists (`bd list --all`, read-only). Related beads: `tl-3cl.3` CHECKIDENT (closed, released 0.23.293), `tl-3cl.4` GATESELECT (open), `tl-4af` multi-machine dashboard (open), `tl-sqd3.24` delegate lock load under 4 lanes (open). |
| devbox hardware | `nproc` = 8, `AMD Ryzen 9 9950X3D` (the container sees 8 of its 16 cores), 35 GB RAM, 62 GB free in `$HOME`; `cpu.max` = `max` (no CFS quota). |
| `mise registry` | `dotnet  core:dotnet vfox:mise-plugins/vfox-dotnet asdf:...`: mise has a core dotnet backend. **Not installed and not tried.** |

Every number below that does not come from that table is marked **(est.)** with its inputs written out.

## 1. How a check is run today (what the design touches)

- **One check lane per gate in lifesim.** Execution splits into lanes only when the profile names a `lane`
  (`src/taskloop/domain/checks/plan.py:25-30`, `contracts/checks.py:81`). lifesim's checks name none, so each factory lane
  runs its gate steps one after another (`app/checks/executor.py:77-88`). The parallelism comes from the 4 factory lanes
  and from inside each .NET process.
- **Environment of a check.** `Attempts._exec` merges the check's declared `env`, the round's env and the run ids
  (`app/checks/attempts.py:73-77`). `Shell.stream` adds the worker mark and the slot env (`app/run/shell.py:57`), and
  `RealSpawner._env` builds the child from `tool_env` (`adapters/spawner.py:54-55`). `tool_env` passes on only the
  allowlist: `PATH HOME USER LANG TERM TMPDIR SHELL GIT_* UV SSH_*`, `LC_*`, `GIT_CONFIG_*` and registered
  `TL_*`/`TASK_LOOP_*` names (`tlkernel/childenv.py:32-49`, `:67-73`). **A `DOTNET_*` variable exported in the owner's
  shell or the factory's environment never reaches a check.** It has to be declared in the check's `env` in `.task-loop.json`
  (`contracts/config.py:100`, `contracts/checks.py:70`) or exported by the repo itself (the lifesim justfile already
  exports telemetry opt-outs).
- **The cache key includes that env.** `RunMemo.env_of` hashes the engine env plus `c.env` (`app/checks/cache.py:110-113`), so adding
  `DOTNET_PROCESSOR_COUNT` to a check's `env` invalidates its receipts once. That is correct, because the allocation tests
  depend on how busy the machine is.
- **Machine-wide leases already exist.** `engine.resources` + `needs` give one of `limit` flocks in
  `~/.config/task-loop/locks` (`app/checks/resources.py:72-83`, `:84-107`). The wait is recorded outside the run budget,
  and a cancelled lane stops waiting. This is how the unity lease works.
- **The same `needs` decides where a check may run.** `Resources.lacking` (`resources.py:67-69`, through `domain/checks/affinity.py:22-24`):
  if a `host.json` exists, only the resources it lists are present. A check that needs a missing one is *deferred*,
  not run (`executor.py:109-110`, `:133-143`), and the engine labels the bead `needs:<r>` to move it to another host (`app/run/engine.py:272-279`).
- **Check identity (CHECKIDENT).** `RunKey` = check, cmd, config, **toolchain**, tree, base, inputs, selected, env,
  **execution**, dependencies, plan, plan_output (`contracts/runkey.py:13-32`). The toolchain digest is
  `sha1(f"{platform.system()}-{platform.machine()}" + the pin files)` (`cache.py:103`, `:131`, `domain/checks/inputs.py:101-105`).
  The execution field is the constant `host-v1` for host checks (`app/checks/execution.py:29`, `cache.py:149-150`)
  and the image id for container checks (`execution.py:50-64`). A check is authorized only when the receipt's full key
  equals the expected key (`cache.py:167-173`, `:179-193`; `app/checks/authorization.py:22-34`). Both the land gate
  (`app/land/stackgate.py:35-37`) and `tl green` (`cli/green.py:25`) go through `authorization.results`.
  The pre-push judge (`app/land/push_judge.py:98-108`) checks the commit it is given.
- **What this means for the devbox:** a receipt made on the devbox carries `Linux-x86_64` in its toolchain and can never equal
  a key the Mac computes (`Darwin-arm64`). That is correct today: no receipt from another host is accepted by accident. On the
  other hand, `host-v1` is the same constant on every host, so the host's identity is not in the key at all; only
  `system-machine` tells hosts apart. Part (b) has to change both.

## 2. Part (a): capping .NET and the lanes

### 2.1 Where the threads come from (lifesim `origin/main`)

| Gate step | Command | What sets its parallelism by default |
|---|---|---|
| `build` | `dotnet build lifesim.slnx --nologo -warnaserror` (justfile:186-187) | MSBuild `-m` defaults to one node per logical CPU; node reuse is on; there is one shared Roslyn server (VBCSCompiler) per user |
| `test` | `dotnet test --solution lifesim.slnx --no-build ...` (justfile:194-197), or per project (`tools/gate_plan.py:687`) | MTP runs the 3 test projects in `SUITES` (Sim.Architecture, Sim.Properties, Sim.Scenarios) side by side (default module parallelism = CPU count, **unverified for SDK 10.0.401**); xunit v3 `maxParallelThreads` defaults to the CPU count in each module; CsCheck uses the CPU count per property test unless `CsCheck_Threads` is set, and it is not set for `test` |
| `allocation` | `... --filter-trait Lane=plain -- --parallel none` (justfile:222-223, gate_plan.py:855) | already serial |
| `content` | `dotnet build tools/bake ... -m:1 -nodeReuse:false -p:UseSharedCompilation=false` (justfile:331) | already capped |
| `faults` | `tools/plant.py`: one scratch worktree; per patch `dotnet test --project X` (plant.py:175), which **builds** the project, with `CsCheck_Threads=1` (plant.py:26-31) | MSBuild `-m` = CPU count on every patch build, plus the test host's xunit threads |
| `design-tests` | `tools/run_tests_parallel.py` | `ThreadPoolExecutor(max_workers=os.cpu_count())` (run_tests_parallel.py:97), with one Python process per module |

**One knob covers most of the .NET rows: `DOTNET_PROCESSOR_COUNT=K`.** The .NET runtime (6+) reports K as
`Environment.ProcessorCount` to every managed process. That includes MSBuild's default node count, xunit's default thread count,
CsCheck's default, MTP's module parallelism and the thread pool. Children inherit it: `plant.py` copies `os.environ`
(plant.py:27). **Unverified:** that every one of these defaults reads `Environment.ProcessorCount` in the pinned versions;
check it with one `dotnet test` run under the variable, reading the thread count off the MTP diagnostic log the `test` recipe
already writes (`--diagnostic`). The explicit flags, if the variable alone is not enough:

| Setting | Where | Effect | Recommend |
|---|---|---|---|
| `DOTNET_PROCESSOR_COUNT=4` | check `env` for build, test, faults, allocation | one cap for all managed defaults | **yes** |
| `-m:2` (or `-maxcpucount:2`) | justfile `build`, and plant.py's `dotnet test` (which builds) | caps MSBuild nodes | yes, if the variable does not reach MSBuild's `-m` |
| `-nodeReuse:false` / `MSBUILDNODEREUSE=0` | build | nodes exit after the build instead of idling. They use no CPU while idle, only memory. With 4 lanes x N idle nodes that is GBs of RAM, not load | yes (memory) |
| `UseSharedCompilation=false` | build | **raises** CPU: every csc starts and JITs again | **no**: keep the shared compiler server, one per user across all lanes |
| `dotnet test --max-parallel-test-modules 1` | justfile `test` | one test project at a time per lane | optional (est. halves peak test threads) |
| xunit `--max-threads K` / `xunit.runner.json maxParallelThreads` | after `--` in `test` | caps test threads per module | only if `DOTNET_PROCESSOR_COUNT` is not honored |
| `CsCheck_Threads=1` | check `env` for `test` | property tests run single-threaded | yes: faults, the bounded run and nightly already use it (plant.py:31, test_suites.py:30) |
| `DOTNET_gcServer=0`, `DOTNET_GCHeapCount` | - | console apps and test hosts already use workstation GC; HeapCount applies only to server GC; no lifesim project outside `prototype/` sets `ServerGarbageCollector` (git grep) | **no effect, skip** |
| `DOTNET_TieredPGO=0` | - | trims tier-0 instrumentation in short-lived processes; est. under 5 % CPU, not a load cap (unverified) | skip |
| design-tests workers | `run_tests_parallel.py:97` | `max_workers=min(4, cpu_count)` or an env override (lifesim change) | yes: est. 4N to 16 processes across 4 lanes |

### 2.2 The caps the engine can apply

| Cap | Mechanism | Code change | What it cuts |
|---|---|---|---|
| **A. Global compute lease** `dotnet` | `engine.resources.dotnet.limit = 2`; `needs: ["dotnet"]` on build, test, faults, allocation, content (the same mechanism as unity, `resources.py:72-107`) | **none** in the engine. Profile edit, plus `"dotnet"` added to the Mac's `host.json` if it lists resources, or every dotnet check is deferred (`affinity.py:22-24`, `executor.py:109`) | at most 2 lanes in a .NET step at once |
| **B. Per-process CPU budget** | `DOTNET_PROCESSOR_COUNT=4`, `CsCheck_Threads=1` in check `env` | none (profile) | threads per .NET process from N to 4 |
| **C. Lower priority for check processes** | `nice -n 10` before check argv. `nice` is already a recognized wrapper (`domain/checks/cmd/matchers.py:9`), so the program matcher still sees `dotnet`/`just`. `taskpolicy -b` is **not** recommended: on Apple Silicon it puts the process in the background QoS on E-cores with IO throttled, which makes heavy steps several times slower (unverified factor) | profile argv, or later an engine `check_nice` in `Shell.stream` (`shell.py:57`) | does **not** lower the load average; it gives network clients, the dashboard and the editor the CPU first |
| **D. Load-aware lane start** | the loop waits before `queue()` while `os.getloadavg()[0] > 2 x cores` (`app/loop/loop.py:201-218`) | small engine change; shows as a loop wait | stops new beads being admitted while the machine is overloaded; running gates are not touched |

### 2.3 Arithmetic (est.)

Inputs: Mac logical cores N (unknown; **12** is used as the example, an M-series Pro); 4 factory lanes; per-lane thread
model while a .NET step runs ≈ (modules in parallel x xunit threads) + CsCheck threads ≈ 3N + N = 4N for `test`;
≈ N MSBuild nodes + compiler server for builds; N Python processes for design-tests.

- **Today:** 4 lanes x (between N and 4N) = 4N to 16N = 48 to 192 runnable threads for N=12, plus the Unity editor,
  design-tests' N processes per lane (up to 48), the Codex and delegate processes, and git/uv. The reported 281 ≈ 23 per core
  **fits this model** (unverified: no thread sample from the Mac).
- **With A + B (dotnet limit 2, K=4, CsCheck 1):** 2 lanes x (3 modules x 4 + 1) ≈ 26, or 2 x 4 = 8 with
  `--max-parallel-test-modules 1`. Add design-tests capped at 4 per lane (≤ 16), Unity ≈ 4-8 (est.), and other processes
  ≈ 5. **Load ≈ 30-55, against 281.**
- **What that buys:** under the kernel's round-robin, a process that wants CPU gets roughly cores/load of a core. At 281 on 12
  cores that is 1/23 of a core; at 40 it is 1/3.3. The CPU-bound parts of TLS handshakes, ssh, `uv` resolution and `git` index
  work therefore run **about 7x faster** (23/3.3). That is the timeout fix. With C, `nice`, they go first on top of that.
- **Gate wall time:** the CPU work is the same core-seconds either way. Today the 4 lanes share N cores, about N/4 each. With
  the lease, 2 lanes get about N/2 each, and the other 2 wait on the lease (an `RESOURCE` wait in the wait log, outside
  the budget) while their writers keep working (writers are remote AI calls and use little CPU). Per-lane gate throughput is **about
  the same**, with an est. 5-15 % gain from less context switching, less cache thrash and less memory pressure. Fewer network
  timeouts also mean fewer reruns, and that gain cannot be estimated without the Mac logs.
- **What capping cannot do:** shorten a gate. On one Mac, a 1550 s heavy chain (faults 650 + test 500 + design-tests 400)
  is the same CPU work whatever the cap. Only more cores (part b) or fewer steps run (`when` and plan skips, already in place) make it shorter.

## 3. Part (b): the non-Unity gate steps on the devbox

### 3.1 What runs where

| Mac only | Either host (eligible for the devbox) |
|---|---|
| `unity-check`, `unity-analyzers`, `unity-tests`, `unity-play-tests`, `unity-scenes-if-stale` (all `needs: ["unity"]`). Unity republishes the sim itself, so the Mac still needs dotnet for that. | `build`, `content`, `test`, `allocation`, `faults` (dotnet 10); `design-tests`, `text`, `blueprint`, the other light Python checks (uv, typos, gitleaks from `mise.toml`). `blueprint` needs a shelf clone (`just doctor`); `assets`/`unity-integrity` may need LFS content (**unverified**). Keep these on the Mac in the first version. |

**What the devbox must have**

- dotnet SDK `10.0.401` (`global.json`): `mise use -g dotnet@10.0.401` (core backend in the registry, **not tried**), or
  better, the repo's own `mise.toml` pins it, so the Mac and the devbox resolve the same version. `mise.toml` pins only just/uv/prek/gitleaks/typos/bd today.
- `just tools` from the repo (`mise install --locked` plus `dotnet tool restore`) and a NuGet cache in `~/.nuget`;
  `dotnet restore lifesim.slnx --locked-mode` (the profile's `prepare`).
- the task-loop plugin (it is already here) and a gate repo at `~/gate/lifesim.git`, a full bare repo that receives pushes.
  **Not** the partial clone in `~/Workspaces/lifesim`: a checkout from a `blob:limit` clone fetches missing blobs from GitHub
  on demand, which brings GitHub back onto the critical path.
- `host.json` on the devbox lists `["dotnet"]` and no `unity`, so any Unity check routed there is deferred
  (`executor.py:133-143`) rather than run.

### 3.2 Clean export of the judged commit (GATECLEAN)

The devbox never sees the Mac's worktree; it receives only commits:

1. The Mac pushes `git push devbox-gate <tree-commit>:refs/tl/gate/<run>/head <base>:refs/tl/gate/<run>/base` (over ssh,
   straight to the devbox, without GitHub). The gate judges commits, and the pre-push judge already insists on a clean
   HEAD (`push_judge.py:80`), so the candidate is committed by the time it is judged.
2. On the devbox, `git worktree add --detach <wt> <head>` from the bare repo (a real worktree, not `git archive`: `plant.py`
   runs `git worktree add` itself, and `tools/changed.py`/`gate_plan.py` run `git diff`).
3. `git update-ref refs/remotes/origin/main <base>` in that worktree's repo. lifesim's planner and `changed.py`
   take the merge-base with `origin/main` (justfile comments on `check`). If `origin/main` is not the Mac's base, the step plan
   is different.
4. `prepare` (`dotnet restore --locked-mode`), then the checks, each with its declared `env`.
5. The profile is read from the judged tree (`authorization.profile`, `authorization.py:17-19`).
6. Gitignored inputs: `InputKeys.ignored_of` hashes gitignored files under a check's `inputs` (`cache.py:55-61`). A clean
   worktree has none, so a check with `inputs` that reads ignored files gets a different key on the two hosts. The eligible
   checks above have no `inputs` (whole-tree keys), so this does not apply to them. **Rule: only checks whose key reads no
   ignored files are eligible.**

### 3.3 Receipts bound to the executor (extends CHECKIDENT)

Required engine changes (file:line as of 0.23.293):

1. **An executor identity in `execution`.** Today host checks carry `host-v1` (`execution.py:29`). Add
   `RemoteExecution(identity = sha256("remote-v1", host key fingerprint, system-machine, dotnet --version, mise lock digest))`,
   resolved before reuse like the container identity (`authorization.py:30-33`, `executor.py:122-131`).
   **Also make the local identity host-specific** (`host-v1:<machine id>`). Today `host-v1` is the same on every machine, so the
   key does not record which machine ran a check, only `system-machine` does. Changing it invalidates every receipt once.
2. **The toolchain digest follows the executor, not the judge.** `RunMemo.system` is `platform.system()-machine()` of the process that computes the key
   (`cache.py:103`). For a remote check, the Mac must compute the key with the executor's system (`Linux-x86_64`), so the
   expected key equals the one the devbox computes. Change: `toolchain(self.system_of(c))`, where `system_of` comes from the
   resolved execution.
3. **Admitted executors are set per machine, not by the candidate** (GATESELECT, `tl-3cl.4`). `host.json` gains
   `executors: {"devbox": {"ssh": "devbox", "repo": "~/gate/lifesim.git", "identity": "<pinned digest>"}}`. The profile may only mark
   a check `portable: true`. A candidate that edits `.task-loop.json` cannot name an executor; at most it can mark a check portable,
   and the key still records where the check ran.
4. **Authorization accepts any admitted execution.** `authorization.results` today resolves one execution per check. It
   becomes: for a portable check, a hit for the full key under **any** admitted executor (`local`, `devbox`) satisfies it. Every
   other field (tree, base, cmd, env, selected, dependencies, plan) must match exactly, as now (`cache.py:167-173`).
5. **Receipt import.** The devbox runner returns a `PassRecord` (`contracts/checks.py:205-220`) as JSON on a channel the check
   cannot write to (the runner's own ssh session, after the check process tree has exited; never parsed from check output).
   The Mac recomputes the expected key for that executor, compares the full key, and writes the record into its own store
   `results/<repo_key>/<check>/<digest>.json` (`cache.py:217-226`), with `host` = the devbox and `log_abs` = a local copy of the
   log, which is pulled with the receipt so the dashboard and the writer can read it.

**Trust: who signs a receipt.** Today nobody signs one. A receipt is trusted because only one Unix user writes `~/.config/task-loop`, and the
check code (the candidate's code) runs as that same user and could forge one anyway (`c4-system.md`, "one Unix user per machine runs
every process"). A remote receipt reaches the **same** level of trust, and no more, if:
- it travels only over the Mac-initiated ssh session (devbox host key pinned in the Mac's `known_hosts`), and
- the Mac recomputes and compares the full key itself, so the devbox reports a verdict and never decides what it applies to.

Signing it (`ssh-keygen -Y sign` with a devbox key) adds protection only against mix-ups in transport or storage; the candidate's
code running as the same user on the devbox can read that key. Real isolation means a separate `tlgate` Unix user on the devbox
that runs the checks, with a signing key that user cannot read. That is a later step, and it would make the devbox **stronger** than the Mac.
Recommendation: ship without signing, with the identity check and the key comparison above, and file the `tlgate` user separately.

### 3.4 Transport and scheduling

```
Mac engine (gate round)                                     devbox
  plan -> eligible portable checks, devbox admitted
  resources.hold("gatehost") local lease, limit 1 per remote
  git push devbox-gate head,base -> refs/tl/gate/<run>/*  ->  bare repo
  ssh devbox tl gate-serve --run R --head H --base B         -> worktree add, origin/main=B, prepare, checks
        --checks build,test,allocation,faults [--expect-keys]   (devbox's own `dotnet` lease, limit 1)
  <- stream: log lines; final: receipts JSON + logs tarball <-
  verify keys, import receipts, publish TL_CHECK_LOG_*
  meanwhile the Unity lane runs locally (unity lease)
```

- The eligible checks become their own check lane (`lane: "remote"`, `contracts/checks.py:81`), so `Lanes` runs
  them alongside the local Unity lane, and the first red on either side cancels the other (`app/checks/lanes.py`, module docstring).
  This is where the wall-time gain comes from.
- **Fallback:** if the devbox is unreachable, its identity differs from the pinned one, or the gate host lease is busy for more
  than `lane_wait_min` (`contracts/config.py:223`), the lane runs locally under the `dotnet` lease from part (a). This keeps the
  devbox an overflow, not a dependency. Every fallback is written to the run log with its reason.
- `ssh` is started through the Spawner like any check command, so a stop or a halt kills it (`app/run/shell.py:54-66`), and the
  devbox side ends its process group when the ssh session drops (`gate-serve` treats a closed stdin as a stop).

### 3.5 Failure modes

| Failure | Behaviour |
|---|---|
| devbox down / ssh times out | the lane falls back to local (dotnet lease); a wait event; no verdict lost |
| push rejected (disk full, ref exists) | fallback; the ref name includes the run id, so it never collides |
| devbox SDK patch differs from the Mac's (`rollForward: latestPatch`) | it is a different identity, not a wrong one: the key carries it. A red that shows only on the devbox is a real Linux red; the fix bead says so |
| Linux-only or macOS-only test behaviour (paths, case sensitivity, culture; `InvariantGlobalization` is on in tests) | a portability red shows up as a normal red. **Unverified** that the lifesim suites pass on Linux; slice 1 measures it |
| receipt for the wrong tree, base or env | key mismatch, rejected, the check counted as not run (fail closed, as `cache.py:172`) |
| the check output imitates a receipt | ignored: receipts come only from the runner's final frame after the process tree has exited |
| ssh drops after the check went green on the devbox | no receipt imported, the check reruns (a pass is never assumed) |
| devbox overloaded by its own loops | its `dotnet` lease queues remote work; the Mac's gate-host lease times out, then falls back |
| NuGet restore from the devbox network fails | `prepare` red is an infrastructure fault (`FAULT_INFRA`), the lane falls back to local |
| stale `refs/tl/gate/*` and worktrees | `gate-serve` removes the worktree in `finally`; a daily prune of refs older than 1 day |

### 3.6 Load and wall time, with and without (est.)

Inputs: owner's loaded figures (faults 650, test 500, design-tests 400 s; Unity 3-5 min per step). In a src-changing gate the Unity
steps that run are unity-check, unity-analyzers and unity-tests, plus unity-play-tests when planned: 3-4 steps, **9-20 min**. The light
steps take about 60 s unloaded (justfile comment on `check`). Mac N=12 as above.

**Devbox throughput.** Under load each Mac lane gets about N/4 = 3 cores, so the heavy chain is ≈ (650+500) x 3 ≈ **3450
Mac-core-seconds** of .NET work, plus 400 x 3 ≈ 1200 for design-tests. Taking a Zen 5 core as roughly 0.8-1.0 of an M-series P-core
(**unverified**) and 60-70 % parallel efficiency on 8 cores, faults (one patch after another) + test on the devbox take ≈
3450 / (8 x 0.9 x 0.65) ≈ **740 s ≈ 12 min** per gate, one gate at a time.

| | Mac load | Gate wall (src change) | Notes |
|---|---|---|---|
| today | ≈ 281 (measured) | 60 + 400 + 500 + 650 + 9-20 min Unity ≈ **35-46 min** + unity lease wait | sequential in one check lane |
| (a) caps only | ≈ 30-55 | ≈ the same per gate (est. ±15 %); 2 of 4 lanes queue on the dotnet lease | timeouts largely gone |
| (b) devbox + local Unity lane | ≈ 15-30 (Unity, light, writers) | max(12 min devbox + ≈ 1 min push and import, 9-20 min Unity) + light ≈ **21-27 min** | saves ≈ 9-15 min per gate *when the devbox is free* |
| (b) with 4 lanes all gating | | devbox busy ≈ 13 min per gate; at one gate per lane every ≈ 45 min (unknown cadence), demand = 4 x 13 / 45 ≈ **1.2 > 1** | about 2 lanes' worth at most; the rest fall back to the local lease |

The cadence (gates per lane per hour) is the input that decides how many lanes one devbox serves. It is in the Mac's `runs/*/checks`
durations and `events.jsonl`, which I could not read. Slice 1 has to bring it.

## 4. Options ranked

| Rank | Option | Effort | Mac load | Gate wall | Risk |
|---|---|---|---|---|---|
| 1 | **dotnet lease (limit 2) + `DOTNET_PROCESSOR_COUNT=4` + `CsCheck_Threads=1` + `nice -n 10`**: profile and `host.json` only | S, today | 281 to ≈ 40 | ≈ same | low; one-time cache invalidation; forgetting `host.json` defers every dotnet check |
| 2 | **design-tests worker cap** (lifesim `run_tests_parallel.py:97`) | XS | −(4N−16) processes | ≈ same | none |
| 3 | **devbox as an overflow gate host** for build, test, allocation, faults (section 3) | L (identity, transport, import, lane, fallback) | to ≈ 15-30 | −9-15 min per gate, for about 2 lanes | Linux portability of the suites unknown; a new trust edge |
| 4 | load-aware lane start (`loop.py:201-218`) | S | caps admits only | none | it hides symptoms; useful as a guard rail after 1 |
| 5 | whole lifesim factory lanes on the devbox, using the existing bead affinity (`engine.py:272-279`) | M | some | - | `unity-analyzers`/`unity-tests` have `when: src/**, config/**, content/**` (lifesim `.task-loop.json`), so nearly every sim bead needs unity and is moved back to the Mac. Only docs/design/tools beads benefit |
| 6 | `taskpolicy -b` for lanes | XS | load unchanged | heavy steps several times slower on E-cores (unverified) | no |

**Recommendation:** do 1 and 2 now. They answer "how would capping help": the Mac stays usable and GitHub/PyPI stop timing out, but no gate
gets shorter. Then build 3 in slices, starting with a measurement, because the devbox numbers above are estimates and the Linux pass rate of
the lifesim suites is unknown. Keep the local dotnet lease as the fallback of 3.

## 5. Smallest first slice of (b)

**Slice 1, measurement only, no engine code:** install dotnet `10.0.401` on the devbox (mise), make a full bare clone, and
on 3 recent lifesim main commits run `just build`, `just test`, `just allocation`, `just faults` (`LIFESIM_GATE_ALL=1`)
and `just design-tests` with `time`. Record: wall time per step, pass or red (Linux portability), and peak load. In the same window, from
the Mac: the per-step `exec_seconds`/`wait_seconds` of the last 50 gates (`Duration` rows, `executor.py:217-220`) and the
gate cadence per lane. These two tables replace every **(est.)** in 2.3 and 3.6, and they decide whether slices 2-4 are worth building.

Then: slice 2, shadow mode (`tl gate-remote` run by hand pushes a landed commit and runs the steps; receipts are compared, never
imported). Slice 3, identity and authorization changes (3.3, items 1-4) behind `portable`. Slice 4, the remote lane, import and fallback
in the round.

## 6. Beads to file

1. **LOADCAP: lifesim profile caps .NET load.** `engine.resources.dotnet.limit = 2`; `needs: ["dotnet"]` on build, content,
   test, allocation, faults; `env: {DOTNET_PROCESSOR_COUNT: "4", CsCheck_Threads: "1"}` on build, test, faults, allocation; Mac `host.json` lists
   `dotnet` (and `unity`). *Acceptance:* with 4 factory lanes gating, `sysctl vm.loadavg` sampled every 60 s over 2 h stays ≤ 60;
   no dotnet check is `deferred` on the Mac; `tl` wait log shows `RESOURCE dotnet` waits; zero GitHub/PyPI timeout faults in that window,
   against the count of the previous 2 h of comparable work.
2. **LOADCAP-VERIFY: `DOTNET_PROCESSOR_COUNT` reaches every default.** *Acceptance:* one `dotnet test` and one `dotnet build` under
   `DOTNET_PROCESSOR_COUNT=4` show ≤ 4 worker threads in `ps -M` (Mac), or the MTP diagnostic log reports `ProcessorCount=4`; if any
   tool ignores it, the explicit flag (`-m:2`, `--max-threads 4`, `--max-parallel-test-modules 1`) is added to the justfile and noted.
3. **DESIGNTESTCAP (lifesim): design-tests workers capped.** `run_tests_parallel.py` uses `min(4, cpu_count)` or an env override.
   *Acceptance:* design-tests wall time unloaded within 20 % of before; process count ≤ 4 during the run.
4. **CHECKNICE: check processes run at nice 10.** *Acceptance:* a check started by the engine shows `NI 10` in `ps`; the program
   matcher still identifies `dotnet`/`just` (test on `domain/checks/cmd/matchers.py`); no change to cache keys.
5. **GATEHOST-MEASURE: devbox timings and Linux pass rate for the non-Unity gate.** *Acceptance:* a dated table in this doc,
   for 3 commits, of wall time per step and verdict on the devbox; the same steps' `exec_seconds` from the Mac's last 50 gates, and the
   gate cadence per lane; a decision line: go or no-go for GATEHOST-*.
6. **EXECIDENT: host and remote execution identities.** `host-v1` becomes host-specific; `RemoteExecution` identity; the toolchain
   digest is computed for the executor's system (`cache.py:103`, `:131`). *Acceptance:* a failing test first: a receipt made under
   executor A never satisfies a key expected under executor B (same tree, base, cmd and env); a devbox key computed on the Mac equals the one
   computed on the devbox for the same commit (a fixture with `system` injected); suite green.
7. **GATEHOST-AUTH: admitted executors are set per machine, portable checks accept any admitted executor.** `host.json.executors`;
   profile `portable: true` only. *Acceptance:* a candidate whose `.task-loop.json` adds an executor or marks a Unity check portable gets no
   authorization from a devbox receipt (test); `authorization.results` returns the devbox receipt for a portable check whose full key
   matches; GATESELECT (`tl-3cl.4`) referenced.
8. **GATECLEAN: gate-serve runs a judged commit in a clean export.** Push to `refs/tl/gate/<run>/{head,base}`, worktree add --detach,
   `origin/main` set to base, prepare, checks, worktree removed. *Acceptance:* a real-git test: the export's tree hash equals the judged
   tree; `git merge-base HEAD origin/main` equals the base; an untracked or ignored file in the Mac worktree never reaches the export;
   the worktree is gone after a stop.
9. **GATEHOST-RECEIPT: import a remote receipt over ssh, fail closed.** *Acceptance:* tests: a receipt with any key field different from
   the Mac's expected key is rejected; receipt-shaped text in check output is ignored; a dropped session imports nothing; the imported
   record has `host` = the devbox and a readable local log.
10. **GATEHOST-LANE: eligible checks run as a remote lane beside the Unity lane, falling back to local.** *Acceptance:* with the devbox
    up, a src-changing lifesim gate runs the dotnet steps remotely and the Unity steps locally at the same time (dashboard shows both); a red on
    either side cancels the other; with the devbox down, the same gate runs locally under the dotnet lease and the run log names the
    fallback reason; Mac gate wall time over 10 gates is reported against the GATEHOST-MEASURE baseline.
11. **GATEHOST-DEVBOX: devbox provisioned as a gate host, reproducibly.** dotnet `10.0.401` pinned in lifesim `mise.toml` (both hosts),
    devbox `host.json` = `{"resources": ["dotnet"]}`, bare repo `~/gate/lifesim.git`, ref and worktree prune. *Acceptance:* after
    the devbox container is recreated, `just doctor` in a gate worktree prints `doctor: ok` for the dotnet line, and `dotnet --version` prints
    `10.0.401`.
12. **GATEHOST-USER (later): checks on the devbox run as a separate `tlgate` user.** *Acceptance:* a check process cannot read the
    receipt signing key or write `~/.config/task-loop` of the owner; receipts are signed and the Mac verifies them with `ssh-keygen -Y verify`.

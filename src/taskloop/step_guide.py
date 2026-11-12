"""The fixed words a person reads around the step commands: which steps are built, what each `Next` word or refusal asks
them to do, and the whole-DB discard steps. Text only; `step_render` places it, every decision is an operation's."""

from pathlib import Path

from taskloop.hold_guide import HOLD, ON_HOLD
from taskloop.land_guide import LAND_GUIDE, LAND_NEXT

STEP_ONLY = "steps built: plan, implement, check; publishes task/<id>; `tl step land` lands, never a round"
PUBLISH = ("The step's result is verified but not on `origin` yet: `tl step publish`. A `refused` word names what to fix; "
           "`unavailable:remote` is often credentials: check that `git push` works from this shell. After `refused:diverged`, "
           "`remote_moved` or `remote_ahead` (the entry log's `branch=` word or the last `tl step publish`), rerunning does not "
           "help: fetch `task/<id>`, compare it with the verified commit, then merge or move one branch aside yourself.")
HELD = ("The tracker claim stays held, and the slot until the step ends on a clean slot (`tl step release` frees a slot left "
        "held; `--abandon` also returns the claim). While a step runs its entry renews the claim's bd lease every 100 s; between "
        "steps nothing does, so a `bd reclaim` run on that tracker can revert the claim once its lease lapses: at the earliest "
        "about 5 minutes after a step ends (bd's default reclaim grace is 10 minutes, so about 15 minutes with a plain `bd reclaim`). "
        "A round (`tl step next`) never renews or retakes a claim: a task whose claim lapsed is open again while factory.db holds "
        "its attempt, and rounds skip it (`attempted`).")
ABANDON = "`tl step release --abandon` frees the slot and gives the task back."
ROUNDS = ("Run scheduling rounds until stopped (Ctrl-C): a round at once, then every --every seconds and as soon as a slot frees; "
          "each round holds the tasks it took that stopped (`bd list --label held`), advances claimed tasks whose step is "
          "done to their next step, then starts approved ready tasks; "
          "the tracker is read only when a slot is free; while a passed task waits for `tl step land`, the last free slot is left "
          "to that land (`slot_for_land`); writes `<artifacts>/rounds.log` (a passed task: `report land`). Runs in this "
          "terminal until stopped: Ctrl-C once stops after the current move, twice exits at once; launched steps keep "
          "running; started with Ctrl-C ignored (`nohup`, `&`), only SIGTERM stops it. "
          "A move in flight finishes first: a verify waits for its publish push (up to Git's timeout). While every slot is held "
          "no candidate is tried, so a wrong --checkout is refused only once a slot frees.")
GUIDE = {
    "start": "Re-run `tl step start` to relaunch its entry (each `tl step next` round relaunches it until its deadline; an "
    "entry registered before a reboot is relaunched with its deadline renewed from --minutes, once per reboot). "
    "If the last entry says `claim_lost`, the tracker claim is gone (reverted, taken by another actor, or the task closed): "
    "check `bd show <task>`; relaunching cannot help and nothing retakes the claim. `tl step release --abandon` (its claim "
    "answers `not_held`), then `tl step start` to admit a fresh attempt.",
    "wait": "Its entry runs; wait, then `tl step show` again.",
    "verify": "Run `tl step verify`.",
    "repeat": "Run `tl step start` again to repeat it with this listing as feedback, or remove the files and `tl step verify`.",
    "repeats_exhausted": "Repeated twice and still unsettled: inspect the slot, tidy it, then `tl step verify` (which releases "
    "the slot), or `tl step release --abandon`.",
    "release": "The step ended; its slot is still held. Remove the listed files if any, then `tl step release`; `--abandon` also "
    "gives the task back (not once a land's S is, or may be, on origin's main: then `tl step land`, which retries its "
    "candidate's release first).",
    "abandoned": "Abandoned: the slot is free and the claim was returned (`Claim:` says if not). `tl step start` admits a fresh "
    "attempt.",
    "publish": PUBLISH,
    "advance": "The step is verified and on `origin`. The next `tl step next` round (or `tl step rounds`) starts the next step "
    "once a slot is free, before any new task, oldest first; by hand, `tl step start <task>`. Either way one tracker read "
    "first confirms the task is in progress for taskloop (no new claim, no label check: removing the label does not stop it, "
    "`tl step release --abandon` does); it starts from that published commit (the check step runs the profile's checks on it, "
    "detached, with the required names read from your local `main`).",
    "done": "Collected: `succeeded` tells whether the step's result was verified (the check step: every check required by `main` "
    "passed). A failed check step keeps the claim and nothing retries it: read the `Check:` lines and logs, then `tl step start` "
    "re-runs the checks on the same commit (no new plan or implement), or `tl step release --abandon` starts the task afresh.",
    "unknown": "The entry or the store could not be read; run `tl step show` again.",
    "stuck:expired_admitted": f"Nothing ran; rounds only report it. {ABANDON} Then `tl step start` admits a "
    "fresh attempt. Its deadline passed with no relaunchable entry from before a reboot (none registered, one from this boot, or "
    "the boot unknown); such an entry would instead be relaunched with the deadline renewed once from --minutes.",
    "failed": "Ended without a verified result; a hand-started step is never held, its claim stays and rounds never retry it: "
    "`tl step show`, then `tl step release --abandon` and `tl step start` to try afresh.",
    "running": "Its entry runs; the round leaves it alone.",
    "attempted": "Open in the tracker while factory.db holds its attempt: the claim was returned or lapsed. `tl step show` it; "
    "rounds never take it again.",
    "abandoned_skip": "Abandoned here: rounds never re-admit it; `tl step start` admits a fresh attempt.",
    "no_free_slot": "No slot is free: each one is reserved, or unusable (missing, dirty, on another branch: the detail and the round log's "
    "`unusable` lines name it and why; fix it or `tl slot adopt`). `tl step rounds` fills a freed slot seconds after.",
    "unusable": "A slot no attempt holds cannot be used (missing, dirty, redirected or on a branch: `unusable:<slot>:<why>`, its "
    "path printed under the line): put it right (`git worktree add --detach`, `git switch --detach`, a clean tree) or `tl slot adopt`.",
    "slot_for_land": "One slot is free and kept for `tl step land`: a passed task waits for it, so rounds start nothing into the "
    "last free slot. Run `tl step land` (or release the task); rounds go on as soon as it is landed.",
    "rounds_running": "Another `tl step rounds` runs for this backlog (the pid is its lock record's, informational): use its "
    "terminal, or stop it there with Ctrl-C first. `tl step next` runs beside it.",
    "interval": "The rounds interval (`--every`, machine config `round_seconds`) is whole seconds, at least 5; "
    "`git_read_seconds` is between 30 and 86400.",
    "rounds_lock": "The rounds lock file beside factory.db cannot be created: fix that folder's permissions.",
    "stuck:entry_lost": "The agent may still run: if `Worker` names a pid, check its cwd is the slot (`lsof -a -p <pid> -d cwd`) "
    f"and stop only its group (`kill -TERM -<pgid>`); then {ABANDON} With no `Worker` recorded it cannot be shown stopped: "
    "only the whole-DB discard remains.",
    "stuck:hung": "Stop the worker first, the agent may keep editing the slot: check the `Worker` pid's cwd is the slot "
    "(`lsof -a -p <pid> -d cwd`), then `kill -TERM -<pgid>`. Then the entry: `ps -o command= -p <entry pid>` must show "
    f"taskloop.attempt_entry, then `kill -TERM <entry pid>`. Then {ABANDON}",
    "stuck:uncollected": "The result was captured but never collected: its answer or its session is still pending or faulted (the "
    f"attempt's entry.log says why), and no verify can judge it. Keep the evidence. {ABANDON}",
    "stuck:conflict": f"The owner inspects the evidence; then {ABANDON}",
    "stuck:setup_failed": "The step's setup (the profile's `setup`, run before an implement agent) failed twice; no agent ran and "
    "rounds no longer relaunch it (a relaunch would only refuse `environment:failed`). Read `setup-<run>.log` beside the "
    f"attempt's entry.log (`Setup:` names the last run), fix the cause (the task branch's `setup`, the network, the slot); then {ABANDON} "
    "Rounds never re-admit an abandoned task: `tl step start` admits it afresh at plan.",
    "task_missing": "The task is gone from the tracker (deleted): the round skips it and starts the others. `tl step release --abandon "
    "<task>` clears its attempt.",
    "paused": "The task carries `held` that no hold of the factory's put there (added by hand): rounds will not start it. Remove the "
    "label (`bd label remove <task> held`) to let it run; a step already running goes on.",
    "task": "The task could not be read from the tracker named by the attempt's tracker root (deleted, malformed, or the root no "
    "longer resolves): check `bd show <task>` there. Rounds skip it every round; `tl step release --abandon` gives it up.",
    "changed": "Another attempt of the task became current since the round read the store; the next round follows it (`tl step show`).",
    "unsettled": "The slot has files the step did not commit (listed), or the slot pointer or HEAD changed. Remove the "
    "listed files and `tl step verify`, or run `tl step start` again to repeat the step; for `redirected` "
    "inspect first; for `head_moved` (a commit the sandbox should have refused; inspect any listed tag or branch, delete "
    "only what the agent made) "
    "`tl step start` refuses too, so run `tl step release --abandon`, then `tl step start`; for `worker_alive` stop the worker "
    "first; for `staged` unstage the listed paths first.",
    "registration_conflict": "Another start registered its entry first; `tl step show` follows that attempt.",
    "slot_busy": "Another entry or verify holds the slot: wait and run it again; if nothing ends, see the `stuck:hung` guide.",
    "lock": "The slot's lock file under `<slots root>/<repo id>/.locks` cannot be created: fix that folder's permissions.",
    "not_terminal": "The step has not ended: wait for it, `tl step start` to repeat it, or `tl step release --abandon`.",
    "entry_running": "Its entry runs: wait, or stop it by verified pid (the `stuck:hung` guide), then run it again.",
    "worker_unknown": "Dispatched with no agent recorded, so it cannot be shown stopped: the whole-DB discard is the only way out.",
    "slot_dirty": "The slot stays held: remove or restore the listed files (`git -C <slot> status --short` lists them again; "
    "nothing is reset for you), then run it again.",
    "remote": "`origin` could not be reached: often credentials; check that `git push` works from this shell, then rerun. The "
    "factory's Git sets `GIT_SSH_COMMAND` (no prompt), which overrides a `core.sshCommand` in your Git config: use ssh-agent or "
    "`~/.ssh/config` for the key.",
    "git": "Git could not run or answer (for a publish, an HTTPS login refused looks like this too): check that `git` and, for a "
    "publish, `git push` work from this shell, then rerun.",
    "repository": "The slot's `.git` pointer or repository is not the attempt's: inspect the slot (`git -C <slot> rev-parse "
    "--git-common-dir`); nothing was pushed.",
    "not_verified": "Only a verified step result is published: `tl step verify` first; a rejected result has nothing to publish.",
    "remote_ahead": "The remote task/<id> already holds the verified commit plus later commits: compare them; the factory does "
    "not record it as its publication and never forces.",
    "no_remote": "Add the remote (`git remote add origin <url>`) in the person's checkout, then rerun `tl step publish`.",
    "not_advanceable": "Only the task's current attempt advances, once it is verified, released with its claim kept and "
    "published, and only when its step has a following one: `tl step show` names its `Next`. A check step is not admitted "
    "while the task's abandon is half done: rerun `tl step release --abandon`.",
    "claim_lost": "The tracker no longer shows the task in progress for taskloop (claim reverted, taken by another actor, or "
    "the task closed): check `bd show <task>`; nothing retakes the claim. `tl step release --abandon` (its claim answers "
    "`not_held`), then `tl step start` admits it afresh at plan.",
    "environment": "The slot's setup (the profile's `setup`, run before an implement agent or a checks block) refused or "
    "failed; nothing after it ran. Its output is `setup-<run>.log` beside the attempt's entry.log. `exit`: a relaunch "
    "before the deadline runs it once more, two failed runs refuse `failed`; `lingering`: a process of it (its group, or a "
    "survivor of the deadline's stop) still runs, and nothing reuses or releases the slot until it is gone (the "
    "`setup_running` guide), then a relaunch runs setup again or, past the deadline, ends as `expired`; `dirty` or "
    "`moved`: setup left files in the slot or moved its HEAD (a checks slot: not detached at X), restore it (the "
    "`slot_dirty` guide); `running`: a process of an earlier setup still runs (the "
    "`setup_running` guide); `profile`: fix `.task-loop.json` on the task branch; `platform`: implement runs on Linux only; "
    "`path_long`: the agent's `TMPDIR` (`<slots root>/<repo id>/.t/<slot>`) is over 64 bytes, set a shorter `slots_root`; "
    "`roots`: a folder the agent may write (`.t/<slot>`, `.env/<slot>/uv-cache`, `.env/<slot>/uv-tools` beside the slots) "
    "resolves into the slot, its Git directories, your checkout, the artifacts or factory.db's folder, or outside the "
    "slots, by a link or by the machine config's paths: move them apart or remove the link; `sandbox`: the probe failed "
    "after those folders were made 0700 and the scratch emptied, so it is the sandbox, not their state: `codex sandbox` "
    "did not start, did not pass `TMPDIR`/`UV_OFFLINE` to its shell (a Codex config `profile` or `shell_environment_policy` "
    "can override), could not write a folder, or could write `/tmp` (Linux needs bubblewrap with unprivileged user "
    "namespaces; `codex sandbox -- true` run in `.t/<slot>` shows the error); `files`: one of those folders cannot be made "
    "or emptied, fix its permissions. Otherwise `tl step release --abandon`.",
    "setup_running": "A process of the slot's setup still runs in the process group named (from an entry that died, or left "
    "behind by a command; one recorded before a reboot never counts). Wait for it. To stop it yourself, list the group "
    "(`ps -o pid=,lstart=,command= -g <pgid>`), check each member's working directory is the slot (`lsof -a -p <pid> -d "
    "cwd`), stop only those pids, then run it again. The factory never stops it.",
    "setup_unknown": "The process table could not be read to show the slot's setup stopped: run it again.",
    "stuck:checks_refused": "The checks were relaunched twice without concluding (every relaunch the entry counts, and each "
    "round's relaunch past the deadline, `late_relaunch`; `Refused:` names the last word, the entry log says why), so rounds no "
    "longer relaunch them. Fix the cause (a check's process still running, a busy slot, the store, an entry that cannot start: "
    "its `entry.log`), then `tl step start` relaunches them by hand; or `tl step release --abandon`.",
    "check_running": "A check's process still runs in the process group named (from an entry that died, or left behind by a "
    "check: `lingering`). Wait for it. To stop it yourself, list the group (`ps -o pid=,lstart=,command= -g <pgid>`), check each "
    "member's working directory is the slot (`lsof -a -p <pid> -d cwd`), stop only those pids, then run it again. The factory "
    "never stops it.",
    "check_unknown": "The process table could not be read to show a check's process stopped: run it again.",
    "checks": "A checks entry did not conclude: `checks:running`, a check's process from an earlier entry still runs (wait for "
    "it); `unknown`, the process table could not be read; `uncertain`, a check's start could not be confirmed. A relaunch "
    "reconciles it; each relaunch counts toward `stuck:checks_refused`.",
    "no_required": "The profile at your local `main` requires no check, so nothing would decide a pass: add the required check "
    "names to `.task-loop.json` on `main`. Every done task waits (skipped each round, logged once) until then.",
    "target": "A new task branch starts at your local `main`'s tip and the required checks are read from it: `main` is "
    "missing, or its profile names another `target` (only `main` is checked yet). Fix `main`, then rerun.",
    "target_profile": "The profile at your local `main` is refused (the detail names why; `tl profile show --at main` shows it): "
    "fix `.task-loop.json` on `main`, then rerun. Every done task waits until then.",
    "commit_missing": "The implement step's commit is not in the repository any more: fetch `task/<id>` back, or `tl step "
    "release --abandon` to start the task afresh at plan.",
    "main_moved": "`main` moved while the checks ran (`Main:` shows both commits), so the required names it gave may be stale: "
    "`tl step start` re-runs the checks against `main` as it is now.",
    "branch_moved": "Restore the local task/<id> so it contains the verified commit, then rerun; or `tl step release --abandon`.",
    "remote_moved": "`git fetch origin task/<id>`, compare it with the verified commit, then rerun `tl step publish`.",
    "diverged": "The remote task/<id> does not contain the verified commit: compare them, then merge or move the remote branch "
    "aside yourself; the factory never forces.",
    "remote_rejected": "The remote's policy refused it: push the verified commit by hand (`git push origin <commit>:refs/heads/"
    "task/<id>`, never `--force`) to see why.",
    "land": LAND_NEXT["land"],
    "landed": LAND_NEXT["landed"],
    "landing": LAND_GUIDE["landing"],
    "hold": HOLD,
    "on_hold": ON_HOLD,
    "held": "A round is holding this task and has not finished (`tl step show` says what keeps it): let the next round "
    "finish the hold (`tl step next` does it now), or `tl step release --abandon` first. Then answer the hold: edit the "
    "task's description and add its label back (`tl step show` says which); `tl step start` is refused `on_hold` until then.",
}

# A checks attempt's own words for the `Next` words whose agent text would mislead (S6d): its entry is
# `taskloop.check_entry` and its commands are check process groups.
CHECKS_GUIDE = {
    "start": "Each `tl step next` round relaunches the checks entry (`taskloop.check_entry`), and so does `tl step start`. "
    "Every refusal the entry counts (`Refused:`) brings `stuck:checks_refused` nearer (two in a row). Relaunches the entry "
    "never counts (a failed or uncertain launch, an entry refusing `identity`, `stale_reservation`, `absent` or `unavailable "
    "store`, a crash before it counts) repeat each round until the deadline, as an agent attempt's do; past it each round's "
    "relaunch counts (`late_relaunch`), and the relaunched entry concludes `expired` once nothing of the attempt still runs. "
    "`tl step release --abandon` gives the task back.",
    "wait": "Its entry runs, or (the entry gone) a check's or setup's process group from it still runs: rounds wait without "
    "relaunching or counting, then relaunch once it ends. `tl step show` again.",
    "stuck:hung": "The checks entry, or a check's process group that outlived its entry, runs past the deadline (nothing ends "
    "it now). Verify before stopping anything: `ps -o command= -p <entry pid>` must show taskloop.check_entry, and each process "
    "group a `Check:` line names (`ps -o pid=,lstart=,command= -g <pgid>`) must work in the slot (`lsof -a -p <pid> -d cwd`). "
    "Stop only the pids you verified, the check groups first, then the entry; then rounds or `tl step start` relaunch it (it "
    "concludes `expired`), or `tl step release --abandon`.",
    "unsettled": "A process of the checks attempt still holds its slot (the word after `unsettled:` names it); nothing "
    "changed. Once it ends, `tl step release` again.",
    "release": "The checks concluded; their slot is still held (the last entry or `tl step release` says why: `held:check_running` "
    "waits for a check's process group, `held:slot_dirty` for files a person removes). Once the entry is gone each round "
    "retries the settled release (`check release ...`); `tl step release` does it by hand; `--abandon` also gives the task back.",
}


def guide(word: str, *, checks: bool, land: bool = False) -> str:
    """The guide of a `Next` word: a land's own (`LAND_NEXT`: its `release` is the candidate's slot) once the task has a
    land candidate, else a checks attempt's own (`CHECKS_GUIDE`) where the agent text would mislead."""
    if land and word in LAND_NEXT:
        return LAND_NEXT[word]
    return CHECKS_GUIDE.get(word, GUIDE[word]) if checks else GUIDE[word]


def discard(db: Path) -> str:
    """The last resort, naming this machine config's resolved factory.db, never another factory's."""
    return "\n".join([
        "Last resort, when `tl step release --abandon` cannot prove the attempt stopped (`worker_unknown`): the whole-DB discard:",
        "  1. stop `tl step rounds` (Ctrl-C in its terminal), then every entry and worker by verified pid (`tl step show` names them);",
        f"  2. delete {db} and its -wal/-shm (this machine config's factory.db, never another factory's);",
        "  3. in the tracker, `bd unclaim <task-id> --if-assignee taskloop` for each claimed task;",
        "  4. inspect each slot worktree, then `tl slot adopt` again.",
        "Never edit rows by hand: a deleted reservation silently fences out a still-running worker.",
    ])

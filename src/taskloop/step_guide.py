"""The fixed words a person reads around the step commands: which steps are built, what each `Next` word or refusal asks
them to do, and the whole-DB discard steps. Text only; `step_render` places it, every decision is an operation's."""

from pathlib import Path

STEP_ONLY = "steps built: plan, implement; publishes task/<id>; no merge or land"
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
          "each round advances claimed tasks whose step is done to their next step, then starts approved ready tasks; "
          f"the tracker is read only when a slot is free; writes `<artifacts>/rounds.log`; {STEP_ONLY}. Runs in this terminal "
          "until stopped: Ctrl-C once stops after the current move, twice exits at once; launched steps keep running. A move "
          "in flight finishes first: a verify waits for its publish push (up to Git's timeout). While every slot is held "
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
    "gives the task back.",
    "abandoned": "Abandoned: the slot is free and the claim was returned (`Claim:` says if not). `tl step start` admits a fresh "
    "attempt.",
    "publish": PUBLISH,
    "advance": "The step is verified and on `origin`. The next `tl step next` round (or `tl step rounds`) starts the next step "
    "once a slot is free, before any new task, oldest first; by hand, `tl step start <task>`. Either way one tracker read "
    "first confirms the task is in progress for taskloop (no new claim, no label check: removing the label does not stop it, "
    "`tl step release --abandon` does); it starts from that published commit.",
    "done": "Collected: `succeeded` tells whether the step's result was verified.",
    "unknown": "The entry or the store could not be read; run `tl step show` again.",
    "stuck:expired_admitted": f"Nothing ran; rounds only report it. {ABANDON} Then `tl step start` admits a "
    "fresh attempt. Its deadline passed with no relaunchable entry from before a reboot (none registered, one from this boot, or "
    "the boot unknown); such an entry would instead be relaunched with the deadline renewed once from --minutes.",
    "failed": "The step ended without a verified result; the claim stays held, so rounds never retry it. Read `tl step show`; "
    "to try it afresh, `tl step release --abandon` then `tl step start`.",
    "running": "Its entry runs; the round leaves it alone.",
    "attempted": "Open in the tracker while factory.db holds its attempt: the claim was returned or lapsed. `tl step show` it; "
    "rounds never take it again.",
    "abandoned_skip": "Abandoned here: rounds never re-admit it; `tl step start` admits a fresh attempt.",
    "no_free_slot": "Every slot is held: `tl step rounds` fills it seconds after a slot frees; by hand, the next `tl step next` "
    "after a step ends.",
    "rounds_running": "Another `tl step rounds` runs for this backlog (the pid is its lock record's, informational): use its "
    "terminal, or stop it there with Ctrl-C first. `tl step next` runs beside it.",
    "interval": "The rounds interval (`--every`, machine config `round_seconds`) is whole seconds, at least 5.",
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
    "task": "The task could not be read from the tracker named by the attempt's tracker root (deleted, malformed, or the root no "
    "longer resolves): check `bd show <task>` there. Rounds skip it every round; `tl step release --abandon` gives it up.",
    "changed": "Another attempt of the task became current since the round read the store; the next round follows it (`tl step show`).",
    "unsettled": "The slot has files the step did not commit (listed), or the slot pointer or HEAD changed. Remove the "
    "listed files and `tl step verify`, or run `tl step start` again to repeat the step; for `redirected` or `head_moved` "
    "inspect first; for `worker_alive` stop the worker first; for `staged` unstage the listed paths first.",
    "registration_conflict": "Another start registered its entry first; `tl step show` follows that attempt.",
    "slot_busy": "Another entry or verify holds the slot: wait and run it again; if nothing ends, see the `stuck:hung` guide.",
    "lock": "The slot's lock file under `<slots root>/<repo id>/.locks` cannot be created: fix that folder's permissions.",
    "not_terminal": "The step has not ended: wait for it, `tl step start` to repeat it, or `tl step release --abandon`.",
    "entry_running": "Its entry runs: wait, or stop it by verified pid (the `stuck:hung` guide), then run it again.",
    "worker_unknown": "Dispatched with no agent recorded, so it cannot be shown stopped: the whole-DB discard is the only way out.",
    "slot_dirty": "The slot stays held: remove the listed files (nothing is reset for you), then run it again.",
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
    "published, and only when its step has a following one: `tl step show` names its `Next`.",
    "claim_lost": "The tracker no longer shows the task in progress for taskloop (claim reverted, taken by another actor, or "
    "the task closed): check `bd show <task>`; nothing retakes the claim. `tl step release --abandon` (its claim answers "
    "`not_held`), then `tl step start` admits it afresh at plan.",
    "environment": "The slot's setup (the profile's `setup`, run before an implement agent) refused or failed; the attempt "
    "stays admitted and no agent ran. Its output is `setup-<run>.log` beside the attempt's entry.log. `exit` or `lingering`: "
    "the next relaunch runs it once more, two failed runs refuse `failed`; `dirty` or `moved`: setup left files in the slot "
    "or moved its HEAD, restore it (the `slot_dirty` guide); `running`: a process of an earlier setup still runs (the "
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
    "branch_moved": "Restore the local task/<id> so it contains the verified commit, then rerun; or `tl step release --abandon`.",
    "remote_moved": "`git fetch origin task/<id>`, compare it with the verified commit, then rerun `tl step publish`.",
    "diverged": "The remote task/<id> does not contain the verified commit: compare them, then merge or move the remote branch "
    "aside yourself; the factory never forces.",
    "remote_rejected": "The remote's policy refused it: push the verified commit by hand (`git push origin <commit>:refs/heads/"
    "task/<id>`, never `--force`) to see why.",
}


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

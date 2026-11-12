"""The fixed words a person reads around `tl step land` (tl-8bh9.14.8 sections 14 and 16): the `Next` words a land gives
(`land`, `landed`, a land's `release`) and one guide per land refusal or unknown word. Text only; `land_render` and
`step_render` place it. A word the land shares with the other step commands (`claim_lost`, `remote_rejected`, `target`,
...) has its land meaning here: `land_render` reads this table before `step_guide.GUIDE`."""

from typing import Final

# The one recovery from a conflict (or a failed validation that needs new code): a new chain on the current main. The task
# branch is the chain's memory, so the stale one is set aside (locally and on origin) and local `main`, where a new branch
# starts, is brought up to date first; the old commits stay on `old/task/<id>`.
RESTART: Final = (
    "start the task again on the current main, in your checkout: `git switch main && git pull --ff-only`; `git branch -m "
    "task/<id> old/task/<id>`; `git push origin --delete task/<id>`; then `tl step release --abandon` and `tl step start` "
    "(plan and implement run again on the new main; the old commits stay on `old/task/<id>`)."
)
RERUN: Final = "Nothing was lost: rerun `tl step land` (a rerun does only what is missing)."
INTERRUPTED: Final = "interrupted"  # `tl step land` stopped by Ctrl-C (`cli_step._land`): exit 130, the rerun reconciles

# The `Next` words of a land; `step_guide.GUIDE` carries `land` and `landed` (a status without a candidate shows them too).
LAND_NEXT: Final = {
    "land": "The checks passed, or a land is under way: read the diff and `tl step land TASK --summary`, then `tl step land "
    "TASK`. It fetches origin's main, squashes X onto it as one commit S, runs every check again on S in a free slot (in "
    "your shell) only when main moved or its required names changed, pushes S to origin's main as you, never forced, and "
    "closes the task in your local tracker. Rounds never land; a rerun does only what is missing.",
    "landed": "S is on origin's main and the task is closed in your local tracker: nothing is left. Run `git pull --ff-only` in "
    "your checkout; `bd dolt push` shares the tracker if others read it. (From `tl step release --abandon`: the code is on "
    "main, nothing to abandon; if `tl step show` still says `Next: land`, rerun `tl step land` to finish the close.)",
    "release": "The land's candidate still holds its slot (its release was held: `held:check_running` waits for a check's "
    "process group, `held:slot_dirty` for files a person removes, `held:slot_redirected` for a rewritten slot pointer). "
    "`tl step land` retries the release first and then finishes the land; `tl step release TASK` releases it alone; rounds "
    "only report it.",
}

LAND_GUIDE: Final = {
    **LAND_NEXT,
    "unavailable": RERUN,
    INTERRUPTED: "The land was interrupted (Ctrl-C) and stopped where it was; a check it was running was stopped with it, and "
    "the rerun marks that check `interrupted` and repeats its block whole.",
    "push_barred": "This shell carries an agent's push bar: run `tl step land` from your own shell.",
    "not_done": "The task's implement step is not done (verified, released with its claim kept, published): `tl step show "
    "TASK` names its next step.",
    "not_checked": "The task's checks have not passed and been released: finish them (`tl step show TASK`), re-run failed ones "
    "with `tl step start`, or `tl step release --abandon`. `--no-change` accepts any concluded checks.",
    "landing": "A land candidate of the task is being validated, still holds its slot, or is validated and may already be on "
    "origin's main: `tl step land` finishes it (it retries a held release first); `tl step land --withdraw` gives a "
    "validated, undelivered one up; `tl step release TASK` frees a slot a land left held. Then abandon if you still want to.",
    "not_landing": "No validated, undelivered candidate: nothing to withdraw. `tl step show TASK` shows the land.",
    "land_running": "Another `tl step land` of this task still runs (`Land process:` names its pid): wait for it, then rerun.",
    "observe": "The process table could not be read to show the earlier land process stopped: rerun.",
    "no_change": "origin's main already holds X's changes (a hand land, say): confirm with `git log origin/main`, then `tl step "
    "land TASK --no-change` records it and closes the task.",
    "changes": "There is something to land: drop `--no-change`.",
    "conflict": f"X does not merge onto origin's main: {RESTART}",
    "checks_failed": "A check failed on S (the `Land check:` lines and logs say which): rerun `tl step land` if it is flaky; "
    f"otherwise {RESTART} Nothing was pushed.",
    "target_moved": "Rerun `tl step land`: it squashes X onto the new main as a new candidate and runs the checks again on it "
    "when its tree differs from X's (a slot and the checks' time).",
    "no_remote": "The checkout has no `origin`: add it (`git remote add origin <url>`), then rerun.",
    "branch_moved": "`task/<id>` (local or on origin) is not exactly the checked X: reset it to X, or `tl step release "
    "--abandon` and restart to check the new commits. `--withdraw` and `--no-change` skip this rule.",
    "commit_missing": "The checked commit X is not in the repository any more: fetch `task/<id>` back, or abandon and restart.",
    "target": "origin has no `main`, or main's `.task-loop.json` names another `target` (only `main` lands): fix main, then "
    "rerun.",
    "target_profile": "The profile at origin's main is refused (the detail says why): fix `.task-loop.json` on main, then rerun.",
    "no_required": "origin main's profile requires no check, so nothing would decide a pass: add the required names to "
    "`.task-loop.json` on main, then rerun.",
    "remote_rejected": "Push S by hand to read origin's reason (`git push origin <S>:refs/heads/main`, never `--force`): often a "
    "protected main that requires a pull request (PR mode is held), signed commits or a server hook. After a hand push of "
    "that S, rerun `tl step land`: it finds S on main, records it and closes the task.",
    "remote": "origin could not be fetched or pushed (often credentials): check that `git fetch` and `git push` work from this "
    f"shell. {RERUN}",
    "git": "Git could not answer (reading your checkout, making S, or resetting the candidate's slot): check that `git` works "
    f"in your checkout and the slot. {RERUN}",
    "tracker": f"The tracker could not be read or could not close the task. {RERUN}",
    "store": f"factory.db could not be read or written now. {RERUN}",
    "claim_lost": "The tracker no longer shows the task in progress for taskloop (another actor took it, or its claim "
    "lapsed): inspect it (`bd show <task>`). Before the push nothing was pushed: `tl step release --abandon`. After the push "
    "the detail names the `bd close` that works; a rerun then records it.",
    "closed": "The task is closed in the tracker without a land: inspect it (`bd show <task>`); reopen it to land, or abandon.",
    "blocked": "bd refuses the close (an open child or blocker, named in the detail): close or unblock it, or `bd close <task> "
    "--force`; a rerun then closes or records it. The code is already on main.",
    "task": "The tracker has no such task: inspect the attempt's tracker root (`bd show <task>`).",
    "checkout": "--checkout is not a checkout of the task's repository: pass your own checkout of it.",
    "minutes": "S needs validating (main moved or its required names changed): rerun with `--minutes N`, the validation's deadline.",
    "choices": "Fix the flags: `--minutes` from 1 to the maximum; `--summary`, `--withdraw` and `--no-change` exclude each other.",
    "slot_busy": "Another land or entry holds the candidate's slot: wait for it, then rerun.",
    "no_free_slot": "Every slot is held and S must be validated in one: rerun once a slot is free, or stop `tl step rounds`.",
    "checks": "A check of an earlier land process still runs (`checks:running`, see `Land check:`), or the process table could "
    "not be read (`checks:unknown`): wait for it to end, then rerun; the block repeats whole.",
    "changed": f"The land candidate changed meanwhile (another land or release). {RERUN}",
    "abandoned": "The task's checks were abandoned: nothing lands; `tl step start` admits it afresh at plan.",
    "unsettled": "A process of the land's validation still holds its slot (named after `unsettled:`): wait for it, then rerun "
    "`tl step land`, which retries the release first.",
    "entry_running": "The candidate's land process still runs (its pid is in the detail; `tl step show` names it): wait for "
    "that `tl step land` to end, or stop it by verified pid, then rerun.",
    "not_terminal": "The land's validation has not concluded: rerun `tl step land` to finish it, or `tl step release "
    "--abandon`.",
    "profile": "The profile at S is refused (the detail says why): fix `.task-loop.json` on the task branch (abandon and "
    "restart) or on main.",
    "refused": "The land refused to go on; the detail and the guide above say what to fix, then rerun `tl step land`.",
    "abandoning": "The task's abandon stopped half way (its land candidate is abandoned, its checks attempt not yet): rerun "
    "`tl step release TASK --abandon` to finish it; `tl step land` refuses until then, so nothing lands against it.",
    "absent": "The land candidate's slot is no longer held by it (released or never reserved): `tl step show TASK`, then rerun.",
    "land_changed": f"Another land of the task recorded its delivery or close first. {RERUN}",
    "stale_reservation": f"The candidate's slot reservation changed meanwhile (released or taken over). {RERUN}",
    "check_changed": f"A check result of the validation was written by another process meanwhile. {RERUN}",
    "setup_changed": f"The validation's setup run was written by another process meanwhile. {RERUN}",
    "lock": "The slot's lock file under `<slots root>/<repo id>/.locks` cannot be created: fix that folder's permissions, then "
    "rerun.",
    "slot_dirty": "The candidate's slot has files the release will not remove (listed): remove them, then rerun `tl step land` "
    "(it retries the release first) or `tl step release TASK`.",
    "slot_branch": "The candidate's slot is on a branch, not detached: `git -C <slot> switch --detach`, then rerun.",
    "slot_unborn": "The candidate's slot has no commit: inspect it (`git -C <slot> log -1`), then rerun.",
    "slot_redirected": "The candidate's slot `.git` pointer was rewritten (by a check's code, say): inspect and restore it, then "
    "rerun; nothing was reset.",
    "repo": "The candidate's slot is not a worktree of the task's repository: inspect it (`git -C <slot> rev-parse "
    "--git-common-dir`), then rerun.",
    "not_listed": "The candidate's slot is not listed by `git worktree list` any more: restore it, then rerun.",
    "deadline": "--minutes is out of range: from 1 to the maximum.",
    "expired": "The validation's deadline passed: rerun `tl step land` (a rerun renews it from --minutes).",
    "environment": "S's `setup` refused or failed in the slot (its `setup-<run>.log` beside the candidate's check logs says why): "
    "fix it on the task branch or main, then rerun.",
    "check_running": "A check of the land's validation still runs in the process group named: wait for it (or stop only its "
    "verified pids), then rerun.",
    "setup_running": "The validation's setup still runs in the process group named: wait for it (or stop only its verified "
    "pids), then rerun.",
    "check_unknown": f"The process table could not be read to show a check stopped. {RERUN}",
    "setup_unknown": f"The process table could not be read to show the setup stopped. {RERUN}",
}

RELEASE_RERUN: Final = "Nothing changed: rerun `tl step release` (with `--abandon` if you were abandoning)."

# A land candidate's release by `tl step release` (`--abandon` or not): its words where the step commands' would mislead.
CANDIDATE_RELEASE: Final = {
    "unavailable": RELEASE_RERUN,
    "entry_running": "The candidate's land process (`tl step land`) still runs: wait for it to end, or stop it by verified pid "
    "(`ps -o command= -p <pid>` shows `tl ... step land`), then rerun `tl step release`.",
    "not_terminal": "The land's validation has not concluded: rerun `tl step land` to finish it, or `tl step release --abandon` "
    "to give the task back.",
    "unsettled": "A process of the land's validation still holds the candidate's slot (named after `unsettled:`): wait for it, "
    "then rerun `tl step release`.",
    "changed": "The land candidate changed meanwhile (a land or another release): rerun `tl step release`.",
}

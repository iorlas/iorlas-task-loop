"""The fixed words a person reads around `tl step land` (tl-8bh9.14.8 sections 14 and 16): the `Next` words a land gives
(`land`, `landed`, a land's `release`) and one guide per land refusal or unknown word. Text only; `land_render` and
`step_render` place it. A word the land shares with the other step commands (`claim_lost`, `remote_rejected`, `target`,
...) has its land meaning here: `land_render` reads this table before `step_guide.GUIDE`."""

from typing import Final

RERUN: Final = "Nothing was lost: rerun `tl step land` (a rerun does only what is missing)."

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
    "conflict": "X does not merge onto origin's main: merge `main` into `task/<id>` by hand and push it, then `tl step release "
    "--abandon` and `tl step start` (the restarted steps check the merge).",
    "checks_failed": "A check failed on S (the `Land check:` lines and logs say which): rerun `tl step land` if it is flaky; "
    "otherwise fix it as for a conflict (merge `main` into `task/<id>`, abandon, restart). Nothing was pushed.",
    "target_moved": "origin's main moved during the land: rerun `tl step land` (a new candidate onto the new main, validated "
    "when its tree differs). Nothing was pushed.",
    "push_url": "origin pushes elsewhere than it fetches from: make them one (`git remote get-url --push origin` against `git "
    "remote get-url origin`), or land by hand.",
    "no_remote": "The checkout has no `origin`: add it (`git remote add origin <url>`), then rerun.",
    "branch_moved": "`task/<id>` (local or on origin) is not exactly the checked X: reset it to X, or `tl step release "
    "--abandon` and restart to check the new commits. `--withdraw` and `--no-change` skip this rule.",
    "commit_missing": "The checked commit X is not in the repository any more: fetch `task/<id>` back, or abandon and restart.",
    "target": "origin has no `main`, or main's `.task-loop.json` names another `target` (only `main` lands): fix main, then "
    "rerun.",
    "target_profile": "The profile at origin's main is refused (the detail says why): fix `.task-loop.json` on main, then rerun.",
    "no_required": "origin main's profile requires no check, so nothing would decide a pass: add the required names to "
    "`.task-loop.json` on main, then rerun.",
    "remote_rejected": "origin refused the push by its own policy (a protected main that requires a pull request, signed "
    "commits, a hook): land by hand to see why (`git push origin <S>:refs/heads/main`, never `--force`); PR mode is held.",
    "remote": "origin could not be fetched or pushed (often credentials): check that `git fetch` and `git push` work from this "
    f"shell. {RERUN}",
    "git": f"Git could not read the checkout or make S: check that `git` works in your checkout. {RERUN}",
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
}

"""Prose guidance for land status, refusals and candidate release; renderers select the words here."""

from typing import Final


def restart(task_id: str = "<id>", x: str = "<X>") -> str:
    """Explain a fresh plan on current main while preserving the previous task branch."""
    aside = f"old/{task_id}-{x[:12]}"
    return (
        f"decide whether to start the task again from plan on the current main. Preserve the old task/{task_id} branch, "
        f"including saved work, locally as {aside} before retiring its published branch and abandoning the old attempt. "
        "Bring local main up to date first; if it contains unpublished commits, decide where to preserve them before "
        "starting the new plan and implementation."
    )


RERUN: Final = "Nothing was lost. Retrying the land reconciles recorded progress and completes only the missing work."
INTERRUPTED: Final = "interrupted"  # Interruption identity shared with the command entry and exit-code mapping.

LAND_NEXT: Final = {
    "land": "The checks passed and the change waits to be landed, or a land is already under way. With automatic land in "
    "the repository profile, the next round integrates the change onto origin's main, validates it again when main or the "
    "required checks changed, pushes without replacing remote history, and closes the task. A conflict or failed validation "
    "holds the task with its cause. Manual land is the default: a person decides when to proceed, and rounds reserve the "
    "last free slot for that work. Retrying completes only the missing work.",
    "landed": "The change is on origin's main and the task is closed in the local tracker. Nothing remains to land. "
    "The factory leaves your checkout untouched; refresh it before working there and share the tracker changes if others "
    "need them. If the status still waits for land, retrying finishes recording the close; delivered code cannot be abandoned.",
    "release": "The land candidate still holds its slot. Release waits for a check process to stop, retained files to be "
    "handled, or a rewritten slot pointer to be restored. Decide whether to finish the land, which retries release first, "
    "or release the slot alone. Rounds only report this situation.",
}

LAND_GUIDE: Final = {
    **LAND_NEXT,
    "unavailable": RERUN,
    INTERRUPTED: "The land was interrupted and stopped where it was; a running check was stopped with it. Retrying marks "
    "that check interrupted and repeats its whole block.",
    "push_barred": "This agent session is barred from pushing. A person must decide whether to land from their own session.",
    "not_done": "The implementation has not been accepted by factory commit, released with its claim kept, and published. "
    "Review the task's next step and finish that work before deciding to land.",
    "not_checked": "The task's checks have not passed and been released. Decide whether to finish or retry the checks, "
    "abandon the attempt, or confirm that the change is already integrated after the checks have concluded.",
    "landing": "A land candidate is being validated, still holds its slot, or may already be delivered. Decide whether to "
    "finish it, withdraw a validated candidate that has not been delivered, or release its retained slot before abandoning.",
    "not_landing": "There is no validated, undelivered candidate to withdraw. Review the recorded land before deciding what remains.",
    "land_running": "Another land of this task still runs; its process identity is recorded. Wait for it before retrying.",
    "observe": "The process table could not confirm that the earlier land stopped. Restore process observation before retrying.",
    "no_change": "Origin's main already contains the checked change. Review its history and decide whether to confirm that "
    "integration so the factory can record it and close the task.",
    "changes": "The checked change still needs delivery. Proceed with integration rather than confirming an existing delivery.",
    "gate_changed": "The change alters what decides a pass, such as checks, setup, required names, configuration or tests. "
    "The task waits for a person to review the diff and accept those changes, or revise the task branch and restart.",
    "conflict": "Conflict work has stopped delivery. Review the retained work and its explanation before deciding how the task "
    "continues. A retained resolution is not checked or delivered work. Under automatic land the factory holds the task.",
    "checks_failed": "A check failed on the change as integrated onto current main; the check results and logs identify it. "
    "Automatic land holds the task. A person may retry a flaky check; otherwise " + restart() + " Nothing was pushed.",
    "target_moved": "Main changed during delivery. Retrying integrates the checked change onto the new main as a new "
    "candidate and repeats validation when its tree differs from the checked commit, requiring a slot and time for checks.",
    "no_remote": "The checkout has no origin remote. Choose and configure the repository's origin before retrying.",
    "branch_moved": "The task branch, locally or on origin, differs from the checked commit. Decide whether to restore that "
    "commit or abandon and restart to check the new work. Withdrawal and confirmation of existing integration do not require this match.",
    "commit_missing": "The checked commit is no longer available locally. Restore it from the published task branch, "
    "or abandon and restart.",
    "target": "Origin has no main branch, or main's profile selects an unsupported target. Restore main and its target "
    "settings before retrying.",
    "target_profile": "The profile at origin's main was refused; the detail explains why. Correct that profile before retrying.",
    "no_required": "Origin main's profile requires no checks, so nothing would decide a pass. Choose the required checks "
    "in that profile first.",
    "remote_rejected": "Origin refused the push by its own policy. Automatic land holds the task. Review the remote's "
    "explanation and decide how to satisfy its delivery policy, which may require a pull request, signed commits or a server "
    "hook. Preserve remote history. If the same validated candidate is delivered manually, retrying records it and closes the task.",
    "remote": "Origin could not be fetched or pushed. Restore remote access, including credentials, before retrying. " + RERUN,
    "git": "Git could not read the checkout, create the candidate or reset its slot. Restore repository access in the checkout "
    "and slot before retrying. " + RERUN,
    "tracker": "The task tracker could not be read or could not close the task. Restore tracker access before retrying. " + RERUN,
    "store": "The factory database could not be read or written. Restore database access before retrying. " + RERUN,
    "claim_lost": "The factory no longer owns the task's claim. Review the current ownership before deciding to abandon "
    "undelivered work or arrange the task's close after delivery. Retrying then records confirmed progress.",
    "closed": "The task is already closed without a recorded land. Review the tracker and decide whether to reopen it "
    "for delivery or abandon.",
    "blocked": "The tracker refused closure because a child or blocker remains open. The code is already on main. Resolve "
    "the blocker or explicitly authorize closure despite it; retrying then closes the task or records its confirmed close.",
    "task": "The tracker has no such task. Check which tracker the attempt belongs to before deciding how to proceed.",
    "checkout": "The supplied directory is not a checkout of the task's repository. Choose a checkout of that repository.",
    "minutes": "Land needs a time limit for validation or conflict resolution. Choose a duration before starting this work.",
    "choices": "The requested land choices conflict or the duration is invalid. Choose a duration within the allowed range "
    "and only one of reviewing the summary, withdrawing a candidate or confirming existing integration.",
    "slot_busy": "Another land or entry holds the candidate's slot. Wait for it before retrying.",
    "no_free_slot": "No slot is free and the candidate needs one. Wait for a usable slot, or decide whether to stop rounds "
    "to free capacity.",
    "checks": "An earlier land's check still runs, or process observation cannot confirm it stopped. Wait for confirmed "
    "completion before retrying; the whole check block repeats.",
    "changed": "Another land or release changed the candidate meanwhile. " + RERUN,
    "abandoned": "The task's checks were abandoned, so nothing lands. Decide whether to start a fresh attempt from plan.",
    "unsettled": "A validation process still holds the candidate's slot. Wait for it to stop before retrying land, "
    "which retries release first.",
    "entry_running": "The candidate's land process still runs. Wait for it, or stop only the confirmed owning process, before retrying.",
    "not_terminal": "The land's validation has not concluded. Decide whether to finish it or abandon the attempt.",
    "profile": "The candidate's profile was refused; the detail explains why. Correct the profile on main or revise the "
    "task branch and restart.",
    "refused": "Land refused to continue. Review the detail and the specific guide, resolve the cause, then decide whether to retry.",
    "abandoning": "Abandoning stopped after the land candidate was abandoned but before its checks attempt was. Finish "
    "abandoning; delivery remains refused until that is complete.",
    "absent": "The candidate no longer holds its slot, or never reserved it. Review the recorded status before retrying.",
    "land_changed": "Another land recorded delivery or closure first. " + RERUN,
    "stale_reservation": "The candidate's slot reservation was released or taken over meanwhile. " + RERUN,
    "check_changed": "Another process recorded a validation check result meanwhile. " + RERUN,
    "setup_changed": "Another process recorded the validation's setup result meanwhile. " + RERUN,
    "lock": "The slot's lock file cannot be created. Restore permissions on its lock directory before retrying.",
    "slot_dirty": "The candidate's slot contains files release will preserve. Review and preserve or remove those files, "
    "then decide whether to finish land, which retries release first, or release the slot alone.",
    "slot_branch": "The candidate's slot is attached to a branch. Restore its detached checkout before retrying release.",
    "merge_pending": "The slot has an active merge. Its owning operation retains it until preservation and process stop are confirmed.",
    "slot_unborn": "The candidate's slot has no commit. Review and restore its checkout before retrying.",
    "slot_redirected": "The candidate's slot pointer was rewritten. Review and restore it before retrying; nothing was reset.",
    "repo": "The candidate's slot is not a worktree of the task's repository. Review and restore its repository association "
    "before retrying.",
    "not_listed": "Git no longer lists the candidate's slot as a worktree. Restore its registration before retrying.",
    "deadline": "The validation duration is outside the allowed range. Choose a duration between one minute and the maximum.",
    "expired": "The validation deadline passed. Decide whether to retry with a renewed deadline using the chosen duration.",
    "log": "The validation's artifacts directory cannot be written. Restore permissions or free space before retrying. "
    "The task branch and main remain intact. " + RERUN,
    "environment": "The candidate's setup was refused or failed in its slot; its setup log explains why. Correct the "
    "environment on the task branch or main before retrying.",
    "check_running": "A validation check still runs in the recorded process group. Wait for it, or stop only its confirmed "
    "owning processes, before retrying.",
    "setup_running": "The validation's setup still runs in the recorded process group. Wait for it, or stop only its "
    "confirmed owning processes, before retrying.",
    "check_unknown": "Process observation could not confirm that a check stopped. Restore observation before retrying. " + RERUN,
    "setup_unknown": "Process observation could not confirm that setup stopped. Restore observation before retrying. " + RERUN,
}

RELEASE_RERUN: Final = "Nothing changed. Retry the release, keeping the decision to abandon if that was already chosen."

CANDIDATE_RELEASE: Final = {
    "unavailable": RELEASE_RERUN,
    "entry_running": "The candidate's land process still runs. Wait for it, or stop only the confirmed owning process, "
    "before retrying release.",
    "not_terminal": "The land's validation has not concluded. Decide whether to finish land or abandon the attempt and return the task.",
    "unsettled": "A validation process still holds the candidate's slot. Wait for it to stop before retrying release.",
    "changed": "Another land or release changed the candidate meanwhile. Review the recorded progress before retrying release.",
}

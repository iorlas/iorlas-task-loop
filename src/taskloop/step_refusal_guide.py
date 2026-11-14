"""Reason-specific guidance for step refusals, kept apart from the status/Next prose."""

REFUSALS = {
    "dirty": "The slot has retained changes. Inspect and settle them before verification; preserve needed work.",
    "slot_head_moved": "The slot HEAD moved from its expected commit. Inspect and restore the expected commit before continuing.",
    "ref_moved": "The task branch moved while work was being saved. Preserve the slot and reconcile its branch before release.",
    "repo": "The slot belongs to another repository. Restore the expected repository binding before continuing.",
    "not_listed": "The slot is no longer a listed worktree. Restore its registration before continuing.",
    "land_running": "The owning land process still runs. Wait for it to finish before changing the candidate.",
    "database": "No readable factory.db was found. Check the configured database path; slot adoption initializes a new factory.",
    "schema": "This database belongs to a different runtime schema. Preserve the upgrade explanation above; drain "
    "with the matching runtime before the owner decides on an upgrade.",
    "backlog": "The backlog is missing, ambiguous or invalid. Select the configured backlog key explicitly; "
    "inspect the available backlogs above.",
    "label": "An approval label is required. Select the label whose tasks the owner approved for the factory.",
    "bad_label": "The approval label is invalid. Choose a non-blank label accepted by the task tracker.",
    "tracker_root": "The tracker root cannot be used. Check the explicitly configured tracker directory and its access permissions.",
    "choices": "The requested options are invalid. Correct the values named above using the command's help.",
    "checkout": "The checkout is absent or belongs to another repository. Select an existing checkout of the task's repository.",
    "input": "The agent input could not be prepared. Inspect the supplied detail and the artifacts directory's "
    "permissions and free space before starting work.",
    "claimed_elsewhere": "Another actor holds the tracker claim. Leave its work intact and wait for that actor's decision.",
    "constraint": "Admission conflicted with a retained reservation or task. Inspect the current attempt and "
    "slots before deciding which work may proceed.",
    "deadline": "The requested deadline is outside the supported range. Choose a positive --minutes value within "
    "the command's maximum.",
    "expired": "The attempt's deadline has passed. Inspect its retained evidence and current status before "
    "deciding whether to abandon or continue it.",
    "registration_refused": "The entry registration was refused by the retained attempt state. Inspect the "
    "current attempt before allowing another launch.",
    "dispatched": "This attempt was already dispatched. Observe its existing entry and evidence; a second worker "
    "must not be launched.",
    "observe": "Process identity could not be established. Wait for reliable process observation; do not release "
    "or stop an unverified process.",
    "store": "Local execution state could not be read or recorded. Check database access and free space, preserve "
    "the database and evidence, then inspect again.",
    "log": "The entry or check log could not be opened. Check the artifacts directory's permissions and free "
    "space; preserve existing evidence.",
    "launch": "The entry launch is uncertain and may already be running. Inspect the registered entry before "
    "deciding on another launch.",
    "exec_failed_after_commit": "The entry was registered but execution failed. Inspect the registered entry and "
    "its log before relaunching it.",
    "absent": "No retained attempt exists in the selected scope. Check the task ID, backlog and database path "
    "before starting new work.",
    "tracker": "The task tracker could not answer reliably. Check its supplied explanation and access to the "
    "configured tracker before proceeding.",
    "not_repeatable": "The current attempt cannot be repeated in this state. Inspect its status and settle or "
    "abandon it before starting another attempt.",
    "repeat_cap": "The step has used its allowed repeats. Inspect the retained work and decide whether to settle or abandon it.",
    "task_attempted": "A retained attempt already owns this task. Inspect that attempt and continue its existing work.",
    "branch_name": "The task ID cannot form a safe task branch name. Correct the task identity before admission.",
    "branch_held": "Another worktree holds the task branch. Preserve that work and resolve its ownership before admission.",
    "branch_diverged": "The task branch and its remote history diverged. Compare and reconcile their commits before admitting work.",
    "branch_unpublished": "The task branch has unpublished retained work. Inspect and publish or deliberately set "
    "aside that work before continuing.",
    "stale_reservation": "The attempt no longer owns the slot reservation. Inspect the current owner; do not "
    "change another attempt's slot.",
    "worker_alive": "The worker or its process group still runs. Wait for it to stop; any manual stop requires "
    "verifying its identity first.",
    "slot_branch": "The slot is on an unexpected branch. Inspect and restore its expected branch before releasing it.",
    "slot_unborn": "The slot has no HEAD commit. Inspect and restore its expected commit before continuing.",
    "slot_redirected": "The slot's Git pointer changed. Restore the verified repository pointer; preserve the slot and its evidence.",
    "slot_staged": "The slot has staged changes. Inspect and settle those changes before continuing; the factory "
    "will not discard them.",
    "slot_detached": "The task slot is unexpectedly detached. Restore the task branch containing the attempt's "
    "work before verification.",
    "not_captured": "No agent result has been captured. Wait for the entry, then inspect its evidence if it has stopped.",
    "no_base": "The attempt has no retained admission base. Preserve its evidence and ask the owner to resolve "
    "the inconsistent state.",
    "session": "The recorded session conflicts with the answer. Preserve the transcript and ask the owner to resolve it.",
    "session_pending": "The session is not complete yet. Wait for collection before verification.",
    "session_fault": "The session could not be collected. Preserve its evidence and inspect the supplied "
    "diagnostic before proceeding.",
    "validation_pending": "Answer validation has not completed. Wait for the owning entry to finish collection.",
    "inconsistent": "The retained facts do not produce a consistent verdict. Preserve all evidence and ask the owner to investigate.",
    "read_only": "Verification requires writes but this reader is read-only. Use the owning step verification "
    "operation after inspecting status.",
    "released": "The attempt has already released its slot. Inspect the current task status before starting its next step.",
    "uncommitted": "The attempt left uncommitted work. Inspect and settle the listed files before verification or release.",
    "unsafe": "The attempt left paths the factory cannot safely settle. Inspect the listing and preserve needed "
    "work before resolving it.",
    "ignored": "Ignored files remain in the slot. Inspect them and preserve needed data before clearing the slot.",
    "head_moved": "The slot HEAD moved away from the attempt's commit. Inspect and restore the expected commit before continuing.",
    "branch": "The slot is on an unexpected branch. Restore the attempt's expected branch before verification.",
    "unborn": "The slot has no commit. Restore the attempt's expected commit before verification.",
    "redirected": "The slot points at another Git directory. Restore its verified pointer before continuing.",
    "staged": "Staged changes prevent settlement. Inspect the staged files and settle them before continuing.",
    "superseded": "A newer attempt superseded this work. Inspect the current attempt; this one cannot be settled again.",
    "changed_admission": "Admission changed during this operation. Inspect the winning attempt before continuing.",
    "changed_answer": "The captured answer changed during verification. Preserve the evidence and inspect the current result.",
    "check_changed": "Another process recorded the check result first. Inspect the current check result before continuing.",
    "setup_changed": "Another process recorded the setup result first. Inspect the current setup result before continuing.",
    "land_changed": "Another process changed the land candidate. Inspect the current candidate before continuing.",
    "unlabelled": "The required approval label is absent. The owner must decide whether to approve this task before admission.",
    "unregistered_entry": "The entry identity was never registered. Preserve evidence and inspect the owning "
    "attempt before allowing execution.",
    "unregistered_worker": "The worker identity was never registered. Preserve evidence; execution cannot be assumed stopped.",
    "worker_mismatch": "The worker identity differs from the registered owner. Preserve evidence and resolve "
    "process ownership before continuing.",
    "check_profile": "The failed checks and their profile do not agree or cannot be read. Inspect the checked "
    "commit's profile before deciding on an implement repeat.",
    "check_feedback": "The failed check's evidence is missing or invalid. Preserve the check logs and inspect "
    "them before deciding on an implement repeat.",
    "draining": "New work is blocked by the durable drain request. Existing work remains intact; wait for "
    "verified idle and the owner's restart or upgrade decision.",
    "drained": "Idle was verified and new work remains blocked. The owner must decide whether to restart or upgrade.",
    "interrupted": "The operation was interrupted. Existing executions and evidence remain intact; inspect "
    "current state before continuing.",
    "dashboard_port": "The local dashboard port cannot be bound. Select a free local port or resolve the existing "
    "listener's ownership.",
}

# Compound reason domains carry different remedies, even when the surrounding operation is the same.
REFUSALS.update({
    "environment:dirty": "Setup left changes in the slot. Inspect and preserve needed files, then restore the expected clean state.",
    "environment:moved": "Setup moved the slot HEAD or branch. Restore the expected commit and branch before continuing.",
    "environment:failed": "Setup exhausted its allowed attempts. Inspect its setup log and fix the cause before approving new work.",
    "environment:exit": "Setup exited unsuccessfully. Read its setup log and correct the command or environment before continuing.",
    "environment:profile": "Setup could not use the committed profile. Correct .task-loop.json on the task branch before continuing.",
    "environment:platform": "The slot environment requires Linux. Use a supported Linux host for implementation.",
    "environment:path_long": "The slot's temporary path exceeds its supported length. Configure a shorter slots root before admission.",
    "environment:roots": "The writable environment folders overlap protected paths or escape the slots "
    "root. Separate the configured roots.",
    "environment:sandbox": "The sandbox probe failed. Inspect its supplied diagnostic and correct the host sandbox configuration.",
    "environment:files": "Setup's environment folders cannot be prepared. Check their permissions and free space before continuing.",
    "environment:remove_unsafe": "The environment cannot safely clear its scratch folder. Restore its "
    "expected location and ownership first.",
    "environment:reset": "The slot could not be reset to its admitted base. Preserve its changes and "
    "restore the expected checkout state.",
    "environment:lingering": "A setup process survived its entry or deadline. Wait for it to end; retain "
    "the slot until its identity is verified.",
    "environment:running": "An earlier setup process still runs. Wait for it to end before reusing the slot.",
    "environment:uncertain": "Setup may have started but its launch is uncertain. Wait for process "
    "reconciliation before reusing the slot.",
    "environment:unknown": "Setup process liveness cannot be established. Wait for reliable process observation before reusing the slot.",
    "checks:running": "An earlier check process still runs. Wait for it to end before another checks block can start.",
    "checks:unknown": "Check process liveness cannot be established. Wait for reliable process observation before continuing.",
    "checks:uncertain": "A check may have started but its launch is uncertain. Wait for reconciliation before continuing.",
    "answer:validation_pending": "The answer has not finished validation. Wait for the owning entry to complete collection.",
    "answer:valid": "The stored answer has no usable disposition. Preserve the answer and diagnostics for the owner's investigation.",
    "answer:missing": "The agent supplied no answer. Inspect its retained stdout, stderr and diagnostics "
    "before deciding on another attempt.",
    "answer:json_invalid": "The agent answer is not valid JSON. Inspect the answer and diagnostics before deciding on another attempt.",
    "answer:schema_invalid": "The agent answer does not meet its schema. Inspect the answer and "
    "diagnostics before deciding on another attempt.",
})

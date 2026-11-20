"""Context-specific remedies for configuration, adoption and read-only inspections."""

from typing import Final

from taskloop.workflow import Reason

UNAVAILABLE: Final = "unavailable"  # the workflow could not be read from Git: not a refusal reason of the file

CONFIG = {
    "missing": "The explicitly selected machine config is missing. Restore that file or select an existing config path.",
    "unreadable": "The machine config cannot be read. Check its path and read permissions.",
    "toml": "The machine config is not valid TOML. Correct the syntax in that file.",
    "unknown_key": "The machine config contains an unsupported setting. Remove or correct the named key in the machine config.",
    "type": "A machine setting has the wrong type. Correct the named setting in the machine config.",
    "relative_path": "A machine path is relative. Set the named path to an absolute path.",
    "count": "The slot count is invalid. Choose a positive supported slot count.",
    "interval": "The rounds interval is invalid. Choose an interval within the supported range.",
    "backlog_missing": "No backlog is named for this task and the machine config sets no default backlog. "
    "Name the backlog, or set the default backlog in the machine config.",
    "binding_missing": "The backlog's tracker root, checkout or approval label is not given and the machine config has none for "
    "it. Give the missing value, or add it to that backlog's entry in the machine config.",
}
PROFILE = {
    "missing": "The selected Git revision has no .task-loop.json. Commit a profile at the indicated revision before using it.",
    "no_commit": "The selected profile revision names no commit. Select an existing commit or restore the required ref.",
    "not_json": "The committed profile is not valid JSON. Correct .task-loop.json at the indicated side and commit the correction.",
    "not_object": "The committed profile must be a JSON object. Correct .task-loop.json at the indicated side.",
    "unknown_key": "The committed profile contains an unsupported key. Correct that key in .task-loop.json at the indicated side.",
    "bad_value": "A committed profile value is invalid. Correct the named profile key at the indicated side.",
    "too_large": "The committed profile exceeds a supported size limit. Reduce the named value or file before using it.",
    "duplicate_check": "The committed profile repeats a check name. Give every check a unique name.",
    "required_undefined": "A required check has no definition. Define it in both the target and checked profiles before using them.",
    "not_a_file": "The committed profile is not a regular file. Replace it with a plain .task-loop.json file at the indicated side.",
    "unavailable": "Git could not read the profile. Check access to the checkout and selected revisions, then inspect again.",
}
WORKFLOW: dict[str, str] = {
    Reason.MISSING: "The selected Git revision has no such workflow file. Commit one at the indicated revision, or name a workflow "
    "file that exists there.",
    Reason.NOT_A_FILE: "The committed workflow is not a regular file. Replace it with a plain workflow file at the indicated revision.",
    Reason.TOO_LARGE: "The committed workflow exceeds the supported size. Shorten it and commit the correction.",
    Reason.NOT_TOML: "The committed workflow is not valid TOML. Correct its syntax and commit the correction.",
    Reason.UNKNOWN_KEY: "The committed workflow contains an unsupported key. Remove or correct the named key and commit the correction.",
    Reason.UNKNOWN_KIND: "The committed workflow has a step table the factory does not run. Keep only the plan and implement tables "
    "and the feedback sections.",
    Reason.UNKNOWN_RENDERER: "A prompt section names a renderer the factory does not have. Use the task or input context renderer, "
    "or verbatim text.",
    Reason.RESERVED_MARKER: "A text section holds the name of a factory data block. Reword that section so it does not contain it.",
    Reason.BAD_VALUE: "A workflow value is invalid. Correct the named key and commit the correction.",
    UNAVAILABLE: "Git could not read the workflow. Check access to the checkout and the selected revision, then read again.",
}
WORKFLOW_INIT = {
    "exists": "That workflow file is already there and was left unchanged. Edit it in place, or choose another workflow name.",
    "unwritable": "The starter could not be written. Check that the checkout exists and that its folders can be written.",
}
REPO = {
    "not_a_repo": "The path is not a Git repository. Select an existing checkout root.",
    "git_read_failure": "Git could not read the checkout. Check its Git metadata and access permissions before inspecting again.",
    "git_timeout": "The repository read timed out. Check local repository access before inspecting again.",
    "git_unavailable": "Git could not inspect the repository. Check the supplied Git explanation and local access.",
    "unsupported_checkout": "This checkout shape is unsupported. Select a non-bare checkout root, rather than a subdirectory or file.",
    "path_unavailable": "The checkout path cannot be accessed. Check its existence and permissions.",
}
TASK = {
    "not_found": "The tracker has no such task. Check the task ID and explicitly selected backlog and tracker root.",
    "malformed": "The tracker returned malformed task data. Preserve its explanation and ask the tracker owner to correct the task.",
    "tracker_unavailable": "The tracker could not answer. Check the supplied adapter explanation and access to "
    "the configured tracker.",
    "invalid_binding": "The task scope does not match the configured tracker binding. Correct the backlog or "
    "tracker root before inspecting again.",
}
SLOT = {
    "not_listed": "The slot is not a listed worktree. Create or restore its detached worktree before adoption.",
    "main": "The person's main checkout cannot be adopted. Select a separate detached slot worktree.",
    "unborn": "The slot has no HEAD commit. Restore its expected commit before adoption.",
    "attached": "The slot is attached to a branch. Preserve its work and detach it before adoption.",
    "redirected": "The slot's Git pointer differs from the registered worktree. Restore the verified pointer before adoption.",
    "dirty": "The slot contains changes. Preserve needed work and settle its changes before adoption.",
    "git_unavailable": "The slot's repository could not be read. Check Git access before adoption.",
    "store_unavailable": "Slot state could not be recorded or read. Check database access and free space before adoption.",
    "other_root": "This repository already uses another slots root. Use that registered root; preserve its existing slots.",
    "inside_checkout": "The slots root lies inside the person's checkout. Choose a separate slots root before adoption.",
    "locked": "The slot's lock is held by another operation. Wait for that owner to finish.",
    "lock_unavailable": "The slot's lock cannot be opened. Check the lock directory's permissions.",
}

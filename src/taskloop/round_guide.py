"""Automatic factory messages describe the situation and decision in words."""

from taskloop.hold_cause import RULES, RUN, cause
from taskloop.inspection_guide import SLOT
from taskloop.step_refusal_guide import REFUSALS

GUIDE = {
    **REFUSALS,
    "minutes": "The validation needs a supported deadline. The owner must supply enough time before land can validate the change.",
    "incomplete": "The agent stopped before completing the task. The factory preserves its work and waits for the owner's decision.",
    "needs_owner": "The agent needs an owner decision. The factory preserves the evidence and waits for that decision.",
    "run:timeout": "The agent exceeded its deadline. The factory preserves the work and waits for the owner's decision.",
    "slot:branch": "The slot is on an unexpected branch. The factory waits for its expected branch to be restored.",
    "slot:moved": "The slot HEAD moved. The factory waits for its expected commit to be restored.",
    "slot:redirected": "The slot's Git pointer changed. The factory waits for its verified pointer to be restored.",
    "start": "The admitted entry needs launching; the factory retains its original choices.",
    "wait": "The entry is running; the factory waits for it.",
    "verify": "The result is captured; the factory will verify it before advancing.",
    "repeat": "Unsettled files require another attempt; the factory retains the work as feedback.",
    "repeats_exhausted": "The allowed repeats are exhausted. The task needs the owner's decision and remains held.",
    "release": "The attempt ended but its slot or claim remains held. Release must finish before new work can use it.",
    "abandoned": "The attempt was abandoned. The factory waits for the owner's approval before starting afresh.",
    "abandoned_skip": "The attempt was abandoned. The factory waits for the owner's approval before starting afresh.",
    "publish": "The verified result awaits publication; the factory retains its claim until delivery is resolved.",
    "advance": "The verified result is published; the next step waits for a free slot.",
    "done": "The step concluded. The factory follows its recorded result before advancing.",
    "unknown": "The entry or local state could not be read. The factory waits for reliable observation.",
    "running": "The entry is running; the factory leaves it alone.",
    "attempted": "The tracker task is open but a retained attempt exists. The factory will not retake it automatically.",
    "failed": "The attempt failed. The factory retains its evidence and waits for the owner's decision.",
    "no_free_slot": "Every slot is reserved or unusable. The factory waits for a usable free slot.",
    "unusable": "A slot is unusable. Its specific reason follows; the factory leaves it untouched.",
    "slot_for_land": "The last free slot is reserved for a waiting land. Admission waits.",
    "max_running": "The configured running limit has been reached. Admission waits for capacity.",
    "rounds_running": "Another rounds process owns this backlog. This process leaves scheduling to that owner.",
    "rounds_lock": "The rounds lock cannot be opened. Scheduling waits for access to the lock directory.",
    "interval": "The scheduling interval is outside its supported range. The owner must correct it before scheduling.",
    "task_missing": "The task is gone from the tracker. The factory skips it and preserves retained evidence.",
    "paused": "The task has an explicit held label. The factory waits for the owner's decision.",
    "task": "The tracker task could not be read. The factory waits for valid task data in its configured scope.",
    "changed": "The current attempt changed during this operation. The factory will observe the winning state.",
    "unsettled": "The attempt still owns work or processes. The factory retains the slot until settlement is proved.",
    "registration_conflict": "Another start registered the entry first. The factory observes the registered entry.",
    "slot_busy": "Another operation holds the slot lock. The factory waits for that operation.",
    "lock": "The slot lock cannot be opened. The owner must restore access before work can continue.",
    "not_terminal": "The attempt has not concluded. Its slot remains held until the result is settled.",
    "entry_running": "The entry still runs. The factory waits and retains its slot.",
    "worker_unknown": "A dispatched worker has no verified identity. The factory cannot prove it stopped and retains its slot.",
    "slot_dirty": "The slot contains retained changes. The owner must preserve and settle them before release can finish.",
    "remote": "The remote could not answer reliably. Publication or land waits for network and authorization to be restored.",
    "git": "Git could not answer reliably. The factory waits for repository access to be restored.",
    "repository": "The slot is no longer in the expected repository. The factory leaves it untouched pending restoration.",
    "not_verified": "The result has not passed verification. The factory cannot publish it.",
    "remote_ahead": "The remote branch includes later work. Publication waits for the owner to reconcile its history.",
    "no_remote": "The repository has no configured origin. The owner must configure the intended remote before publication.",
    "not_advanceable": "The current attempt has not met the conditions for advancing. The factory waits for "
    "settlement and publication.",
    "claim_lost": "The tracker claim is no longer the factory's. The factory will not retake it automatically.",
    "environment": "Setup or the slot environment could not be established. The owner must resolve its supplied "
    "diagnostic before work proceeds.",
    "setup_running": "A setup process still runs. The factory waits and keeps the slot held.",
    "setup_unknown": "Setup process liveness is uncertain. The factory retains the slot until it can prove settlement.",
    "check_running": "A check process still runs. The factory waits and keeps the slot held.",
    "check_unknown": "Check process liveness is uncertain. The factory retains the slot until it can prove settlement.",
    "checks": "Checks have not concluded reliably. The factory waits for their process and result reconciliation.",
    "no_required": "The target profile requires no checks. The owner must define the required checks before a pass can be decided.",
    "target": "The required main branch is missing or the target is unsupported. The owner must restore the intended target.",
    "target_profile": "The target profile is invalid. Work waits for the owner to correct the committed profile.",
    "commit_missing": "The checked commit is absent. The owner must restore its history before work proceeds.",
    "main_moved": "Main moved while the operation was in progress. The factory must reassess against the current target.",
    "branch_moved": "The task branch no longer contains the verified work. The owner must reconcile the retained history.",
    "remote_moved": "The remote task branch moved. The owner must compare and reconcile the retained history.",
    "diverged": "Local and remote task history diverged. The owner must reconcile them; publication cannot force an update.",
    "remote_rejected": "The remote rejected publication by policy. The owner must resolve its supplied explanation.",
    "land": "The passed task awaits land under the configured policy. The factory retains it until delivery is settled.",
    "landed": "The change is or may be on main. Land must finish reconciling delivery and close before abandonment is possible.",
    "landing": "A land candidate owns this task. Its delivery must be resolved before other work proceeds.",
    "hold": "The task needs the owner's decision. The factory is finishing the hold and preserves its evidence.",
    "on_hold": "The task is explicitly held. The factory waits for the owner's answer and approval.",
    "held": "The task or slot remains held. The owner must resolve its specific cause before work can proceed.",
    "claim_leaked": "The admission failed but its tracker claim may remain. The owner must reconcile the claim "
    "before the task can be taken again.",
    "conflict": "The checked change conflicts with main. The task is held for the owner's decision; this refusal "
    "will not be retried each round.",
    "checks_failed": "Checks on the land candidate failed. The task is held for the owner's decision; this "
    "refusal will not be retried each round.",
    "gate_changed": "The change alters the checks that decide a pass. The task is held for the owner's decision.",
    "target_moved": "Main moved during land. Delivery waits for a candidate based on the current target.",
    "profile": "The committed profile is invalid or unavailable. The owner must resolve it before work proceeds.",
    "land_running": "The land's owning process still runs. The factory waits for its delivery decision.",
    "push_barred": "The land candidate may not be pushed in its current state. The factory waits for the owner's decision.",
    "not_done": "The task has not finished its preceding step. Land waits for completion.",
    "not_checked": "The task has no passing checked result. Land waits for required checks.",
    "not_landing": "There is no current land candidate to continue. The factory preserves the task's current state.",
    "changes": "The candidate contains changes requiring validation. Delivery waits for that validation.",
    "no_change": "The candidate's unchanged tree requires the owner's explicit decision before delivery.",
    "abandoning": "Abandonment is unfinished. The factory retains ownership until release finishes.",
    "closed": "The tracker task is closed. The owner must resolve its status before work proceeds.",
    "blocked": "The tracker refuses closure because dependencies remain. Delivery is retained while the owner resolves them.",
    "repo": "The slot is not in the task's repository. The factory preserves it pending restoration.",
    "not_listed": "The slot is no longer a listed worktree. The owner must restore its registration before work proceeds.",
}


def automatic_guide(word: str) -> str:
    """Decode the fixed round-result codec, including nested release/publication refusals."""
    if word.startswith(("verified ", "reused ")):
        nested = [part.split("=", 1)[1] for part in word.split()[1:] if "=" in part and ":" in part]
        return " ".join(dict.fromkeys(automatic_guide(part) for part in nested))
    if word.startswith("held "):
        return GUIDE["on_hold"]
    if word.startswith("unusable:"):
        return SLOT[word.rsplit(":", 1)[-1]]
    if word.startswith("failed:"):
        word = word.split(":", 1)[1]
        if not word.startswith(("rejected:", "run:", "answer:", "environment:", "checks:")):
            return GUIDE.get(word, GUIDE["failed"])
    reason = word.split(":", 1)[1] if word.split(":", 1)[0] in {
        "refused", "unavailable", "uncertain", "unsettled", "rejected", "not_applicable", "defect", "held",
    } else word
    return _reason_guide(reason)


def _reason_guide(reason: str) -> str:
    if reason.startswith("stuck:"):
        return f"The attempt cannot continue ({reason}). The factory preserves its evidence and waits for the owner's decision."
    if reason in GUIDE:
        return GUIDE[reason]
    domain = reason.split(":", 1)[0]
    if domain == "git":
        return GUIDE[domain]
    if domain == "expired":
        return GUIDE["expired"]
    if reason not in RULES and not reason.startswith("answer:") and reason.split(":", 1)[-1] not in RUN:
        raise KeyError(reason)
    found = cause(reason if ":" in reason else f"rejected:{reason}")
    if found is None:
        raise KeyError(reason)
    return f"{found.what} The factory preserves the evidence and waits for the owner's decision."

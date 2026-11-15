"""Fixed explanations of step outcomes and decisions; operations own every transition."""

from pathlib import Path

from taskloop.hold_cause import RULES, RUN
from taskloop.hold_guide import HOLD, ON_HOLD
from taskloop.land_guide import LAND_GUIDE, LAND_NEXT
from taskloop.step_refusal_guide import REFUSALS

STEP_ONLY = ("Steps built: plan, implement and check. Verified results are published on the task branch. "
             "The profile selects automatic land during a round or manual land by the owner.")
PUBLISH = ("The step's result is verified but has not been published to origin. Publication must finish before the next step. "
           "An unreachable remote may need network or credential repair. If the remote branch moved, diverged or advanced, "
           "compare it with the verified commit and decide how to reconcile the histories; the factory never forces a push.")
HELD = ("The tracker claim stays held; the slot stays reserved until the step ends and its work is settled. "
        "Abandoning also returns the claim. While a step runs, its entry renews the tracker lease every 100 seconds. "
        "Between steps the lease is not renewed, so tracker maintenance can reclaim it after the lease and grace period "
        "expire. Rounds never renew or retake a lapsed claim: they skip an open task while factory.db retains its attempt.")
ABANDON = "Abandoning frees the slot once its processes are proven stopped and its work is settled, and returns the claim."
ROUNDS = ("Scheduling starts with a round immediately, then repeats at the configured interval and when a slot becomes free. "
          "Each round holds stopped tasks it took, advances completed claimed tasks, then starts approved ready tasks within "
          "the running-task limit (default 3). Under the automatic land profile read from origin's main, a round first lands "
          "one passed task it took; a conflict or failed re-check holds that task. The tracker is read only when a slot is free. "
          "The last free slot is reserved for a passed task waiting to land. Round results are retained in rounds.log. "
          "Ctrl-C once stops scheduling after the current move; twice exits immediately. Launched steps keep running. "
          "If interrupt handling was disabled at launch, SIGTERM is needed to stop scheduling. A move in flight finishes "
          "first, including any publication push up to Git's timeout. Checkout validation waits until a slot is free.")
GUIDE = {
    **REFUSALS,
    "start": "The entry needs relaunching. Rounds relaunch it until its deadline; an entry registered before a reboot gets "
    "its configured deadline renewed once per reboot. If the tracker claim was lost, relaunching cannot help: nothing "
    "retakes the claim. Inspect its ownership, then decide whether to abandon the retained attempt and approve a fresh one.",
    "wait": "Its entry is running. Wait for its result before deciding the next step.",
    "verify": "The result is captured and awaits verification before it can be accepted.",
    "repeat": "Unsettled work remains. Decide whether to repeat the step with this listing as feedback or settle the files "
    "and verify the result.",
    "repeats_exhausted": "The step repeated twice and remains unsettled. Inspect and settle the slot for verification and "
    "release, or decide to abandon the attempt.",
    "release": "The step ended but its slot is still held. Inspect and settle any listed files before release. Abandoning "
    "also returns the claim, unless a land may already have delivered to origin's main; then that land must finish first.",
    "abandoned": "The slot is free and the claim was returned unless the claim result says otherwise. A round starts a "
    "fresh attempt once the task carries the approval label.",
    "publish": PUBLISH,
    "advance": "The step is verified and published to origin. When a slot is free, rounds advance the oldest completed "
    "claimed task before starting new work. The tracker must still confirm the factory's claim; removing approval alone "
    "does not stop advancement, but abandoning does. The next step starts at the published commit. Checks use a detached "
    "checkout and the required names from local main.",
    "done": "The result was collected; its success status says whether verification passed. For checks, every check "
    "required by main must pass. Failed checks keep the claim and are not retried automatically. Inspect their results and "
    "logs, then decide whether to retry checks on the same commit or abandon and start the task afresh.",
    "unknown": "The entry or store could not be read. Wait for reliable observations before deciding how to continue.",
    "stuck:expired_admitted": "Nothing ran; rounds only report it. Its deadline passed with no relaunchable entry from "
    "before a reboot: none was registered, the entry is from this boot, or the boot is unknown. A confirmed pre-reboot "
    f"entry would instead get one renewed deadline. {ABANDON} A fresh attempt requires a new admission.",
    "failed": "The step ended without a verified result. A manually started step keeps its claim and is not held or "
    "retried by rounds. Inspect its evidence before deciding whether to abandon and admit a fresh attempt.",
    "running": "Its entry runs; the round leaves it alone.",
    "attempted": "The task is open in the tracker while factory.db retains its attempt: the claim was returned or lapsed. "
    "Rounds skip it; inspect the retained attempt before deciding its future.",
    "abandoned_skip": "The abandoned task is not restarted yet. A completed hold needs renewed approval; an unfinished "
    "abandon must finish returning the claim first.",
    "no_free_slot": "Every slot is reserved or unusable. Inspect the reported missing, dirty or incorrectly attached "
    "worktrees and settle their state. Scheduling resumes when a usable slot is free.",
    "unusable": "An unreserved slot is missing, dirty, redirected or attached to a branch. Inspect its reported path, "
    "preserve needed work and restore the expected clean worktree before it is reused.",
    "slot_for_land": "The last free slot is reserved for a passed task's land. Under automatic land the next round lands "
    "it; under manual land it waits for the owner's decision. New steps wait until it is landed.",
    "max_running": "This backlog reached its configured running-task limit. A passed task waiting to land counts toward "
    "the limit; failed, stuck and held tasks do not. New work waits for capacity.",
    "rounds_running": "Another scheduling process owns this backlog. Use its terminal or stop that confirmed process "
    "before starting another scheduler. The reported process ID is informational; individual rounds can still run.",
    "interval": "The scheduling interval must be a whole number of seconds, at least 5; the Git read timeout must be "
    "between 30 and 86400 seconds. Correct the configured values before scheduling.",
    "rounds_lock": "The rounds lock beside factory.db cannot be created. Restore access to that folder before scheduling.",
    "stuck:entry_lost": "The entry stopped before collecting its result. The factory keeps the slot reserved until the "
    "recorded entry and any registered worker and group are proven stopped, then releases uncaptured work and returns its claim.",
    "stuck:hung": "The entry or worker runs past its deadline. Before stopping anything, verify the worker's recorded "
    "identity, process group and slot working directory, and verify the entry's identity. Stop only confirmed owned "
    f"processes, the worker first and then the entry. {ABANDON}",
    "stuck:uncollected": "The result was captured but its answer or session remains pending or faulted, so verification "
    f"cannot judge it. Inspect entry.log and preserve the evidence before deciding to abandon. {ABANDON}",
    "stuck:conflict": f"The retained attempt conflicts with current authority. Inspect the evidence before deciding to abandon. {ABANDON}",
    "stuck:setup_failed": "Setup failed twice before an agent ran. Rounds no longer relaunch it. Inspect the setup log "
    "beside entry.log and correct the profile, network or slot cause. Abandoning releases the old attempt; a fresh "
    "admission starts at plan.",
    "task_missing": "The task was deleted from the tracker. Rounds skip it and continue other work; abandoning clears "
    "its retained attempt after safe release.",
    "paused": "The task has a held label added outside a factory hold. Rounds leave it paused until the owner removes "
    "that label; an already running step continues.",
    "task": "The task cannot be read from the attempt's bound tracker root. Inspect that tracker and the task's identity; "
    "rounds skip it until it is readable or its retained attempt is abandoned.",
    "changed": "Another attempt became current during the round. The next round follows the current attempt.",
    "unsettled": "Files, the slot pointer or HEAD remain unsettled. Inspect and preserve needed work before verification "
    "or a repeat. A redirected pointer needs inspection first. For `head_moved`, inspect listed refs and remove only refs "
    "created by this agent; a repeat is refused, so abandon before admitting a fresh attempt. A live worker must be proven "
    "stopped first. Staged paths need settlement. An unexpected branch needs restoration to the attempt's expected branch "
    "with its work preserved, or deliberate abandonment.",
    "registration_conflict": "Another start registered its entry first. Follow the existing attempt before allowing another launch.",
    "slot_busy": "Another entry or verification holds the slot. Wait for it; if it runs past its deadline, verify process "
    "identities before deciding whether to stop it.",
    "lock": "The slot lock cannot be created under the slots root. Restore that folder's permissions before continuing.",
    "not_terminal": "The step has not ended. Wait for completion or decide whether to repeat or abandon the attempt.",
    "entry_running": "The entry still runs. Wait for it, or verify its recorded identity before deciding to stop it.",
    "worker_unknown": "No agent identity was recorded. The slot stays reserved until its recorded entry is independently proven stopped.",
    "slot_dirty": "The slot stays held because files remain. Inspect and preserve needed work, then remove or restore "
    "the listed files before release; nothing is reset automatically.",
    "remote": "Origin could not be reached. Inspect network access and credentials, including the noninteractive SSH "
    "configuration, before publication can continue.",
    "git": "Git could not run or answer, possibly because publication credentials were refused. Resolve the supplied "
    "Git diagnostic and noninteractive access before continuing.",
    "repository": "The slot's Git pointer or repository differs from the attempt's binding. Inspect and restore the "
    "expected repository before publication; nothing was pushed.",
    "not_verified": "The step has no verified result to publish. Verification must accept it first; a rejected result "
    "cannot be published.",
    "remote_ahead": "The remote task branch contains the verified commit plus later commits. Compare the histories "
    "and decide how to reconcile them; the factory neither records this as its publication nor forces a push.",
    "no_remote": "The repository has no origin remote. The owner must configure the intended remote before publication.",
    "not_advanceable": "Only the current verified, released and published attempt can advance to a following step, with "
    "its claim kept. Inspect its status; an unfinished abandon must return the claim before new checks are admitted.",
    "claim_lost": "The tracker no longer confirms the factory's claim: it was reverted, taken by another actor or the "
    "task closed. Nothing retakes it. Inspect ownership before abandoning the retained attempt and deciding on fresh admission.",
    "environment": "Setup refused or failed, so no later work ran. Inspect its log beside entry.log and the specific "
    "reason. One failed run can retry before the deadline; two failures stop retries. A lingering setup process prevents "
    "slot reuse or release until proven stopped. Dirty files or a moved HEAD need safe restoration. Profile, platform, "
    "path, sandbox and permission failures need correction before continuing.",
    "setup_running": "A recorded setup process group still runs. Wait for it; before stopping anything, verify each "
    "member's identity and slot working directory and stop only confirmed owned processes. The factory never stops it.",
    "setup_unknown": "Setup processes cannot be reliably observed. Keep the slot reserved until they are proven stopped.",
    "stuck:checks_refused": "The checks entry reached two counted relaunch refusals without concluding, including late "
    "relaunches past the deadline. Rounds stop relaunching it. Inspect entry.log and resolve the cause before deciding "
    "on a manual relaunch or abandonment.",
    "check_running": "A recorded check process group still runs. Wait for it; before stopping anything, verify each "
    "member's identity and slot working directory and stop only confirmed owned processes. The factory never stops it.",
    "check_unknown": "Check processes cannot be reliably observed. Keep the slot reserved until they are proven stopped.",
    "checks": "The checks entry did not conclude: an earlier process may still run, process observation may be unavailable "
    "or a launch may be uncertain. Relaunch reconciles these facts and counts toward the two-refusal limit.",
    "no_required": "The profile on local main requires no checks, so a pass cannot be decided. The owner must select "
    "required checks there; completed tasks wait until then.",
    "target": "Local main is missing or its profile selects an unsupported target. Restore the intended main and "
    "profile before new task branches or checks can proceed.",
    "target_profile": "The profile on local main is invalid. Correct the supplied profile error there; completed tasks wait until then.",
    "commit_missing": "The implement commit is missing from the repository. Restore its retained task branch, or "
    "decide to abandon and admit the task afresh at plan.",
    "main_moved": "Main moved during checks, so the required check names may be stale. Rounds recheck their tasks "
    "against current main and hold after three consecutive changes. A manually started task needs a manual recheck decision.",
    "branch_moved": "The local task branch no longer contains the verified commit. Restore that history before "
    "publication or decide to abandon the attempt.",
    "remote_moved": "The remote task branch moved during publication. Compare its current history with the verified "
    "commit and reconcile it before deciding to retry publication.",
    "diverged": "The remote task branch does not contain the verified commit. Compare and reconcile the histories "
    "before publication; the factory never forces a push.",
    "remote_rejected": "The remote's policy rejected publication. Inspect that policy and the supplied diagnostic "
    "before deciding how to publish the verified commit; the factory never forces a push.",
    "land": LAND_NEXT["land"],
    "landed": LAND_NEXT["landed"],
    "landing": LAND_GUIDE["landing"],
    "hold": HOLD,
    "on_hold": ON_HOLD,
    "held": "A round has not finished holding this task. Resolve its reported pending cause so the next round can "
    "return the claim and finish. Then answer the hold in the task requirements and renew approval before new work starts.",
}

CHECKS_GUIDE = {
    "start": "Rounds relaunch the checks entry. Two consecutive counted refusals stop automatic relaunches. Failed or "
    "uncertain launches and refusals before counting retry until the deadline; past it every round's relaunch counts. "
    "The relaunched entry concludes expired once no attempt process remains. Abandoning returns the claim after safe release.",
    "wait": "The checks entry, or a check or setup process group that outlived it, still runs. Rounds wait without "
    "counting a relaunch, then relaunch the entry once those processes end.",
    "stuck:hung": "The checks entry or a surviving check process group runs past its deadline. Before stopping anything, "
    "verify the entry identity and each group member's recorded identity and slot working directory. Stop only confirmed "
    "owned processes, check groups first and then the entry. A relaunch concludes expired; abandonment requires safe release.",
    "unsettled": "A process of the checks attempt still holds its slot. Nothing changed; release must wait for that "
    "process to be proven stopped.",
    "release": "The checks concluded but their slot is held by a running process or unsettled files. Wait for confirmed "
    "process completion or inspect and settle the files. Once the entry is gone, rounds retry release. Abandoning also "
    "returns the claim after safe release.",
}

NEEDS_OWNER = (
    "The agent needs the owner's decision before this step can succeed. Its explanation is above and its whole answer "
    "is retained in answer.txt in the attempt directory. A manually started step is not held or written to the task, and "
    "its claim lapses unrenewed. Record the decision in the task's description before abandoning and admitting a fresh attempt."
)

# Commit rules and classified execution failures already have an owning explanation.
GUIDE.update({word: f"Verification refused: {what}. Inspect the retained evidence and resolve this before continuing."
              for word, (what, _fix) in RULES.items()})
GUIDE.update({f"run:{word}": f"{what} The owner must resolve this before new work is approved."
              for word, (what, _fix) in RUN.items()})
GUIDE.update({
    "answer_repair": "The rejected answer's repair could not be admitted. The factory will retry when admission is available.",
    "run:timeout": "The agent exceeded its deadline. Inspect its retained work and evidence before deciding on another attempt.",
    "incomplete": "The agent reported incomplete work. Inspect its answer and evidence before deciding how to continue.",
    "needs_owner": NEEDS_OWNER,
    "run": "The agent execution failed. Inspect its retained stdout, stderr and diagnostics before deciding on another attempt.",
    "answer": "The agent answer did not meet the answer contract. Inspect diagnostics.txt and the retained answer before "
    "deciding on another attempt.",
})


def refusal_guide(reason: str, *, checks: bool = False, land: bool = False) -> str:
    """Resolve a reason, never a failure-kind catch-all. Compound domains keep their owning guide."""
    if land and reason in LAND_GUIDE:
        return LAND_GUIDE[reason]
    domain = reason.split(":", maxsplit=1)[0]
    if land and domain in LAND_GUIDE:
        return LAND_GUIDE[domain]
    if reason in GUIDE:
        return guide(reason, checks=checks)
    domain = reason.split(":", maxsplit=1)[0]
    if domain == "git":
        return GUIDE[domain]
    key = "expired" if reason.startswith("expired:") else reason
    if reason.startswith("slot:"):
        key = {"branch": "slot_branch", "moved": "head_moved", "redirected": "slot_redirected"}[reason.split(":")[1]]
    return GUIDE[key]  # A new public reason needs an explicit guide and coverage case.


def guide(word: str, *, checks: bool, land: bool = False) -> str:
    """Use the land or checks explanation where an agent attempt's explanation would mislead."""
    if land and word in LAND_NEXT:
        return LAND_NEXT[word]
    return CHECKS_GUIDE.get(word, GUIDE[word]) if checks else GUIDE[word]


def discard(db: Path) -> str:
    """The last resort, naming this machine config's resolved factory.db, never another factory's."""
    return "\n".join([
        "Last resort: when an attempt cannot be proven stopped, the owner may decide to discard the whole factory database.",
        "First stop scheduling, then all entries and workers, using only independently verified process identities.",
        f"Only after all are stopped, discard {db} and its -wal/-shm companions; preserve every other factory's database.",
        "Return each tracker claim only if it is still held by the factory, then inspect and readopt each slot worktree.",
        "Never edit rows by hand: a deleted reservation silently fences out a still-running worker.",
    ])

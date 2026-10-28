"""A resumed branch is rebased onto the latest base before it is planned; a conflict is fixed in place when few files are in it, else the
task starts again on the base (the branch kept under another name)."""
import dataclasses
import time
from pathlib import Path
from typing import Any

MAX_REBASE_RESETS = 2  # the plan count starts again at most this often per bead: a red gate for a real reason must still reach the limit
SALVAGE_MAX_FILES = 10  # a resume conflict in more files than this starts again


class Rebase:
    def __init__(self, host: Any) -> None:
        self.e = host
        self.squashed = False

    def onto_base(self, salvage: bool = False) -> str:
        """tl-bxk.13.8: a branch resumed from an earlier run is rebased onto the latest base before it is planned or re-planned, so the
        plan and the checks see what main has now. -> "rebased" (the plan count starts again), "conflict" (the work does not fit main: the
        caller starts again, tl-19i), "conflict-fixable" (salvage on: the rebase stopped on few files and is left running for the caller's
        fix(conflict)), or "". More than one commit on the branch (the wip commits) is squashed first, so one conflict is fixed once."""
        e = self.e
        if e.dry or e.dirty_status():  # (the base-ignored files of an old branch are no reason not to rebase)
            return ""
        behind = e.git("rev-list", "--count", f"HEAD..{e.cfg.base}")
        if behind in ("", "0"):
            return ""
        orig = e.git("rev-parse", "HEAD")
        old_parent = e.git("rev-parse", "-q", "--verify", "HEAD~1") if e.left_dirty else ""
        self.squash_wip(orig)
        e.rebase_orig, e.rebase_pre = orig, [x for x in (orig, old_parent) if x]
        rc, tail = e.sh(["git", "rebase", "-q", e.cfg.base], pin=True)
        if rc:
            return self.stopped(salvage, tail, orig)
        self.follow_checkpoint()
        e.log.note(f"rebased the task branch onto the latest {e.cfg.base} ({behind} commits behind) before planning")
        return self.plan_count()

    def squash_wip(self, orig: str) -> None:
        e = self.e
        self.squashed = False
        mb = e.git("merge-base", "HEAD", e.cfg.base)
        if not mb or e.git("rev-list", "--count", f"{mb}..HEAD") in ("", "0", "1"):
            return
        rc, _ = e.sh(["git", "reset", "-q", "--soft", mb], pin=True)
        if not rc:
            rc, _ = e.sh(["git", "commit", "-q", "--no-verify", "--allow-empty", "-m", f"wip ({e.bead}): earlier work, squashed"], pin=True)
        if rc:  # the branch stays as it was
            e.sh(["git", "reset", "-q", "--hard", orig], pin=True)
        else:
            self.squashed = True
            e.log.note("squashed the branch's wip commits into one before rebasing")

    def stopped(self, salvage: bool, tail: str, orig: str) -> str:
        e = self.e
        unmerged = e.git("diff", "--name-only", "--diff-filter=U").split()
        if salvage and unmerged and len(unmerged) <= SALVAGE_MAX_FILES:
            e.salvage_tail = "Conflicted files: {}\n{}".format(", ".join(unmerged), tail)
            return "conflict-fixable"
        e.sh(["git", "rebase", "--abort"], pin=True)
        if self.squashed:
            e.sh(["git", "reset", "-q", "--hard", orig], pin=True)
        last = tail.strip().splitlines()[-1][:200] if tail.strip() else "conflict"
        e.warn(f"the task branch could not be rebased onto {e.cfg.base} before planning: {last}")
        return "conflict"

    def follow_checkpoint(self) -> None:
        """The checkpoint's head follows a rebase (or squash), or the next resume reads this as an edit from outside."""
        e = self.e

        def move(ck: Any) -> Any:
            if ck.head not in e.rebase_pre:
                return ck
            # unsquashed, the wip commit reset() made on top of the checkpoint's head is still on top of it
            above = not self.squashed and len(e.rebase_pre) > 1 and ck.head == e.rebase_pre[1]
            return dataclasses.replace(ck, head=e.git("rev-parse", "HEAD~1" if above else "HEAD"))

        e.checkpoints.amend(move)

    def salvage(self) -> str:
        """tl-7y6.2.19: the resume rebase stopped on a few files: one fix(conflict) round (markers and build only) instead of throwing the
        branch away. -> "rebased" (the run record shows salvaged: true), or "conflict": the fix did not work, the branch is back as it
        was and the caller starts again."""
        e = self.e
        fixes, ok = e.fixes, False
        try:
            d = e.fixer.fix("conflict", e.salvage_tail, resume=True)
            ok = not e.git("diff", "--name-only", "--diff-filter=U")  # (a fix the review sent back still continued the rebase)
            if d != "accept":
                e.warn("resume: the conflict fix did not pass its checks and review; the stage goes on from it")
        except e.FixFailed as err:
            e.warn(f"the resume conflict fix failed: {str(err).splitlines()[0][:200]}")
        finally:
            e.fixes = fixes  # the land's two fix rounds are its own
        gd = Path(e.git("rev-parse", "--absolute-git-dir") or ".")
        if (gd / "rebase-merge").exists() or (gd / "rebase-apply").exists():
            e.sh(["git", "rebase", "--abort"], pin=True)
        if not ok:
            e.sh(["git", "reset", "-q", "--hard", e.rebase_orig], pin=True)  # the work as it was, for start_again
            return "conflict"
        e.salvaged = True
        self.follow_checkpoint()
        e.log.note("resume conflict fixed in place instead of starting again (salvaged)")
        return self.plan_count()

    def plan_count(self) -> str:
        e = self.e
        if e.planned and e.rebase_resets < MAX_REBASE_RESETS:
            # tl-19i: plans made on the old base say nothing about this one. At most twice per bead
            e.log.note(f"the plan count starts again: {e.planned} earlier plan{'' if e.planned == 1 else 's'} were made on another base")
            e.plan_log.append({"mode": "rebase", "counted": False,
                               "why": f"the branch moved to a new base; {e.planned} plan(s) before it do not count"})
            e.planned, e.rebase_resets = 0, e.rebase_resets + 1
        return "rebased"

    def start_again(self, why: str) -> bool:
        """tl-19i: the branch's earlier work conflicts with main, so it cannot go on. It is kept under another name; the task starts again
        on the base with a fresh plan (the owner's answer is in the bead's comments), and nothing so far counts toward the re-plan limit."""
        e = self.e
        branch = e.git("symbolic-ref", "--short", "-q", "HEAD")
        if not branch or branch != (e.branch or branch):
            e.warn(f"resume conflict, but HEAD is not the task branch ({branch or 'detached'}): the branch stays as it was")
            return False
        stale = f"{branch}-stale-{time.strftime('%Y%m%d-%H%M%S')}"
        if e.git("rev-parse", "--verify", "-q", "refs/heads/" + stale):
            stale += "-2"
        rc, tail = e.sh(["git", "branch", "-m", branch, stale], pin=True)
        if rc:  # never reset a branch whose work could not be kept
            e.warn(f"resume conflict, but the branch could not be kept aside ({tail.strip()[-160:]}): it stays as it was")
            return False
        e.sh(["git", "checkout", "-q", "-B", branch, e.cfg.base], pin=True, check=True)
        e.checkpoints.drop()
        self.forget()
        e.steps.move("plan", "resume_conflict",
                     f"the branch's earlier work conflicts with {e.cfg.base}: kept as {stale}, planning fresh. {why[:160]}")
        e.log.note(f"resume conflict: {branch} kept as {stale}; the task starts again on {e.cfg.base}")
        e.comment(f"Resume (engine): the earlier work on {branch} conflicts with {e.cfg.base}. It is kept as the branch {stale}; "
                  f"the task starts again on {e.cfg.base} with a fresh plan.")
        return True

    def forget(self) -> None:
        """What the old attempt left in the run: the plan, the accepted stages, the writer, the look state (verify_answer stays: the owner's
        word still goes to the planner)."""
        e = self.e
        e.old_plan, e.amend_why, e.amend_text, e.replan_first = None, "", "", False
        e.plan_summary, e.last_summary, e.amended = "", "", False
        e.state = e.state.start_again()
        e.unverified = list[dict[str, str]]()
        e.unchecked = list[dict[str, str]]()

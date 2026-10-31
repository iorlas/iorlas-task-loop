"""The seams of the push-race interruption cells (tests/land/test_engine_land_1.py): an engine stopped, paused or denied at one
boundary of a failed land validation, and the later runs that recover from the checkpoint it left."""
import signal
from contextlib import ExitStack
from unittest import mock

from support import fake_route
from support.push_race import seam
from taskloop.app.checks import evidence as check_evidence
from taskloop.app.land.fixer import Fixer
from taskloop.app.land.outbound import pin_head
from taskloop.app.run import engine
from taskloop.app.run.state import Checkpoints
from taskloop.app.run.steps import Steps
from taskloop.app.write.stage_loop import StageLoop
from taskloop.contracts.kinds import Kind


class Interrupter:
    """Interrupts the run at `role` (a boundary: failed_checks, checkpoint, transition; or a worker role inside the fix)."""

    def __init__(self, case, interruption, role):
        self.case, self.interruption, self.role = case, interruption, role
        self.seen: dict = {}
        self.real = {"fix": Fixer.fix, "stage": StageLoop.run, "delegate": fake_route.Script.reply,
                     "brief": check_evidence.failure_brief, "checkpoint": Checkpoints.save, "move": Steps.move}

    def boundary(self, name):
        if self.role == name and not self.seen.get("interrupted"):
            self.seen["interrupted"] = True
            signal.raise_signal(signal.SIGTERM)

    def brief(self, bad, run_dir):
        # Red results must replace the pre-check recovery barrier without a signal gap.
        if any(c.cmd == "retry check" for c in bad):
            self.boundary("failed_checks")
        return self.real["brief"](bad, run_dir)

    def checkpoint(self, this, **at):
        if at.get("step") == "land-verify-red":
            # SIGTERM must wait until the durable checkpoint has actually been written.
            self.boundary("checkpoint")
        return self.real["checkpoint"](this, **at)

    def move(self, this, to, cause, detail=""):
        if to == "fix" and cause == "checks_red":
            # This used to interrupt before pending validation was saved at all.
            self.boundary("transition")
        return self.real["move"](this, to, cause, detail)

    def fix(self, this, kind, tail, resume=False):
        case, seen = self.case, self.seen
        ck = case.checkpoint()
        case.assertEqual(ck["step"], "land-verify-red")
        case.assertIn("retry check", ck["pending_land_validation"])
        case.assertEqual(ck["feedback"], ck["pending_land_validation"])
        seen["failure"] = ck["feedback"]
        seen["in_fix"] = True
        try:
            return self.real["fix"](this, kind, tail, resume)
        finally:
            seen["in_fix"] = False

    def stage(self, this, plan, i, state=None):  # this: the StageLoop
        if (state or {}).get("fix"):
            # fix() has initialized its checkpoint; the pending failure must still be there.
            ck = self.case.checkpoint()
            self.case.assertEqual(ck["step"], "land-verify-red")
            self.case.assertEqual(ck["feedback"], self.seen["failure"])
            self.seen["fix_initialized"] = True
        return self.real["stage"](this, plan, i, state)

    def delegate(self, this, current_role, *a, **kw):
        if self.seen.get("in_fix") and current_role == self.role:
            self.seen["interrupted"] = True
            if self.interruption == "SIGTERM":
                signal.raise_signal(signal.SIGTERM)
            paused = self.interruption == "pause"
            raise engine.Blocked("paused: validation writer unavailable" if paused else "needs a human: validation command denied",
                                 kind=Kind.PAUSE_LANE if paused else Kind.FAULT_DENIED)
        return self.real["delegate"](this, current_role, *a, **kw)

    def patched(self):
        stack = ExitStack()
        for target, name, fn in ((Fixer, "fix", seam(self.fix)), (StageLoop, "run", seam(self.stage)),
                                 (check_evidence, "failure_brief", self.brief), (Checkpoints, "save", seam(self.checkpoint)),
                                 (Steps, "move", seam(self.move)), (fake_route.Script, "reply", seam(self.delegate))):
            stack.enter_context(mock.patch.object(target, name, fn))
        return stack


class Recovery:
    """The later runs: count their checks and the pushes they make, and see that no stale validation stays when a push is made."""

    def __init__(self, case):
        self.case = case
        self.checks_run: list = []
        self.pushes: list = []
        self.real_checks, self.real_sh = engine.Engine.run_checks, engine.Engine.sh

    def checks(self, this, *a, **kw):
        result = self.real_checks(this, *a, **kw)
        self.checks_run.append(result)
        return result

    def command(self, this, cmd, *a, **kw):
        pushed = cmd[-1].partition(":")[0].lstrip("+") if isinstance(cmd, list) else ""  # the land pins HEAD to its sha
        if isinstance(cmd, list) and cmd == pin_head(this.cfg.land, pushed):
            self.pushes.append(cmd)
            self.case.assertFalse(this.pending_land_validation)
            self.case.assertFalse(self.case.checkpoint()["pending_land_validation"])
        return self.real_sh(this, cmd, *a, **kw)

    def patched(self):
        stack = ExitStack()
        stack.enter_context(mock.patch.object(engine.Engine, "run_checks", seam(self.checks)))
        stack.enter_context(mock.patch.object(engine.Engine, "sh", seam(self.command)))
        return stack

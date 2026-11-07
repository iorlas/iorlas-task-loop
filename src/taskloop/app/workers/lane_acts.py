"""What the engine does about a stopped call: `lanes.policy.decide` says what, this does it. Retries and waits set up the next call of
the step; a pause or a fault ends the step as a `Blocked` (built by the host's ops). Every decision is a `RetryDecision` record with the
timeout and the exit it was made on. The lander's git push network wait lives here too."""

import time
from typing import Any, Final

from tlkernel import log as rec
from tlkernel.delegate import DelegateResult
from tlkernel.waitenums import WaitWhat

from taskloop.app.workers import writer_pin
from taskloop.domain.lanes import pin
from taskloop.domain.lanes import policy as lp
from taskloop.domain.lanes.notes import NET_BACKOFF, NOTES
from taskloop.domain.lanes.roles import READ_ONLY_NODES
from taskloop.domain.review.availability import ReviewUnavailable

ASK_KINDS: Final = ("ASK_STUCK",)
VERBS: Final = {
    lp.Retry: "retry",
    lp.Wait: "wait",
    lp.NewThread: "new_thread",
    lp.Reroute: "reroute",
    lp.Yield: "pause",
}


class LaneActs:
    def __init__(self, host: Any, call: Any) -> None:
        self.e, self.wc = host, call

    # -- the network gate
    def net_up(self) -> bool | None:
        """True, False, or None (the probe could not run): the host's probe, else delegate's `route.py net`."""
        return self.e.delegation.net_probe().up()

    def await_net(self, up: bool | None, max_s: float) -> tuple[float, bool]:
        """Wait until the probe passes, at most max_s (backoff NET_BACKOFF); `up` is the probe's last answer. -> (seconds waited,
        whether the network is back). The time is neither the budget's nor a failure's: it is written as a wait."""
        e = self.e
        waited, i, wid = 0.0, 0, e.waits.start(WaitWhat.NETWORK) if up is not False or max_s > 0 else None
        if up is not False:  # the probe says up, or could not run: a beat, then go and see
            e.halt_point(wait=NET_BACKOFF[0])
            waited, up = NET_BACKOFF[0], True
        while up is False and waited < max_s:
            gap = NET_BACKOFF[min(i, len(NET_BACKOFF) - 1)]
            i += 1
            e.halt_point(wait=gap)
            waited += gap
            up = self.net_up()
            if up is None:  # the probe could not run: go and see
                up = True
        if wid:
            e.waits.add(waited, WaitWhat.NETWORK, wid)
        return waited, up is not False

    def ctx_of(self, c: Any) -> lp.Ctx:
        k, now = c.counts, self.e.clock.now()
        return lp.Ctx(
            now,
            bool(c.resume),
            k["attempt"],
            k["polls"],
            k["crashes"],
            k["waited_lane_s"],
            c.denied_retried,
            c.secret_fp,
            c.node,
            resume_refused=int(k["resume_refused"]),
        )

    # -- the decision
    def record(self, c: Any, stop: lp.Stop, a: Any) -> None:
        verb = ("ask" if a.kind in ASK_KINDS else "fault") if isinstance(a, lp.Fail) else VERBS[type(a)]
        self.e.log.emit(
            rec.RetryDecision(
                step=c.step or c.node,
                plan=getattr(a, "plan", ""),
                action=verb,
                attempt=c.counts["attempt"],
                reason=stop.reason,
                timeout_s=c.limit_s,
                exit=stop.exit_code,
                lane=stop.lane,
                evidence=f"{stop.scope} {stop.permanence}",
            )
        )

    def act(self, c: Any, res: DelegateResult, stop: lp.Stop, a: Any) -> None:
        """Do what lane_policy.decide said about a stopped call. A Yield or Fail ends the step (Blocked); the rest set up the next call."""
        self.record(c, stop, a)
        step = c.step or c.node
        if isinstance(a, (lp.Retry, lp.Wait)):
            return self.rest(c, res, stop, a, step)
        if isinstance(a, lp.NewThread):
            self.e.steps.move(
                step, "denied_retry" if a.note == "apply_patch" else "lane_out", "%s: a new thread" % (stop.reason or "the lane is out")
            )
            if a.note == "lane_out":
                c.out_on = stop.lane or c.out_on
            self.wc.charge(c, a.charges)
            return self.wc.again(c, note=NOTES.get(a.note, ""))
        if isinstance(a, lp.Reroute):
            self.e.log.note("{}: {} stopped the call ({}); routing it again".format(c.node, a.exclude or "the pick", stop.reason))
            self.e.steps.move(step, "lane_out", "%s: routed again" % (stop.reason or "the lane stopped"))
            c.out_on = stop.lane or c.out_on
            self.wc.charge(c, a.charges)
            return self.wc.again(c)
        return self.end(c, res, stop, a)

    def same_family(self, c: Any, res: DelegateResult) -> bool:
        """tl-9un.15: a reviewer answer from the writer's own family (delegate's flag, or the family itself) is no review."""
        return c.node in READ_ONLY_NODES and bool(c.writer_family) and (res.flag == "same_family" or res.family == c.writer_family)

    def refuse_same_family(self, c: Any, res: DelegateResult) -> None:
        """Pause the step until the other family has a lane: the answer is dropped (a resume must not take it back)."""
        e = self.e
        if c.state is not None:
            c.state.consumed()
        e.retry_after = 0.0
        e.pause_reason = "same_family"
        e.pause_producer = "engine"
        e.pause_permanence = None
        why = f"paused: no lane of another family than the writer's ({c.writer_family}) for the {c.node} step; it runs when one is free"
        e.steps.outcome("paused", "same family")
        e.steps.move("pause", "paused", f"lane for {c.node}: only the writer's own family ({c.writer_family}) answered")
        raise self.wc.ops.blocked(why, "PAUSE_LANE")

    def rest(self, c: Any, res: DelegateResult, stop: lp.Stop, a: lp.Retry | lp.Wait, step: str) -> None:
        e = self.e
        secs = max(0.0, (a.not_before if isinstance(a, lp.Retry) else a.until) - e.clock.now())
        crash = a.charges == "crashes"
        if secs:
            doing = "delegate crashed" if crash else "waiting for the lane"
            e.warn(f"{c.node}: {doing} ({(res.say or stop.reason)[:160]}), trying again in {int(secs)} s")
            e.steps.move(
                step,
                "delegate_crash" if crash else "lane_wait",
                f"{'delegate crashed' if crash else 'waited for a lane'} ({stop.reason}): {int(secs)} s",
            )
            wid = e.waits.start(WaitWhat.DELEGATE_CRASH if crash else WaitWhat.LANE, stop.lane or "", e.clock.now() + secs)
            e.halt_point(wait=secs)
            e.waits.add(secs, WaitWhat.DELEGATE_CRASH if crash else WaitWhat.LANE, wid)
        self.wc.charge(c, a.charges, secs)
        return self.wc.again(c, a.resume, note="")

    def end(self, c: Any, res: DelegateResult, stop: lp.Stop, a: lp.Yield | lp.Fail) -> None:
        """An exhausted invalid review is unavailable; other stops end the step with their Blocked outcome."""
        if (c.node, a.kind, stop.reason) == ("review", "FAULT_INFRA", "schema_invalid"):
            raise ReviewUnavailable(stop.reason)
        e, ops = self.e, self.wc.ops
        e.pause_reason = stop.reason if isinstance(a, lp.Yield) or a.kind.startswith("FAULT_") else ""
        e.pause_producer = stop.producer if e.pause_reason else "engine"
        e.pause_permanence = stop.permanence if stop.permanence in ("transient", "needs_owner") else None
        retry_after = 0.0
        if isinstance(a, lp.Yield):
            retry_after = a.retry_after if a.retry_after > e.clock.now() else 0.0  # the Park uses this as its earliest retry time
            e.retry_after = retry_after
            e.steps.outcome("paused", stop.reason)
            e.steps.move(
                "pause",
                "paused",
                "{} for {}{}".format(
                    a.kind.lower().replace("pause_", ""),
                    c.node,
                    (" until " + time.strftime("%H:%M:%S", time.localtime(retry_after))) if retry_after else "",
                ),
            )
        pinned = writer_pin.pinned(e.cfg, str(e.bead), e.plan_data, e.budget.labels, c.role)
        if isinstance(a, lp.Yield) and pinned and stop.reason in pin.STOP_REASONS:  # the pin found no ready lane: say it
            warm = writer_pin.warm(e.cfg, str(e.bead), e.plan_data, e.budget.labels) if c.role == pin.PINNED_ROLE else ""
            raise ops.blocked(pin.stop_why(c.node, pinned, stop.reason, res.say or stop.fix, stop.fix, warm), a.kind, stop)
        why = ops.stop_why(c.node, a.kind, stop, res.say, retry_after, c.counts["crashes"] + 1, res.denied, now=e.clock.now())
        raise ops.blocked(why, a.kind, stop)

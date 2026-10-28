"""What the engine does about a stopped call: `lanes.policy.decide` says what, this does it. Retries and waits set up the next call of
the step; a pause or a fault ends the step as a `Blocked` (built by the host's ops). Every decision is a `RetryDecision` record with the
timeout and the exit it was made on. The network gate (probe, backoff, the pause hint) lives here too."""

import time
from typing import Any, Final

from taskloop.contracts import log as rec
from taskloop.contracts.delegate import DelegateResult
from taskloop.contracts.enums import WaitWhat
from taskloop.domain.lanes import policy as lp
from taskloop.domain.lanes.notes import NET_BACKOFF, NOTES
from taskloop.domain.lanes.roles import READ_ONLY_NODES

ASK_KINDS: Final = ("ASK_STUCK",)
VERBS: Final = {
    lp.Retry: "retry",
    lp.Wait: "wait",
    lp.WaitNet: "wait_net",
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
        return self.e.net_probe().up()

    def note_net(self, c: Any, stop: lp.Stop) -> None:
        """A stop of the machine that polls (the network): ask the probe now. Up at a stop is counted: three in five minutes mean the
        calls fail for something the probe cannot see (a proxy, DNS), which the policy pauses visibly."""
        if (stop.scope, stop.permanence, stop.retry_kind) == ("machine", "transient", "poll"):
            c.up_now = self.net_up()
            if c.up_now is True:
                self.e.net_up_times.append(self.e.clock.now())

    def await_net(self, up: bool | None, max_s: float) -> tuple[float, bool]:
        """Wait until the probe passes, at most max_s (backoff NET_BACKOFF); `up` is the probe's last answer. -> (seconds waited,
        whether the network is back). The time is neither the budget's nor a failure's: it is written as a wait."""
        e = self.e
        waited, i, wid = 0.0, 0, e.wait_start(WaitWhat.NETWORK) if up is not False or max_s > 0 else None
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
            e.add_wait(waited, WaitWhat.NETWORK, wid)
        return waited, up is not False

    def ctx_of(self, c: Any) -> lp.Ctx:
        k, now, e = c.counts, self.e.clock.now(), self.e
        e.net_up_times = [t for t in e.net_up_times if now - t < lp.KNOBS["net_probe_window_s"]]
        return lp.Ctx(
            now,
            bool(c.resume),
            k["attempt"],
            k["polls"],
            k["crashes"],
            k["waited_lane_s"],
            k["waited_net_s"],
            len(e.net_up_times),
            c.denied_retried,
            c.secret_fp,
            c.node,
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
        if isinstance(a, lp.WaitNet):
            return self.wait_net(c, res, stop, a)
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
            if c.node in READ_ONLY_NODES and res.family in ("openai", "claude", "xai"):
                c.writer = res.family  # routed as if that family had written the work: the others come first, the failing one last
            c.out_on = stop.lane or c.out_on
            self.wc.charge(c, a.charges)
            return self.wc.again(c)
        return self.end(c, res, stop, a)

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
            wid = e.wait_start(WaitWhat.DELEGATE_CRASH if crash else WaitWhat.LANE, stop.lane or "", e.clock.now() + secs)
            e.halt_point(wait=secs)
            e.add_wait(secs, WaitWhat.DELEGATE_CRASH if crash else WaitWhat.LANE, wid)
        self.wc.charge(c, a.charges, secs)
        return self.wc.again(c, a.resume, stop=stop, note="")

    def end(self, c: Any, res: DelegateResult, stop: lp.Stop, a: lp.Yield | lp.Fail) -> None:
        """A Yield (pause) or Fail ends the step: the Blocked carries the outcome Kind and the stop."""
        e, ops = self.e, self.wc.ops
        retry_after = 0.0
        if isinstance(a, lp.Yield):
            retry_after = a.retry_after if a.retry_after > e.clock.now() else 0.0  # a hint: the loop wakes the bead when its role is usable
            e.retry_after, e.pause_role, e.pause_lane = retry_after, c.role, stop.lane
            if a.banner:
                e.warn(f"the network looks up but delegate calls keep failing: {ops.stop_say(stop)}")
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
        why = ops.stop_why(c.node, a.kind, stop, res.say, retry_after, c.counts["crashes"] + 1, res.denied)
        raise ops.blocked(why, a.kind, stop)

    def wait_net(self, c: Any, res: DelegateResult, stop: lp.Stop, a: lp.WaitNet) -> None:
        """The network is down: probe until it is back (backoff), at most a.max_s; then the same thread goes on with a short note, no
        counter charged. Out of time the run yields, the loop probes and wakes the bead."""
        e = self.e
        e.warn(
            "{}: no network ({}); resuming {} when it is back".format(
                c.node, (res.say or stop.reason)[:120], ("thread " + a.resume) if a.resume else "on a new thread"
            )
        )
        waited, back = self.await_net(c.up_now, a.max_s)
        c.counts["waited_net_s"] += waited
        if not back:
            return self.act(c, res, stop, lp.Yield("PAUSE_NETWORK", self.wc.ops.stop_say(stop)))
        e.steps.move(
            c.step or c.node,
            "network_wait",
            f"the network was down {int(waited)} s; the step goes on in {('thread ' + a.resume) if a.resume else 'a new thread'}",
        )
        self.wc.again(c, a.resume, stop=stop)

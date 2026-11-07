"""Recovery legs within one delegate call, with combined usage."""

import argparse
from collections.abc import Callable

from delegate.app import answer, env, net
from delegate.contracts.json_types import Json, arr, as_num, as_opt_obj, as_opt_str
from delegate.domain.cost import accounting

CONTINUE_NOTE = "The connection dropped. Continue from where you stopped; your last output was cut. Do not restart."


def merge(res: dict[str, Json], again: dict[str, Json]) -> dict[str, Json]:
    """Keep the last leg's answer and all legs' charges."""
    tok = [x for x in (as_opt_obj(res.get("tokens")), as_opt_obj(again.get("tokens"))) if x]
    again["tokens"] = {k: sum(as_num(x.get(k)) or 0 for x in tok) for k in ("in", "cached", "out")} if tok else None
    again["acct"] = accounting.merge(as_opt_obj(res.get("acct")), as_opt_obj(again.get("acct")))
    again["cost"] = (as_num(res.get("cost")) or 0) + (as_num(again.get("cost")) or 0)
    again["cumulative"] = again.get("cumulative") or res.get("cumulative")
    again["denied"] = [*arr(res.get("denied")), *arr(again.get("denied"))]
    return again


def network(
    res: dict[str, Json],
    launch_one: Callable[[str, env.Args, str], dict[str, Json]],
    brief: str,
    args: env.Args,
    lane: str,
    now: Callable[[], float],
    sleep: Callable[[float], object],
) -> dict[str, Json]:
    """Re-ask once after a network stop, waiting at most ten minutes inside this call."""
    if res.get("outcome") != "network":
        return res
    _, back = net.wait_up(lane, 600, now, sleep)
    if not back:
        return res
    ref = as_opt_str(res.get("ref")) if res.get("started") else None
    if res.get("started") and not ref:
        return res  # work started but the vendor gave no session to resume
    again = launch_one(
        CONTINUE_NOTE if ref else brief,
        argparse.Namespace(**dict(vars(args), resume=ref or args.resume)),
        "network_rerun",
    )
    return merge(res, again)


def lane_wait(
    res: dict[str, Json],
    launch_one: Callable[[str, env.Args, str], dict[str, Json]],
    brief: str,
    args: env.Args,
    now: Callable[[], float],
    sleep: Callable[[float], object],
    wall: Callable[[], float],
) -> dict[str, Json]:
    """Poll a transient lane three times; spend at most 180 seconds on predicted recovery."""
    polls, waited, immediate_retried = 0, 0.0, False
    while res.get("outcome"):
        facts = answer.result(as_opt_str(res.get("outcome")), **{k: v for k, v in res.items() if k != "outcome"})
        stop = as_opt_obj(facts.get("stop")) or {}
        retry = as_opt_obj(stop.get("retry")) or {}
        if stop.get("permanence") != "transient":
            break
        scope, kind, at = stop.get("scope"), retry.get("kind"), as_num(retry.get("at")) or 0
        if scope in ("lane", "model", "bead") and kind == "poll":
            if polls >= 3:
                break
            gap = at if 0 < at <= 180 else 20
            polls += 1
            attempt = "lane_poll"
        elif scope in ("lane", "model") and kind == "predicted":
            gap = max(0.0, at - wall())
            if gap > 180 - waited or (gap == 0 and immediate_retried):
                break
            immediate_retried = gap == 0
            attempt = "lane_wait"
        else:
            break
        started = now()
        sleep(gap)
        waited += max(gap, now() - started)
        ref = as_opt_str(res.get("ref")) if res.get("resumable") else None
        again = launch_one(
            CONTINUE_NOTE if ref else brief,
            argparse.Namespace(**dict(vars(args), resume=ref or args.resume)),
            attempt,
        )
        res = merge(res, again)
    return res


def worker_failure(res: dict[str, Json]) -> bool:
    """Only transient bead failures belong to the one worker retry."""
    facts = answer.result(as_opt_str(res.get("outcome")), **{k: v for k, v in res.items() if k != "outcome"})
    stop = as_opt_obj(facts.get("stop")) or {}
    retry = as_opt_obj(stop.get("retry")) or {}
    return (
        stop.get("scope") == "bead"
        and stop.get("permanence") == "transient"
        and retry.get("kind") in ("none", "predicted")
        and stop.get("reason") in ("worker_failed", "timeout")
    )


def hurt_write(res: dict[str, Json], args: env.Args) -> bool:
    """A timed-out or terminated writer must move to another pair."""
    return (
        getattr(args, "role", None) == "worker"
        and worker_failure(res)
        and (res.get("outcome") == "timeout" or res.get("exit_code") == -15)
    )


def retry(
    res: dict[str, Json],
    launch_one: Callable[[str, env.Args, str], dict[str, Json]],
    brief: str,
    args: env.Args,
) -> dict[str, Json]:
    """Retry one real worker leg, resuming only a resumable session; keep both charges."""
    if not worker_failure(res) or hurt_write(res, args):
        return res
    ref = as_opt_str(res.get("ref")) if res.get("resumable") else None
    again = launch_one(
        CONTINUE_NOTE if ref else brief,
        argparse.Namespace(**dict(vars(args), resume=ref)),
        "worker_retry",
    )
    return merge(res, again)

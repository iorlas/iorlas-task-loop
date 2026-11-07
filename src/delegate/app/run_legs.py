"""Recovery legs within one delegate call, with combined usage."""

import argparse
from collections.abc import Callable

from delegate.app import env, net
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

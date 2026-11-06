"""Which untracked file a stage meant (tl-bxk.10.24): a pure function of the ignore globs, the files a review accepted and the plan.
It lives here, not on the engine's `NewFiles` part, so the checkout can ask it without reaching back into a part that reads the checkout
(docs/design/engine-order.md)."""
import fnmatch
from collections.abc import Mapping, Sequence

from taskloop.contracts.paths import TASK_EXCLUDE


def planned(q: str, plan_data: Mapping[str, object] | None) -> bool:
    """A plan stage lists the file, or a folder or glob that holds it."""
    stages = (plan_data or {}).get("stages")
    for st in stages if isinstance(stages, list) else []:
        for listed in st["files"]:
            f = listed.strip().replace("\\", "/")
            f = "" if f in (".", "./") else f[2:] if f.startswith("./") else f
            if f and (q == f or q.startswith(f.rstrip("/") + "/") or fnmatch.fnmatchcase(q, f)):
                return True
    return False


def new_file_kind(path: str, ignore: Sequence[str], accepted: Sequence[str], plan_data: Mapping[str, object] | None) -> str:
    """"ignored" (engine.untracked_ignore: never staged, never listed), "meant" (a plan stage lists it or its folder in files, or a
    review accepted it) or "unexplained" (left out of the commit, listed in the review brief). A .meta follows the file it belongs to."""
    p = path.replace("\\", "/")
    if any(fnmatch.fnmatchcase(p, g) for g in ignore):
        return "ignored"
    if p.startswith(TASK_EXCLUDE):
        return "ignored"
    for q in (p, p[:-5]) if p.endswith(".meta") else (p,):
        if q in accepted or q + ".meta" in accepted or planned(q, plan_data):
            return "meant"
    return "unexplained"

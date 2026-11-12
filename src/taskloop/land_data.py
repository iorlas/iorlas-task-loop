"""The JSON shape of a land (tl-8bh9.14.8 section 14): a candidate (`tl step show`'s `land` key, null without one) and
`tl step land`'s answers (`Landed`, `Withdrawn`, `LandSummary`). Additive to `result_data`'s shapes; no dispatch token,
remote URL, Git output or log content. `synced` is always false: the land never shares the tracker (O4)."""

from taskloop.land import Landed
from taskloop.land_push import Withdrawn
from taskloop.land_status import LandView
from taskloop.land_store import LandRow
from taskloop.land_summary import Changed, LandSummary


def candidate_data(row: LandRow) -> dict[str, object]:
    """One candidate's stored facts: O, S, its validation, release, supersession, delivery and close."""
    return {
        "candidate_id": row.key.attempt_id, "number": row.number, "checks_attempt_id": row.checks, "origin": row.origin,
        "commit": row.commit, "tree_same": row.tree_same, "required": [name for name, _ in row.required], "slot": row.slot,
        "slot_head": row.slot_head, "deadline": row.deadline, "validation": row.validation, "reason": row.reason,
        "validated_at": row.validated_at, "released_at": row.released_at, "parked": row.parked, "superseded": row.superseded,
        "delivery": row.delivery, "delivered_at": row.delivered_at, "remote_head": row.remote_head, "close": row.close,
        "closed_at": row.closed_at, "land_process": None if row.entry is None else {"pid": row.entry[0], "start": row.entry[1],
                                                                                    "boot": row.entry[2]},
    }


def view_data(land: LandView | None) -> dict[str, object] | None:
    """`tl step show`'s `land`: the latest candidate, its land process as observed now, its latest block's results."""
    if land is None:
        return None
    logs = land.logs or (None,) * len(land.results)
    results = [{"name": each.name, "conclusion": each.conclusion, "rc": each.rc, "block": each.block, "started_at": each.started_at,
                "ended_at": each.ended_at, "log": None if log is None else str(log)} for each, log in zip(land.results, logs, strict=True)]
    return candidate_data(land.row) | {"process": land.process, "results": results}


def _task(row: LandRow) -> dict[str, object]:
    return {"backlog": row.backlog, "task": row.task_id, "candidate": candidate_data(row)}


def landed_data(found: Landed) -> dict[str, object]:
    return {"status": found.how, **_task(found.row), "release": found.release, "synced": False}


def withdrawn_data(found: Withdrawn) -> dict[str, object]:
    return {"status": "withdrawn", **_task(found.row)}


def land_data(found: Landed | Withdrawn | LandSummary) -> dict[str, object]:
    """`tl step land`'s answer: delivered (and closed), withdrawn, or the summary."""
    if isinstance(found, Landed):
        return landed_data(found)
    return withdrawn_data(found) if isinstance(found, Withdrawn) else summary_data(found)


def _changed(each: Changed) -> dict[str, object]:
    return {"name": each.name, "argv_at_origin": None if each.at_o is None else list(each.at_o.argv),
            "argv_at_x": None if each.at_x is None else list(each.at_x.argv)}


def summary_data(found: LandSummary) -> dict[str, object]:
    """The summary's facts (section 10), its message whole."""
    setup = None if found.setup is None else {"at_origin": [list(each) for each in found.setup[0]],
                                              "at_x": [list(each) for each in found.setup[1]]}
    return {
        "status": "summary", "checks_attempt_id": found.checks_id, "conclusion": found.conclusion, "target": found.target,
        "commit": found.x, "results": [{"name": name, "conclusion": result} for name, result in found.results], "origin": found.origin,
        "added": list(found.added), "removed": list(found.removed), "argv": [_changed(each) for each in found.argv],
        "checks": [_changed(each) for each in found.checks], "setup": setup, "files": list(found.files), "base": found.base,
        "state": found.state, "again": found.again, "conflicts": list(found.conflicts), "message": found.message,
    }

"""Pending delivery details through the same summary operation as the land command."""

import shlex
from pathlib import Path

from taskloop.dash_model import LandDetail
from taskloop.land import LandRequest, land
from taskloop.land_check import LandPorts
from taskloop.land_summary import LandSummary, lines
from taskloop.operations import Failed


def _actions(found: LandSummary) -> tuple[str, ...]:
    if found.state == "conflict":
        return ("Delivery is blocked by conflicts; resolve the task's changes before integration.",)
    if found.conclusion != "passed":
        return ("Delivery is blocked until the task's checks pass.",)
    if found.state == "no_change":
        return ("Record that main already contains the task's changes and mark the task complete.",)
    return (
        *(("Validate the changes against current main with the required checks.",) if found.again else ()),
        *(("The changes to the check gate require your acceptance before delivery.",)
          if found.gate is not None and found.gate.decisive else ()),
        "Integrate the task's changes into main on origin.",
        "Mark the task complete.",
    )


def build_land(ports: LandPorts, backlog: str, task_id: str, checkout: Path) -> LandDetail | Failed:
    """Summary only: may fetch and create Git objects, but never validate, deliver, close or claim."""
    found = land(ports, LandRequest(backlog, task_id, checkout, None, "summary"))
    if isinstance(found, Failed):
        return found
    if not isinstance(found, LandSummary):
        return Failed("unavailable", "land", "The delivery summary could not be read.")
    changes = None if found.gate is None else found.gate.changes
    command = shlex.join(("tl", "step", "land", task_id, "--backlog", backlog, "--checkout", str(checkout)))
    if found.again:
        command += " --minutes N"
    if found.state == "no_change":
        command += " --no-change"
    return LandDetail(
        actions=_actions(found), summary=lines(found),
        diff_files=None if changes is None else len(changes),
        added=None if changes is None else sum(each.added for each in changes),
        deleted=None if changes is None else sum(each.deleted for each in changes),
        diff_command=shlex.join(("git", "diff", f"{found.base}..{found.x}")), command=command,
    )

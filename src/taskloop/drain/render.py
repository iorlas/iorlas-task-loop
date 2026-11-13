"""One codec for drain progress and final results, in human and structured form."""

from taskloop.drain.models import Conclusion, Result
from taskloop.printable import one_line


def data(result: Result) -> dict[str, object]:
    return {
        **result.model_dump(mode="json"),
        "active_count": len(result.active),
        "uncertain_count": len(result.uncertain),
        "pending_actions": len(result.actions),
    }


def human(result: Result) -> str:
    lines = [_human(result)]
    for owner in (*result.active, *result.uncertain):
        process = owner.identity
        lines.append(
            f"{owner.role.value} {one_line(owner.subject, 200)}: pid={process.pid} pgid={process.pgid} "
            f"start={one_line(process.start, 200)} boot={one_line(process.boot, 200)}"
        )
    return "\n".join(lines)


def _human(result: Result) -> str:
    if result.conclusion is Conclusion.COMPLETE:
        return (
            "New work is blocked. Idle was verified: no execution owners, owned processes or unresolved actions remain. "
            "The fence remains in place. The owner can now decide whether to restart with matching code or discard "
            "local execution state for an incompatible upgrade."
        )
    if result.conclusion is Conclusion.WAITING:
        return f"{result.detail} Waiting: {len(result.active)} active, {len(result.actions)} unresolved actions."
    return (
        f"{result.detail} Idle was not verified. Active: {len(result.active)}; uncertain: {len(result.uncertain)}; "
        f"unresolved actions: {len(result.actions)}."
    )

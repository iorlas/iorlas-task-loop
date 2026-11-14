"""One human explanation of stored stop attribution, shared by holds and status projections."""

from taskloop.agents.stop_models import AgentStop, StopCause

_WHY = {
    StopCause.DEADLINE: "its attempt deadline expired",
    StopCause.FIRST_OUTPUT: "its deadline for the first output expired",
    StopCause.INACTIVITY: "its inactivity deadline expired",
    StopCause.STALLED: "its response stalled",
    StopCause.ANSWER: "its answer grace period ended",
    StopCause.POLICY: "its activity violated the execution policy",
    StopCause.LIMIT: "its usage limit was reached",
    StopCause.CREDIT: "its account credit was exhausted",
    StopCause.AUTHENTICATION: "its authentication was lost",
    StopCause.NETWORK: "its network connection failed",
    StopCause.WATCHDOG: "its execution watchdog requested a stop",
    StopCause.ENTRY_SIGNAL: "its entry received a signal",
    StopCause.INTERRUPT: "its entry was interrupted",
    StopCause.PARENT_LOST: "its supervising parent disappeared",
    StopCause.CALLER_EXIT: "its supervising call exited exceptionally",
}


def signal_name(number: int) -> str:
    return {1: "SIGHUP", 2: "SIGINT", 9: "SIGKILL", 15: "SIGTERM"}.get(number, f"signal {number}")


def stop_text(record: AgentStop | None, rc: int | None = None) -> str | None:
    if record is None:
        return (f"The agent ended with {signal_name(-rc)}; the factory has no recorded sender or stop cause."
                if rc is not None and rc < 0 else None)
    signal = signal_name(record.requested_signal)
    proof = record.proof
    delivered = proof is not None and (proof.term_delivered or proof.kill_delivered)
    prefix = ""
    if record.trigger_signal is not None:
        prefix = f"The entry received {signal_name(record.trigger_signal)}; the sender of the entry signal is unknown. "
    action = ("The factory sent " + ("SIGTERM" if proof is not None and proof.term_delivered else "SIGKILL")
              if delivered else f"The factory requested an agent stop with {signal}")
    text = prefix + action + " because " + _WHY[record.cause] + "."
    if proof is None:
        text += " No signal delivery was confirmed."
    else:
        if proof.term_delivered and proof.kill_delivered:
            text += " It escalated to SIGKILL."
        if not delivered:
            text += " No signal delivery was confirmed."
        if proof.error or proof.survivors:
            text += " The stop did not prove that the agent's whole process tree ended."
    if rc is not None and rc < 0:
        text += f" The agent ended with {signal_name(-rc)}."
    if record.observed_gone_at is not None:
        text += " The recorded agent and its process group were subsequently observed gone."
    return text

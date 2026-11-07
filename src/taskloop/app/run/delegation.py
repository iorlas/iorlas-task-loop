"""The delegate the next call goes through: the library, checked against the call's grants."""
from typing import Any

from taskloop.contracts.delegateport import Refusal, Resolved
from taskloop.domain.lanes import pin


class Delegation:
    def __init__(self, host: Any) -> None:
        self.e = host

    def route(self, quiet: bool = False) -> str:
        """The delegate for the next call (tl-6ax): resolved again each call. A refused one (a grant the contract does not carry) keeps the
        one in use (noted); with none in use the run says why."""
        e = self.e
        new = e.router.resolve()
        if isinstance(new, Resolved) and e.cfg.writer_exec_allow:
            why = pin.exec_allow_problem(e.cfg.writer_exec_allow, e.cfg.writer_family, e.budget.labels,
                                         new.contract.get("contract", 0), new.contract.get("capabilities", []))
            if why:
                new = Refusal("writer_exec_allow", why)
        if isinstance(new, Refusal):
            if e.resolved is None:
                e.refusal = new
            elif not quiet:
                e.log.note(f"delegate not switched: {new.kind} {new.detail}; keeping {e.route}")
            return str(e.route)
        if e.resolved is not None and new.route != e.resolved.route and not quiet:
            e.log.note(f"delegate switched: {e.route} -> {new.route}")
        e.resolved, e.route, e.contract, e.refusal = new, new.route, new.contract, None
        if not quiet:
            e.log.note(f"delegate call via {e.route}")
        return str(e.route)

    def net_probe(self) -> Any:
        """The network probe: a test's, else delegate's."""
        return self.e.probe or self.e.router.probe()

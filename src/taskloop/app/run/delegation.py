"""Which delegate install the next call goes through."""
from typing import Any

from taskloop.adapters import delegate as dg


class Delegation:
    def __init__(self, host: Any) -> None:
        self.e = host

    def route(self, quiet: bool = False) -> str:
        """The delegate for the next call (tl-6ax): resolved again each call (a configured path, then the pin, then the installed
        one). A refused one (another contract, a pin that is gone) keeps the one in use (noted); with none in use the run says why."""
        e = self.e
        new = e.router.resolve(e.cfg.delegate)
        if isinstance(new, dg.Refusal):
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
        """The network probe: a test's, else delegate's `route.py net`."""
        return self.e.probe or dg.RouteProbe(self.e.route)

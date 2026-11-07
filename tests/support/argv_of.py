"""The `route.py run` argv delegate would build for an engine request: what a test reads the flags of (the engine builds none)."""
from delegate import api
from taskloop.adapters.delegate import api_request
from tlkernel.delegate import RunRequest


def argv_of(req: RunRequest) -> list[str]:
    return api_request(req, {}).to_argv("route.py", contract=api.contract())

"""Spot a broken connection in an error text."""

from __future__ import annotations

import re

# `max_output_tokens` after "stream disconnected" is the model's cap, not the network.
_DROP = re.compile(
    r"ENOTFOUND|ECONNRESET|ECONNREFUSED|ECONNABORTED|ETIMEDOUT|EAI_AGAIN|EPIPE|getaddrinfo"
    r"|could not resolve host|network is unreachable|cannot connect to api|unable to connect"
    r"|error sending request|connection (reset|closed|refused|timed out|failed)|socket hang up"
    r"|dns error|network error|waiting for network|(?:TLS|SSL) handshake"
    r"|stream disconnected(?!.{0,200}max_output_tokens)",
    re.IGNORECASE | re.DOTALL,
)


def looks_dropped(text: str | None) -> bool:
    """True when `text` (a vendor error event or stderr, never a model answer) says the connection broke."""
    return bool(_DROP.search(text or ""))

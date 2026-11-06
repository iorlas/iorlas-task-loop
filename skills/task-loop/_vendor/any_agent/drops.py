"""Did the connection break? Words in a vendor's error or stderr that say so (never the model's answer)."""

import re

DROP_RE = re.compile(
    r"ENOTFOUND|ECONNRESET|ECONNREFUSED|ECONNABORTED|ETIMEDOUT|EAI_AGAIN|EPIPE|getaddrinfo|could not resolve host|network is unreachable"
    r"|cannot connect to api|unable to connect|error sending request|connection (reset|closed|refused|timed out|failed)|socket hang up"
    r"|dns error|network error|waiting for network|(?:TLS|SSL) handshake|stream disconnected(?!.{0,200}max_output_tokens)",
    re.IGNORECASE | re.DOTALL,
)


def looks_dropped(text: str | None) -> bool:
    """True when `text` (a vendor error event or stderr, never the model's answer) says the connection broke."""
    return bool(DROP_RE.search(text or ""))

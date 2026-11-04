"""Credential-safe text for command diagnostics, without changing parsed data or raw bytes."""

from __future__ import annotations

import re

_URL_USERINFO = re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://)[^\s/?#]*@")


def redact_output(text: str) -> str:
    """Hide URL userinfo in diagnostics, retaining the scheme, host and path."""
    return _URL_USERINFO.sub(r"\1***@", text)

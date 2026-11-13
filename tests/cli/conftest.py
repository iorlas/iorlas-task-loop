"""Capability requirements shared by CLI tests."""

import errno
import socket

import pytest


@pytest.fixture(scope="session")
def require_loopback() -> None:
    """Skip real server tests only when the environment denies loopback TCP."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
    except OSError as error:
        if error.errno in {errno.EPERM, errno.EACCES}:
            pytest.skip(f"Loopback TCP sockets unavailable in this environment: {error}")
        raise

"""An unexpected failure answers 500 with a fixed body: no exception text, path or record reaches the client; stderr has the traceback."""

import io
import sys

import pytest

from taskloop_dash import http


def test_the_client_sees_nothing_of_the_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)
    code, body, ctype = http.internal_error("GET /api/bead", KeyError("/home/me/secret/path.json"))
    assert (code, ctype) == (500, "application/json")
    assert body == b'{"error": "internal error"}'
    assert b"secret" not in body and b"KeyError" not in body
    err = stderr.getvalue()
    assert "GET /api/bead" in err and "KeyError" in err and "/home/me/secret/path.json" in err

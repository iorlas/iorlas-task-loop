"""opencode_size: the last assistant message with tokens, from OpenCode's session store."""
import json
import sqlite3

import pytest
from delegate.adapters import opencode_size

SID = "ses_abc123"


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "opencode.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, time_updated INTEGER, data TEXT)")
    rows = [("m1", 1, {"role": "user"}), ("m2", 2, {"role": "assistant", "tokens": {"input": 9000, "cache": {"read": 4000, "write": 700}}}),
            ("m3", 3, {"role": "assistant", "tokens": {"input": 0}})]
    for i, t, d in rows:
        con.execute("INSERT INTO message VALUES (?,?,?,?,?)", (i, SID, t, t, json.dumps(d)))
    con.commit()
    con.close()
    monkeypatch.setenv("OPENCODE_DB", str(path))


def test_context_is_the_last_assistant_message_with_tokens(db):
    assert opencode_size.context_k("opencode:" + SID) == 13.7
    assert opencode_size.context_k(SID) == 13.7


def test_an_unknown_session_or_a_missing_store_is_none(db, monkeypatch):
    assert opencode_size.context_k("opencode:ses_nope") is None
    assert opencode_size.context_k("not-a-session") is None
    monkeypatch.setenv("OPENCODE_DB", "/nonexistent/o.db")
    assert opencode_size.context_k(SID) is None

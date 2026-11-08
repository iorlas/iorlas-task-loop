"""Stable consumer names and the engine's public path matcher."""
import contextlib
import io
import json
from pathlib import Path

import pytest

from taskloop.domain import selfdescribe
from tlkernel import envvars
from tlkernel.checkmatchers import cmd_match

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "golden/consumer_api.json"


def test_consumer_names_match_golden():
    actual = {"CONSUMER": [name for name, _ in envvars.CONSUMER], "PRIVATE": list(envvars.PRIVATE)}
    assert actual == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_consumer_names_are_registered():
    assert all(envvars.registered(name) for name, _ in envvars.CONSUMER)


def test_selfdescription_lists_consumer_api():
    text = selfdescribe.text()
    assert all(name in text for name, _ in envvars.CONSUMER)
    assert "tl match GLOB... -- PATH...:" in text


def test_contract_lists_consumer_names():
    text = (ROOT / "docs/contracts/consumer-api.md").read_text(encoding="utf-8")
    assert all(name in text for name, _ in envvars.CONSUMER)


@pytest.mark.parametrize(("args", "output", "status"), [
    (["{a,b}.py", "--", "a.py", "c.py", "b.py"], "a.py\nb.py\n", 0),
    (["src/**/*.py", "--", "src/a.py", "src/deep/b.py", "other.py"], "src/a.py\nsrc/deep/b.py\n", 0),
    (["a.py", "--", "a.py.bak", "dir/a.py"], "", 1),
    (["*.py", "*.txt", "--", "a.py", "b.txt"], "a.py\nb.txt\n", 0),
])
def test_match(args, output, status):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        assert cmd_match(args) == status
    assert stream.getvalue() == output


def test_match_without_the_separator_is_a_usage_error():
    with pytest.raises(SystemExit):
        cmd_match(["a/**"])

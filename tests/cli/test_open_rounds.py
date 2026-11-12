"""The real `cli_composition.open_rounds` over a real factory.db: a refusal installs no handler, the handler goes with the block
however it ends and the rounds lock with it, and the ports carry this process's pid. The handler itself is a recording stub:
tests never install a signal handler."""

import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlite_store import Store

from taskloop.cli_composition import open_rounds
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitViews
from taskloop.interrupts import Interrupts
from taskloop.operations import Failed
from taskloop.round import NextRequest

REQUEST = NextRequest("tasks", "/tracker", Path("/checkout"), "auto", "m", "high", 30)


class Handler:
    """A stand-in for `interrupts.installed`: records the lives of its handler."""

    def __init__(self) -> None:
        self.live, self.installed = False, 0

    @contextmanager
    def install(self, say: object) -> Generator[Interrupts]:
        self.live, self.installed = True, self.installed + 1
        try:
            yield Interrupts(print, lambda: None)
        finally:
            self.live = False


def factory(tmp_path: Path) -> Path:
    database = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(database)
    assert con is not None
    con.close()
    return database


def test_a_refused_rounds_installs_no_handler(tmp_path: Path) -> None:
    handler = Handler()
    with open_rounds(tmp_path / "absent.db", tmp_path / "art", GitViews(30), REQUEST, handler.install) as ports:
        assert isinstance(ports, Failed) and ports.reason == "database"
    assert handler.installed == 0


def test_a_raise_inside_the_block_restores_the_handler_and_frees_the_lock(tmp_path: Path) -> None:
    database, handler = factory(tmp_path), Handler()
    with pytest.raises(RuntimeError), open_rounds(database, tmp_path / "art", GitViews(30), REQUEST, handler.install) as ports:
        assert not isinstance(ports, Failed) and handler.live
        raise RuntimeError
    assert not handler.live
    with open_rounds(database, tmp_path / "art", GitViews(30), REQUEST, handler.install) as again:
        assert not isinstance(again, Failed) and handler.installed == 2


def test_the_ports_carry_this_process_s_pid(tmp_path: Path) -> None:
    with open_rounds(factory(tmp_path), tmp_path / "art", GitViews(30), REQUEST, Handler().install) as ports:
        assert not isinstance(ports, Failed) and ports.pid == os.getpid()

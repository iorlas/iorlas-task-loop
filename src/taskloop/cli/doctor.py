"""Dispatch the doctor command's diagnostic modes."""
from argparse import Namespace

from taskloop.app.doctor import rails, setup_checks
from taskloop.app.launch import reindex
from taskloop.app.wire import doctor
from taskloop.cli.ctx import Ctx


def run(a: Namespace, c: Ctx) -> int:
    if a.reindex:
        return reindex.run(c.who.config)
    if a.disk:
        return setup_checks.disk_run(c.who.config)
    if a.print_guard_rails:
        return rails.print_calls(c.git)
    return doctor.run(c.here.parents[1], c.env, c.git, c.who, c.spawner)

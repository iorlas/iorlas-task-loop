"""`tl dash` calls the launch rule with the signature it has (an autospec refuses a wrong call, as the unchecked caller once was)."""
from argparse import Namespace
from pathlib import Path
from unittest import mock

from support.tlmain import tl

from taskloop.app.launch import dash
from taskloop.app.parts import STAGE_PARTS
from taskloop.cli.ctx import Ctx
from tlkernel.env import snapshot


def test_the_dash_verb_passes_the_installed_part_versions():
    env = snapshot()
    spec = mock.create_autospec(dash.run, return_value=0)
    ctx = Ctx(Path("."), lambda: 0.0, [], env, spawner=mock.Mock(), git=mock.Mock(), who=mock.Mock())
    with mock.patch.object(tl.wire_dash, "run", spec):
        assert tl.VERBS["dash"](Namespace(op="url"), ctx) == 0
    spec.assert_called_once_with("url", env, ctx.spawner, {p.name: p.version for p in STAGE_PARTS})

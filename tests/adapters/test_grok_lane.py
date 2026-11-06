"""tl-bxk.10.32: the Grok lane (delegate family xai, OpenCode): its name and its fresh-writer limit."""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.builders import cfg_with
from support.spawn import port_git

from taskloop.app.write.handoff import Handoff
from taskloop_dash.views import names


def test_a_logged_out_xai_lane_says_grok_and_opencode():
    assert names.lane_name("GROK_SUBSCRIPTION", "") == "Grok"
    assert names.lane_name("x", "xai") == "Grok"


def test_xai_has_its_own_fresh_writer_limit():
    eng = types.SimpleNamespace(cfg=cfg_with())
    assert Handoff(eng, port_git()).fresh_above_k("xai") == 100.0
    eng.cfg = cfg_with(write_fresh_above_k={"xai": 40})
    assert Handoff(eng, port_git()).fresh_above_k("xai") == 40.0
    eng.cfg = cfg_with(write_fresh_above_k={"claude": 1})
    assert Handoff(eng, port_git()).fresh_above_k("xai") == 100.0


def test_a_lane_named_openai_xai_is_grok_by_family_or_name():
    assert names.lane_name("OPENAI_XAI") == "Grok"
    assert names.lane_name("OPENAI_SUBSCRIPTION") == "Codex"

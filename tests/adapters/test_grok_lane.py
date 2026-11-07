"""tl-bxk.10.32: the Grok lane (delegate family xai, OpenCode): its display name."""
from taskloop_dash.views import names


def test_a_logged_out_xai_lane_says_grok_and_opencode():
    assert names.lane_name("GROK_SUBSCRIPTION", "") == "Grok"
    assert names.lane_name("x", "xai") == "Grok"


def test_a_lane_named_openai_xai_is_grok_by_family_or_name():
    assert names.lane_name("OPENAI_XAI") == "Grok"
    assert names.lane_name("OPENAI_SUBSCRIPTION") == "Codex"

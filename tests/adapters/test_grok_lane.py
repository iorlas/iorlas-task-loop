"""tl-bxk.10.32: the Grok lane (delegate family xai, OpenCode): its display name."""
from tldash.views import names


def test_a_lane_uses_the_reported_family():
    assert names.lane_name("GROK_SUBSCRIPTION", "") == "Grok"
    assert names.lane_name("x", "xai") == "Xai"


def test_a_lane_without_family_uses_its_first_part():
    assert names.lane_name("OPENAI_XAI") == "Openai"
    assert names.lane_name("OPENAI_SUBSCRIPTION") == "Openai"


def test_lane_names_accept_unknown_families_and_empty_values():
    assert names.lane_name("OLD_LANE", "new_family") == "New_Family"
    assert names.lane_name("OPENAI_XAI", "xai") == "Xai"
    assert names.lane_name("ANTHROPIC_SUBSCRIPTION") == "Anthropic"
    assert names.lane_name(None, None) == ""
    assert names.lane_name() == ""

"""tl-bxk.10.32: the Grok account (delegate family xai, OpenCode): its display name."""
from tldash.views import names


def test_a_account_uses_the_reported_family():
    assert names.account_name("GROK_SUBSCRIPTION", "") == "Grok"
    assert names.account_name("x", "xai") == "Xai"


def test_a_account_without_family_uses_its_first_part():
    assert names.account_name("OPENAI_XAI") == "Openai"
    assert names.account_name("OPENAI_SUBSCRIPTION") == "Openai"


def test_account_names_accept_unknown_families_and_empty_values():
    assert names.account_name("OLD_ACCOUNT", "new_family") == "New_Family"
    assert names.account_name("OPENAI_XAI", "xai") == "Xai"
    assert names.account_name("ANTHROPIC_SUBSCRIPTION") == "Anthropic"
    assert names.account_name(None, None) == ""
    assert names.account_name() == ""

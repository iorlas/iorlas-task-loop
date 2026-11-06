"""xAI (Grok), reached through opencode."""

from any_agent.vendors import Vendor

VENDOR = Vendor(
    name="xai",
    credit=(r"spend(ing)?[- ]?(limit|control)", r"personal-team-blocked"),
    spend=(r"cycle cap", r"cap reached"),
)

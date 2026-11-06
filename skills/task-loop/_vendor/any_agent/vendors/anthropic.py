"""Anthropic: `claude -p` and the API behind it."""

from any_agent.vendors import Vendor

VENDOR = Vendor(
    name="anthropic",
    limit=(r"credit balance",),  # "Credit balance is too low" arrives as a limit and as a spent balance
    credit=(r"credit balance",),
    login=(r"please (run|use) [`'\"]?\S*\s*login", r"oauth session expired", r"failed to authenticate"),
    bad_request=(r"invalid_request_error",),
)

"""OpenAI: `codex exec` and the API behind it."""

from any_agent.vendors import Vendor

VENDOR = Vendor(
    name="openai",
    bad_request=(r"invalid_request_error", r"invalid_json_schema", r"Invalid schema for response_format"),
)

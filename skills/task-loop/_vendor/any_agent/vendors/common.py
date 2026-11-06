"""The phrasing every HTTP API, OS and command line shares."""

from any_agent.vendors import Vendor

VENDOR = Vendor(
    name="common",
    limit=(r"usage limit", r"rate.?limit", r"quota", r"too many requests", r"\b429\b", r"try again (later|in)"),
    credit=(r"out of credits", r"insufficient (funds|credit)", r"credits? (exhausted|too low)"),
    spend=(r"top[- ]?up", r"billing"),
    login=(r"not logged in", r"401 unauthorized", r"invalid api key"),
    network=(
        r"ENOTFOUND",
        r"ECONNRESET",
        r"ECONNREFUSED",
        r"ETIMEDOUT",
        r"EAI_AGAIN",
        r"getaddrinfo",
        r"could not resolve host",
        r"network is unreachable",
        r"cannot connect to api",
        r"unable to connect",
    ),
    bad_request=(r"unrecognized arguments:", r"error: unknown argument"),  # a flag the CLI no longer takes
)

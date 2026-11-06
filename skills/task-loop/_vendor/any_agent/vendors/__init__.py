"""One module per API vendor: the words its errors use for a limit, a spent balance, a login, a refused request or a broken network.

A vendor is data (`Vendor`: regex sources by reason), not code; `common` holds the phrasing every HTTP API and OS shares. The ladder
(`any_agent.classify`) merges `common` with every registered vendor, or with the ones a caller names. A harness is not a vendor: one CLI
(opencode) speaks to many vendors, and one vendor (Anthropic) is spoken to by more than one CLI. What only a CLI says is in its own
harness module.

Add a vendor by writing a module that builds a `Vendor` and listing it in `REGISTRY`; a vendor adds, never removes, a pattern.
"""

import re
from functools import cache

from any_agent._json import record


@record
class Vendor:
    """Regex sources (joined with `|`, matched case-insensitively) by the reason they name."""

    name: str
    limit: tuple[str, ...] = ()  # a rate or usage limit: wait
    credit: tuple[str, ...] = ()  # a spent balance: the lane is out until someone pays
    spend: tuple[str, ...] = ()  # more prose that means money (cockpit); `credit` counts too
    login: tuple[str, ...] = ()
    network: tuple[str, ...] = ()
    bad_request: tuple[str, ...] = ()  # the vendor refused the request itself


@record
class Words:
    """The compiled patterns of a set of vendors."""

    limit: re.Pattern[str]
    credit: re.Pattern[str]
    spend: re.Pattern[str]
    login: re.Pattern[str]
    network: re.Pattern[str]
    bad_request: re.Pattern[str]


def _join(parts: list[str]) -> re.Pattern[str]:
    return re.compile("|".join(parts) if parts else r"(?!)", re.IGNORECASE)


def registry() -> dict[str, Vendor]:
    from any_agent.vendors import anthropic, common, openai, xai  # noqa: PLC0415 - they import Vendor from here

    return {v.name: v for v in (common.VENDOR, anthropic.VENDOR, openai.VENDOR, xai.VENDOR)}


@cache
def _words(names: tuple[str, ...]) -> Words:
    vs = [v for n, v in registry().items() if n == "common" or not names or n in names]
    pick = lambda f: [p for v in vs for p in getattr(v, f)]  # noqa: E731
    return Words(
        limit=_join(pick("limit")),
        credit=_join(pick("credit")),
        spend=_join(pick("credit") + pick("spend")),
        login=_join(pick("login")),
        network=_join(pick("network")),
        bad_request=_join(pick("bad_request")),
    )


def words(names: tuple[str, ...] = ()) -> Words:
    """The patterns of `common` and the named vendors (every registered vendor when none is named). Unknown names raise KeyError."""
    for n in names:
        if n not in registry():
            raise KeyError(n)
    return _words(tuple(sorted(names)))

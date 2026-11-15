"""Keep import exceptions exact, reviewed and removable without leaving spare permissions."""

from configparser import ConfigParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "importlinter:contract:"
APPROVED_EXCEPTIONS = {
    f"{PREFIX}no-runtime-mechanisms": {
        ("taskloop.dash_server", "http.server"),
        ("taskloop.shelf_digest.identities", "urllib.parse"),
    },
    f"{PREFIX}process-lock-owners": {
        ("taskloop.slot_lock", "process_lock"),
        ("taskloop.rounds_lock", "process_lock"),
    },
    f"{PREFIX}one-signal-owner": {("taskloop.interrupts", "signal")},
}


@pytest.fixture
def config() -> ConfigParser:
    configuration = ConfigParser(interpolation=None)
    configuration.read_string((ROOT / ".importlinter").read_text())
    return configuration


def exception_lists(config: ConfigParser) -> dict[str, set[tuple[str, str]]]:
    exceptions: dict[str, set[tuple[str, str]]] = {}
    assert "ignore_imports" not in config.defaults(), "Exceptions must belong to a contract"
    for section in config.sections():
        if not config.has_option(section, "ignore_imports"):
            continue
        edges: set[tuple[str, str]] = set()
        for line in config[section]["ignore_imports"].splitlines():
            if not line.strip():
                continue
            importer, separator, imported = line.strip().partition(" -> ")
            assert separator, f"Expected an exact import edge: {line}"
            assert all(part.isidentifier() for module in (importer, imported) for part in module.split(".")), line
            edges.add((importer, imported))
        exceptions[section] = edges
    return exceptions


def assert_exception_ceiling(config: ConfigParser, approved: dict[str, set[tuple[str, str]]]) -> None:
    actual = exception_lists(config)
    assert actual.keys() <= approved.keys(), "An exception-bearing contract needs a reviewed initial census"
    for section, edges in actual.items():
        assert edges <= approved[section], f"Exceptions grew in {section}: {edges - approved[section]}"
    assert actual == approved, "Remove resolved exceptions from the approved ceiling in the same change"


def assert_strict_exceptions(config: ConfigParser) -> None:
    assert "unmatched_ignore_alerting" not in config.defaults(), "Set unmatched-ignore handling explicitly per contract"
    for section in exception_lists(config):
        assert config[section].get("unmatched_ignore_alerting") == "error", section


def test_exception_lists_do_not_grow(config: ConfigParser) -> None:
    assert_exception_ceiling(config, APPROVED_EXCEPTIONS)


def test_exception_lists_are_explicit_and_strict(config: ConfigParser) -> None:
    assert_strict_exceptions(config)


@pytest.mark.parametrize("edge", [
    "taskloop.profile -> http.server",
    "taskloop.* -> http.server",
    "taskloop.dash_server -> http.*",
    "taskloop.dash_server -> http.**",
    "taskloop.dash_server http.server",
])
def test_unapproved_or_wildcard_exception_fails(config: ConfigParser, edge: str) -> None:
    config[f"{PREFIX}no-runtime-mechanisms"]["ignore_imports"] += f"\n{edge}"
    with pytest.raises(AssertionError):
        assert_exception_ceiling(config, APPROVED_EXCEPTIONS)


def test_exception_cannot_move_to_another_contract(config: ConfigParser) -> None:
    config[f"{PREFIX}one-signal-owner"]["ignore_imports"] += "\ntaskloop.dash_server -> http.server"
    with pytest.raises(AssertionError, match="Exceptions grew"):
        assert_exception_ceiling(config, APPROVED_EXCEPTIONS)


def test_unknown_exception_bearing_contract_fails(config: ConfigParser) -> None:
    config[f"{PREFIX}unreviewed"] = {
        "ignore_imports": "taskloop.profile -> http.server",
        "unmatched_ignore_alerting": "error",
    }
    with pytest.raises(AssertionError, match="reviewed initial census"):
        assert_exception_ceiling(config, APPROVED_EXCEPTIONS)


@pytest.mark.parametrize("alerting", [None, "warn", "none"])
def test_relaxed_or_implicit_unmatched_handling_fails(config: ConfigParser, alerting: str | None) -> None:
    section = config[f"{PREFIX}no-runtime-mechanisms"]
    if alerting is None:
        del section["unmatched_ignore_alerting"]
    else:
        section["unmatched_ignore_alerting"] = alerting
    with pytest.raises(AssertionError):
        assert_strict_exceptions(config)


def test_inherited_unmatched_handling_fails(config: ConfigParser) -> None:
    config["DEFAULT"]["unmatched_ignore_alerting"] = "error"
    del config[f"{PREFIX}no-runtime-mechanisms"]["unmatched_ignore_alerting"]
    with pytest.raises(AssertionError, match="explicitly per contract"):
        assert_strict_exceptions(config)


@pytest.mark.parametrize("remove_contract", [False, True])
def test_exception_and_ceiling_can_shrink_together(config: ConfigParser, remove_contract: bool) -> None:
    section = f"{PREFIX}no-runtime-mechanisms"
    approved = {name: edges.copy() for name, edges in APPROVED_EXCEPTIONS.items()}
    if remove_contract:
        del config[section]["ignore_imports"]
        del approved[section]
    else:
        config[section]["ignore_imports"] = "taskloop.dash_server -> http.server"
        approved[section].remove(("taskloop.shelf_digest.identities", "urllib.parse"))
    with pytest.raises(AssertionError, match="Remove resolved exceptions"):
        assert_exception_ceiling(config, APPROVED_EXCEPTIONS)
    assert_exception_ceiling(config, approved)
    assert_strict_exceptions(config)

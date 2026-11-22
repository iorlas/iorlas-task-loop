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


# Initial folder/privacy and connection-import census; remove entries with resolved imports.
APPROVED_EXCEPTIONS.update(
    {
        "importlinter:contract:slice-taskloop.agents": {
            ("taskloop.admit", "taskloop.agents.settings"),
            ("taskloop.admit_chain", "taskloop.agents.settings"),
            ("taskloop.agent_credentials", "taskloop.agents.launch"),
            ("taskloop.attempt", "taskloop.agents.launch"),
            ("taskloop.attempt", "taskloop.agents.stop"),
            ("taskloop.attempt", "taskloop.agents.stop_store"),
            ("taskloop.attempt_loads", "taskloop.agents.settings"),
            ("taskloop.attempt_reads", "taskloop.agents.settings"),
            ("taskloop.attempt_status", "taskloop.agents.stop_models"),
            ("taskloop.attempt_status", "taskloop.agents.stop_store"),
            ("taskloop.attempt_types", "taskloop.agents.settings"),
            ("taskloop.check_repeat.store", "taskloop.agents.settings"),
            ("taskloop.cli_step", "taskloop.agents.settings"),
            ("taskloop.composition", "taskloop.agents.launch"),
            ("taskloop.dash_board", "taskloop.agents.stop_text"),
            ("taskloop.dash_task", "taskloop.agents.stop_store"),
            ("taskloop.hold_cause", "taskloop.agents.stop_models"),
            ("taskloop.hold_cause", "taskloop.agents.stop_text"),
            ("taskloop.hold_facts", "taskloop.agents.stop_store"),
            ("taskloop.hold_guide", "taskloop.agents.stop_text"),
            ("taskloop.hold_text", "taskloop.agents.stop_models"),
            ("taskloop.land_conflict.composition", "taskloop.agents.launch"),
            ("taskloop.land_conflict.execute", "taskloop.agents.launch"),
            ("taskloop.machine_config", "taskloop.agents.config"),
            ("taskloop.machine_config", "taskloop.agents.settings"),
            ("taskloop.merge.models", "taskloop.agents.settings"),
            ("taskloop.merge.prepare", "taskloop.agents.launch"),
            ("taskloop.merge.resolve", "taskloop.agents.launch"),
            ("taskloop.operations", "taskloop.agents.settings"),
            ("taskloop.recovery.native", "taskloop.agents.launch"),
            ("taskloop.recovery.native", "taskloop.agents.stop"),
            ("taskloop.recovery.native", "taskloop.agents.stop_store"),
            ("taskloop.result_data", "taskloop.agents.config"),
            ("taskloop.result_data", "taskloop.agents.stop_text"),
            ("taskloop.round", "taskloop.agents.settings"),
            ("taskloop.slot_release", "taskloop.agents.stop"),
            ("taskloop.slot_release", "taskloop.agents.stop_store"),
            ("taskloop.step_render", "taskloop.agents.config"),
        },
        "importlinter:contract:slice-taskloop.check_repeat": {
            ("taskloop.attempt_reads", "taskloop.check_repeat.feedback"),
            ("taskloop.attempt_status", "taskloop.check_repeat.status"),
            ("taskloop.cli_composition", "taskloop.check_repeat.repair"),
            ("taskloop.cli_composition", "taskloop.check_repeat.store"),
            ("taskloop.evidence_files", "taskloop.check_repeat.feedback"),
            ("taskloop.implement_step", "taskloop.check_repeat.feedback"),
            ("taskloop.operations", "taskloop.check_repeat.feedback"),
            ("taskloop.operations", "taskloop.check_repeat.status"),
            ("taskloop.steps", "taskloop.check_repeat.feedback"),
        },
        "importlinter:contract:slice-taskloop.drain": {
            ("taskloop.admit", "taskloop.drain.models"),
            ("taskloop.admit", "taskloop.drain.observe"),
            ("taskloop.admit", "taskloop.drain.store"),
            ("taskloop.admit_chain", "taskloop.drain.models"),
            ("taskloop.admit_chain", "taskloop.drain.store"),
            ("taskloop.answer_repair", "taskloop.drain.models"),
            ("taskloop.answer_repair_store", "taskloop.drain.store"),
            ("taskloop.attempt_entry", "taskloop.drain.models"),
            ("taskloop.attempt_status_store", "taskloop.drain.models"),
            ("taskloop.attempt_write_store", "taskloop.drain.models"),
            ("taskloop.attempt_write_store", "taskloop.drain.store"),
            ("taskloop.check_admit", "taskloop.drain.models"),
            ("taskloop.check_admit", "taskloop.drain.store"),
            ("taskloop.check_release", "taskloop.drain.actions"),
            ("taskloop.check_release", "taskloop.drain.models"),
            ("taskloop.check_repeat.store", "taskloop.drain.models"),
            ("taskloop.check_repeat.store", "taskloop.drain.store"),
            ("taskloop.check_store", "taskloop.drain.models"),
            ("taskloop.check_store", "taskloop.drain.store"),
            ("taskloop.cli_composition", "taskloop.drain.composition"),
            ("taskloop.cli_composition", "taskloop.drain.drain"),
            ("taskloop.cli_composition", "taskloop.drain.models"),
            ("taskloop.cli_composition", "taskloop.drain.restart"),
            ("taskloop.cli_composition", "taskloop.drain.store"),
            ("taskloop.cli_drain", "taskloop.drain.composition"),
            ("taskloop.cli_drain", "taskloop.drain.drain"),
            ("taskloop.cli_drain", "taskloop.drain.models"),
            ("taskloop.cli_drain", "taskloop.drain.render"),
            ("taskloop.cli_step", "taskloop.drain.models"),
            ("taskloop.exit_codes", "taskloop.drain.models"),
            ("taskloop.factory_schema", "taskloop.drain.models"),
            ("taskloop.land", "taskloop.drain.actions"),
            ("taskloop.land", "taskloop.drain.models"),
            ("taskloop.launch", "taskloop.drain.actions"),
            ("taskloop.launch", "taskloop.drain.models"),
            ("taskloop.launch", "taskloop.drain.store"),
            ("taskloop.merge.models", "taskloop.drain.models"),
            ("taskloop.merge.resolve", "taskloop.drain.models"),
            ("taskloop.merge.store", "taskloop.drain.models"),
            ("taskloop.publish", "taskloop.drain.actions"),
            ("taskloop.publish", "taskloop.drain.models"),
            ("taskloop.recovery.continue_attempt", "taskloop.drain.models"),
            ("taskloop.recovery.entry", "taskloop.drain.models"),
            ("taskloop.recovery.execution_models", "taskloop.drain.models"),
            ("taskloop.recovery.launch", "taskloop.drain.models"),
            ("taskloop.recovery.models", "taskloop.drain.models"),
            ("taskloop.recovery.native", "taskloop.drain.models"),
            ("taskloop.recovery.observe", "taskloop.drain.models"),
            ("taskloop.recovery.recover", "taskloop.drain.models"),
            ("taskloop.recovery.registration", "taskloop.drain.models"),
            ("taskloop.recovery.status", "taskloop.drain.models"),
            ("taskloop.recovery.store", "taskloop.drain.models"),
            ("taskloop.recovery.store", "taskloop.drain.store"),
            ("taskloop.release_proof", "taskloop.drain.models"),
            ("taskloop.round", "taskloop.drain.actions"),
            ("taskloop.round", "taskloop.drain.models"),
            ("taskloop.round", "taskloop.drain.store"),
            ("taskloop.rounds", "taskloop.drain.models"),
            ("taskloop.setup_store", "taskloop.drain.models"),
            ("taskloop.slot_release", "taskloop.drain.actions"),
            ("taskloop.slot_release", "taskloop.drain.models"),
            ("taskloop.step_render", "taskloop.drain.models"),
            ("taskloop.commit", "taskloop.drain.actions"),
            ("taskloop.commit", "taskloop.drain.models"),
        },
        "importlinter:contract:slice-taskloop.land_conflict": {
            ("taskloop.cli_composition", "taskloop.land_conflict.composition"),
            ("taskloop.hold_facts", "taskloop.land_conflict.models"),
            ("taskloop.hold_facts", "taskloop.land_conflict.store"),
            ("taskloop.land", "taskloop.land_conflict.handoff"),
            ("taskloop.land_check", "taskloop.land_conflict.handoff"),
            ("taskloop.land_store", "taskloop.land_conflict.reservation_store"),
            ("taskloop.setup_store", "taskloop.land_conflict.reservation_store"),
        },
        "importlinter:contract:slice-taskloop.merge": {
            ("taskloop.attempt", "taskloop.merge.prepare"),
            ("taskloop.attempt_status", "taskloop.merge.status"),
            ("taskloop.attempt_status", "taskloop.merge.store"),
            ("taskloop.composition", "taskloop.merge.prepare"),
            ("taskloop.dash_task", "taskloop.merge.status"),
            ("taskloop.dash_task", "taskloop.merge.store"),
            ("taskloop.drain.composition", "taskloop.merge.store"),
            ("taskloop.hold_cause", "taskloop.merge.models"),
            ("taskloop.hold_facts", "taskloop.merge.models"),
            ("taskloop.hold_facts", "taskloop.merge.store"),
            ("taskloop.hold_status", "taskloop.merge.models"),
            ("taskloop.land", "taskloop.merge.models"),
            ("taskloop.land_conflict.abort", "taskloop.merge.models"),
            ("taskloop.land_conflict.abort_models", "taskloop.merge.models"),
            ("taskloop.land_conflict.cleanup", "taskloop.merge.models"),
            ("taskloop.land_conflict.cleanup_models", "taskloop.merge.models"),
            ("taskloop.land_conflict.composition", "taskloop.merge.models"),
            ("taskloop.land_conflict.composition", "taskloop.merge.store"),
            ("taskloop.land_conflict.execute", "taskloop.merge.models"),
            ("taskloop.land_conflict.execute", "taskloop.merge.resolve"),
            ("taskloop.land_conflict.execute", "taskloop.merge.start"),
            ("taskloop.land_conflict.execute", "taskloop.merge.store"),
            ("taskloop.land_conflict.handoff", "taskloop.merge.models"),
            ("taskloop.land_conflict.models", "taskloop.merge.models"),
            ("taskloop.land_conflict.preserve", "taskloop.merge.git"),
            ("taskloop.land_conflict.preserve", "taskloop.merge.models"),
            ("taskloop.land_conflict.release", "taskloop.merge.models"),
            ("taskloop.land_conflict.release_models", "taskloop.merge.models"),
            ("taskloop.slot_release", "taskloop.merge.store"),
        },
        "importlinter:contract:slice-taskloop.recovery": {
            ("taskloop.answer_repair", "taskloop.recovery.recover"),
            ("taskloop.attempt", "taskloop.recovery.execution_models"),
            ("taskloop.attempt_entry", "taskloop.recovery.continue_attempt"),
            ("taskloop.attempt_entry", "taskloop.recovery.entry"),
            ("taskloop.attempt_entry", "taskloop.recovery.models"),
            ("taskloop.attempt_loads", "taskloop.recovery.execution_models"),
            ("taskloop.attempt_loads", "taskloop.recovery.state_store"),
            ("taskloop.attempt_status", "taskloop.recovery.models"),
            ("taskloop.attempt_status", "taskloop.recovery.status"),
            ("taskloop.attempt_write_store", "taskloop.recovery.execution_models"),
            ("taskloop.attempt_write_store", "taskloop.recovery.models"),
            ("taskloop.attempt_write_store", "taskloop.recovery.state_store"),
            ("taskloop.cli_composition", "taskloop.recovery.status"),
            ("taskloop.composition", "taskloop.recovery.complete_attempt"),
            ("taskloop.composition", "taskloop.recovery.continue_attempt"),
            ("taskloop.composition", "taskloop.recovery.launch"),
            ("taskloop.composition", "taskloop.recovery.models"),
            ("taskloop.composition", "taskloop.recovery.native"),
            ("taskloop.composition", "taskloop.recovery.observe"),
            ("taskloop.composition", "taskloop.recovery.recover"),
            ("taskloop.composition", "taskloop.recovery.store"),
            ("taskloop.dash_duration", "taskloop.recovery.state_store"),
            ("taskloop.evidence_files", "taskloop.recovery.execution_models"),
            ("taskloop.evidence_files", "taskloop.recovery.models"),
            ("taskloop.launch", "taskloop.recovery.models"),
            ("taskloop.release_proof", "taskloop.recovery.models"),
            ("taskloop.session", "taskloop.recovery.execution_models"),
            ("taskloop.slot_release_store", "taskloop.recovery.models"),
            ("taskloop.slot_release_store", "taskloop.recovery.store"),
            ("taskloop.tracker_client", "taskloop.recovery.models"),
        },
        "importlinter:contract:slice-taskloop.shelf_digest": {
            ("taskloop.input_context", "taskloop.shelf_digest.artifact"),
            ("taskloop.input_context", "taskloop.shelf_digest.identities"),
            ("taskloop.input_context", "taskloop.shelf_digest.source"),
        },
        "importlinter:contract:sqlite-only-in-stores": {
            ("taskloop.admit", "sqlite3"),
            ("taskloop.admit_chain", "sqlite3"),
            ("taskloop.admit_store", "sqlite3"),
            ("taskloop.answer_repair_store", "sqlite3"),
            ("taskloop.attempt_entry", "sqlite3"),
            ("taskloop.attempt_loads", "sqlite3"),
            ("taskloop.attempt_reads", "sqlite3"),
            ("taskloop.attempt_store", "sqlite3"),
            ("taskloop.attempt_write_store", "sqlite3"),
            ("taskloop.check_admit", "sqlite3"),
            ("taskloop.check_admit_store", "sqlite3"),
            ("taskloop.check_entry", "sqlite3"),
            ("taskloop.check_release", "sqlite3"),
            ("taskloop.check_store", "sqlite3"),
            ("taskloop.cli_composition", "sqlite3"),
            ("taskloop.composition", "sqlite3"),
            ("taskloop.drain.composition", "sqlite3"),
            ("taskloop.drain.drain", "sqlite3"),
            ("taskloop.factory_store", "sqlite3"),
            ("taskloop.hold_store", "sqlite3"),
            ("taskloop.land", "sqlite3"),
            ("taskloop.land_conflict.reservation_store", "sqlite3"),
            ("taskloop.land_store", "sqlite3"),
            ("taskloop.launch", "sqlite3"),
            ("taskloop.operations", "sqlite3"),
            ("taskloop.publish", "sqlite3"),
            ("taskloop.publish_store", "sqlite3"),
            ("taskloop.recovery.state_store", "sqlite3"),
            ("taskloop.round", "sqlite3"),
            ("taskloop.setup_store", "sqlite3"),
            ("taskloop.slot_release", "sqlite3"),
            ("taskloop.slot_release_store", "sqlite3"),
            ("taskloop.slots_store", "sqlite3"),
            ("taskloop.task_content_store", "sqlite3"),
        },
    }
)


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
    keys = {"unmatched_ignore_alerting", "unmatched_ignore_imports_alerting"}
    assert not keys.intersection(config.defaults()), "Set unmatched-ignore handling explicitly per contract"
    for section in exception_lists(config):
        key = "unmatched_ignore_imports_alerting" if config[section]["type"] == "protected" else "unmatched_ignore_alerting"
        assert config[section].get(key) == "error", section


def test_exception_lists_do_not_grow(config: ConfigParser) -> None:
    assert_exception_ceiling(config, APPROVED_EXCEPTIONS)


def test_exception_lists_are_explicit_and_strict(config: ConfigParser) -> None:
    assert_strict_exceptions(config)


@pytest.mark.parametrize(
    "edge",
    [
        "taskloop.profile -> http.server",
        "taskloop.* -> http.server",
        "taskloop.dash_server -> http.*",
        "taskloop.dash_server -> http.**",
        "taskloop.dash_server http.server",
    ],
)
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
@pytest.mark.parametrize("contract", ["no-runtime-mechanisms", "slice-taskloop.agents", "sqlite-only-in-stores"])
def test_relaxed_or_implicit_unmatched_handling_fails(config: ConfigParser, alerting: str | None, contract: str) -> None:
    section = config[f"{PREFIX}{contract}"]
    key = "unmatched_ignore_imports_alerting" if section["type"] == "protected" else "unmatched_ignore_alerting"
    if alerting is None:
        del section[key]
    else:
        section[key] = alerting
    with pytest.raises(AssertionError):
        assert_strict_exceptions(config)


def test_inherited_unmatched_handling_fails(config: ConfigParser) -> None:
    config["DEFAULT"]["unmatched_ignore_alerting"] = "error"
    del config[f"{PREFIX}no-runtime-mechanisms"]["unmatched_ignore_alerting"]
    with pytest.raises(AssertionError, match="explicitly per contract"):
        assert_strict_exceptions(config)


@pytest.mark.parametrize("remove_contract", [False, True])
@pytest.mark.parametrize("contract", ["no-runtime-mechanisms", "slice-taskloop.agents", "sqlite-only-in-stores"])
def test_exception_and_ceiling_can_shrink_together(config: ConfigParser, remove_contract: bool, contract: str) -> None:
    section = f"{PREFIX}{contract}"
    approved = {name: edges.copy() for name, edges in APPROVED_EXCEPTIONS.items()}
    if remove_contract:
        del config[section]["ignore_imports"]
        del approved[section]
    else:
        approved[section].remove(sorted(approved[section])[0])
        config[section]["ignore_imports"] = "\n".join(f"{a} -> {b}" for a, b in sorted(approved[section]))
    with pytest.raises(AssertionError, match="Remove resolved exceptions"):
        assert_exception_ceiling(config, APPROVED_EXCEPTIONS)
    assert_exception_ceiling(config, approved)
    assert_strict_exceptions(config)

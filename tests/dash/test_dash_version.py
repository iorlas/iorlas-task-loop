"""The dashboard's code version changes with the contracts it imports, not only with its own package."""

from pathlib import Path

from taskloop_dash.cli import dash


def test_a_change_in_the_contracts_changes_the_version(tmp_path: Path) -> None:
    own, contracts = tmp_path / "dash", tmp_path / "contracts"
    own.mkdir()
    contracts.mkdir()
    (own / "a.py").write_text("x = 1")
    (contracts / "wire.py").write_text("V = 1")
    before = dash.code_version(own, contracts)
    assert dash.code_version(own, contracts) == before
    (contracts / "wire.py").write_text("V = 2")
    assert dash.code_version(own, contracts) != before


def test_the_default_version_covers_the_dash_and_the_contracts() -> None:
    assert dash.CONTRACTS.name == "tlkernel"
    assert dash.code_version() != dash.code_version(dash.PACKAGE)

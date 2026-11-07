"""ROOTLINT (tl-e5t0.30): the `nobody-imports-a-root` contract in .importlinter names its sources one by one, because import-linter cannot
say "everything but the roots" inside a package that holds both. So a new app package or a new `app/run` module that is in neither the
sources nor the forbidden roots would escape the rule unnoticed; this fails until it is classified: add it to the contract as a node
(source) or a root (forbidden), and the contract's own check then holds it."""
import configparser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src" / "taskloop" / "app"
CONTRACT = "importlinter:contract:nobody-imports-a-root"


def named(key: str) -> set[str]:
    cp = configparser.ConfigParser(interpolation=None, comment_prefixes=("#",), inline_comment_prefixes=None)
    cp.read(ROOT / ".importlinter", encoding="utf-8")
    return {line.strip() for line in cp[CONTRACT][key].splitlines() if line.strip()}


def test_every_app_package_and_run_module_is_a_node_or_a_root():
    known = named("source_modules") | named("forbidden_modules")
    found = {f"taskloop.app.{p.name}" for p in APP.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    found |= {f"taskloop.app.run.{p.stem}" for p in (APP / "run").glob("*.py") if p.stem != "__init__"}
    found |= {"tlwork.review", "tlwork.plan", "tlwork.look"}
    found -= {"taskloop.app.run"}
    missing = sorted(found - known)
    assert not missing, f"not classified in the {CONTRACT} contract (.importlinter): {missing}"


def exists(module: str) -> bool:
    base = (ROOT / "packages/work/src" if module.startswith("tlwork") else ROOT / "src") / Path(*module.split("."))
    return base.is_dir() or base.with_suffix(".py").exists()


def test_the_contract_names_no_module_that_is_gone():
    gone = [m for m in named("source_modules") | named("forbidden_modules") if m.startswith(("taskloop.app.", "tlwork")) and not exists(m)]
    assert not gone, f"the contract names modules that do not exist: {gone}"


def test_run_wiring_modules_are_composition_roots():
    roots = {"ask_flow", "bead_env", "closer_ports", "field_ports", "preflight", "reload_ports", "running", "shell"}
    modules = {f"taskloop.app.run.{name}" for name in roots}
    assert modules <= named("forbidden_modules")
    assert not modules & named("source_modules")

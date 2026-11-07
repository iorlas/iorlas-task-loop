"""Every rule has a reviewed selection policy; new rules default to always until classified."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dev"))
from rule_inputs import ALWAYS_RULES, RULES_BY_PATH, matches  # noqa: E402


def test_every_rule_is_classified_exactly_once():
    rules = {p.relative_to(ROOT).as_posix() for p in (ROOT / "tests/rules").rglob("test_*.py")}
    rules.add("tests/rules/gate_rules.py")
    assert not ALWAYS_RULES & RULES_BY_PATH.keys()
    assert ALWAYS_RULES | RULES_BY_PATH.keys() == rules


def test_every_input_pattern_matches_an_existing_file():
    files = [p.relative_to(ROOT).as_posix() for folder in ("src", "packages", "tests", "dev", "docs", "skills", "hooks")
             for p in (ROOT / folder).rglob("*") if p.is_file() and ".venv" not in p.parts and "__pycache__" not in p.parts]
    files += [p.name for p in ROOT.iterdir() if p.is_file()]
    for rule, globs in RULES_BY_PATH.items():
        for pattern in globs:
            assert any(matches(p, pattern) for p in files), (rule, pattern)


def test_globs_respect_components_and_recursive_directories():
    assert matches("static/index.html", "static/**/*.html")
    assert matches("static/js/nested/main.js", "static/**/*.js")
    assert not matches("static/js/nested/main.js", "static/*.js")
    assert not matches("other/index.html", "static/**/*.html")

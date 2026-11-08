"""Shared caps and counting semantics agree with Shelf's linting preset."""
import tomllib

from rules import gate_rules

SOURCE = '''"""Module documentation.
Still documentation.
"""

# Comment-only line.
@decorate
def outer():
    """Function documentation.
    Still documentation.
    """

    # Another comment-only line.
    text = """first

last"""
    def nested():
        return text
    return nested()

def outer():
    return 0
'''


def test_caps_match_shelf_preset():
    config = tomllib.loads((gate_rules.ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    caps = config["tool"]["shelf-size"]
    actual = (gate_rules.FILE_CAP, gate_rules.FUNC_CAP, gate_rules.TEST_FILE_CAP)
    assert actual == (
        caps["code-file"], caps["function"], caps["test-file"],
    )


def test_counting_matches_shelf(workdir):
    source = workdir / "sample.py"
    source.write_text(SOURCE, encoding="utf-8")
    # Verified offline with Shelf's tools/size_caps.py measure(SOURCE).
    assert gate_rules.measure(source) == (10, {"outer": 8, "outer.nested": 2})

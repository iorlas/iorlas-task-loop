"""Browser-free contracts for dashboard motion preferences in source and shipped CSS."""

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src/taskloop/dash/static"
REDUCED_MOTION = re.compile(
    r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{\s*([^{}]+)\{([^{}]+)\}\s*\}",
)


@pytest.mark.parametrize("name", ["dash.input.css", "dash.css"])
def test_reduced_motion_disables_effects_on_elements_and_pseudo_elements(name: str) -> None:
    css = (STATIC / name).read_text()
    rules = list(REDUCED_MOTION.finditer(css))
    assert len(rules) == 1, "Both source and shipped CSS must honor reduced motion"
    rule = rules[0]
    before = css[: rule.start()]
    assert before.count("{") == before.count("}"), "The override must be outside cascade layers"
    selectors = {selector.strip().replace("::", ":") for selector in rule[1].split(",")}
    assert selectors == {"*", ":before", ":after"}
    declarations = {re.sub(r"\s+", "", declaration) for declaration in rule[2].split(";") if declaration.strip()}
    assert declarations == {"animation:none!important", "transition:none!important"}, (
        "Disable effects with precedence over utilities, preserving final visibility and position"
    )


@pytest.mark.parametrize("name", ["dash.input.css", "dash.css"])
def test_ordinary_motion_remains_available_outside_the_preference(name: str) -> None:
    css = REDUCED_MOTION.sub("", (STATIC / name).read_text())
    for effect in ("flash", "pulse-dot", "line-in"):
        animation = re.search(rf"(?:@utility animate-|\.animate-){effect}\s*\{{\s*animation:\s*([^;}}]+)", css)
        assert animation is not None
        assert effect in animation[1].split()
    if name == "dash.css":
        assert re.search(r"\.animate-pulse\s*\{animation:var\(--animate-pulse\)", css)
        assert re.search(r"\.transition(?:-\w+)?\s*\{transition-property:", css)

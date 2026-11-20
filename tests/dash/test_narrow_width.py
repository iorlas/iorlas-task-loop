"""Stylesheet contracts for reflow; these do not replace browser layout checks."""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src/taskloop/dash/static"


def source(name: str) -> str:
    return (STATIC / name).read_text()


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text).replace('"', "")


def declarations(css: str, width: int, selector: str) -> dict[str, str]:
    """Read the layout rules, including the narrow media block when applicable."""
    layout = css[css.index("#board-canvas") : css.index("@media (prefers-reduced-motion")]
    media = re.search(r"@media\s*\(max-width:\s*([\d.]+)rem\)\s*\{", layout)
    assert media is not None
    active = layout[: media.start()]
    if width <= float(media[1]) * 16:
        active += layout[media.end() :].rstrip().removesuffix("}")
    result: dict[str, str] = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", active):
        if compact(selector) in compact(selectors).split(","):
            for pair in compact(body).split(";"):
                key, separator, value = pair.partition(":")
                if separator:
                    result[key] = value
    return result


class Panels(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nodes: dict[str, dict[str, str | None]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if identifier := attributes.get("id"):
            self.nodes[identifier] = attributes


@pytest.mark.parametrize("name", ["dash.input.css", "dash.css"])
@pytest.mark.parametrize("width", [320, 375, 1440])
def test_board_minimum_is_inside_the_scrolling_panel_in_both_layouts(name: str, width: int) -> None:
    panels = Panels()
    html = source("index.html")
    panels.feed(html)
    panel, canvas = panels.nodes["board"], panels.nodes["board-canvas"]
    assert panel["role"] == "tabpanel" and panel["aria-labelledby"] == "nav-board"
    assert {"min-w-0", "min-h-0", "overflow-auto", "flex-1"} <= set((panel["class"] or "").split())
    assert "min-width" not in str(panel.get("style", ""))
    assert re.search(r'id="board"[^>]*>\s*<div id="board-canvas"[^>]*></div>\s*</main>', html)
    assert "h-full" in (canvas["class"] or "")
    assert declarations(source(name), width, "#board-canvas")["min-width"] == "1100px"
    app = source("app.js")
    building = app.split("function buildBoard() {", 1)[1].split("\n}\n", 1)[0]
    assert 'const board = $("board-canvas")' in building
    assert 'lanes ? "5.5rem " : ""' in building
    assert 'overflow-y-auto", lanes' not in building
    for caller in ("setLanes", "resyncBoard"):
        body = app.split(f"function {caller}(", 1)[1].split("\n}\n", 1)[0]
        assert "buildBoard()" in body
    assert "setLanes(false)" in app.split("function start()", 1)[1]
    assert '$("board").hidden = name !== "board"' in app


@pytest.mark.parametrize("name", ["dash.input.css", "dash.css"])
@pytest.mark.parametrize("width", [320, 375, 1440])
def test_rails_fit_and_stack_at_narrow_width_but_keep_desktop_widths(name: str, width: int) -> None:
    css = source(name)
    narrow = width <= 768
    drawer_width = min(width, 64 * 16)
    for filename, hook, selector, units in (
        ("rail.js", "min-w-0 w-64 max-w-full", "#rail", 64),
        ("taskview.js", "task-properties min-w-0 w-60 max-w-full", ".task-properties", 60),
    ):
        assert hook in source(filename)
        rule = declarations(css, width, selector)
        if narrow:
            assert rule["width"] == rule["max-width"] == "100%"
            assert rule["border-inline"] == "0"
        assert (drawer_width if narrow else units * 4) <= drawer_width
    for selector in (".drawer-body", ".task-body"):
        rule = declarations(css, width, selector)
        assert rule.get("flex-direction", "row") == ("column" if narrow else "row")
    assert declarations(css, width, "#rail").get("max-height") == ("12rem" if narrow else None)
    for selector in (".drawer-body", ".task-body", ".attempt-pane", '#drawer [role="tabpanel"]'):
        assert declarations(css, width, selector).get("flex") == ("none" if narrow else None)
    assert declarations(css, width, "#drawer").get("overflow-y") == ("auto" if narrow else None)
    assert "drawer-body flex min-h-0 min-w-0 flex-1" in source("drawer.js")
    assert "task-body flex min-h-0 min-w-0 flex-1" in source("taskview.js")
    assert "w-[64rem] max-w-full" in source("index.html")


@pytest.mark.parametrize("name", ["dash.input.css", "dash.css"])
def test_controls_and_long_content_wrap_and_event_tracks_reflow(name: str) -> None:
    css = source(name)
    for width in (320, 375):
        for selector in (".shell-header", ".shell-controls"):
            assert declarations(css, width, selector)["flex-wrap"] == "wrap"
            child = declarations(css, width, f"{selector} > *")
            assert child["min-width"] == "0" and child["max-width"] == "100%"
        for selector in (".log-row > *", ".event-row > *"):
            assert declarations(css, width, selector)["overflow-wrap"] == "anywhere"
        assert declarations(css, width, "#drawer")["overflow-wrap"] == "anywhere"
        assert declarations(css, width, ".log-row")["grid-template-columns"] == "repeat(2,minmax(0,1fr))"
        assert declarations(css, width, ".log-row > :last-child")["white-space"] == "normal"
        assert declarations(css, width, ".event-row")["grid-template-columns"] == "3.25remminmax(0,1fr)"
        row = declarations(css, width, ".event-row > *")
        assert row.get("grid-area") == "auto/1/auto/-1" or (row.get("grid-row") == "auto" and row.get("grid-column") == "1/-1")
        assert declarations(css, width, ".event-row > .event-offset")["grid-column"] == "1"
        assert declarations(css, width, ".event-row > .event-kind")["grid-column"] == "2"
        assert declarations(css, width, ".event-row code")["white-space"] == "pre-wrap"
    for filename, hooks in (
        ("index.html", ("shell-header", "shell-controls")),
        ("logs.js", ("log-toolbar flex min-w-0 flex-wrap", "log-row grid")),
        ("lines.js", ("event-row grid", "event-pause", "event-offset", "event-kind")),
        ("accessibility.js", ("min-w-0 flex-wrap", "min-h-0 min-w-0 flex-1")),
    ):
        for hook in hooks:
            assert hook in source(filename)

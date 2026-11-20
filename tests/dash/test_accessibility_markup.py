"""Browser-free contracts for dashboard accessibility markup and event wiring."""

import ast
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src/taskloop/dash/static"


class Markup(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: dict[str, dict[str, str | None]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        identity = attributes.get("id")
        if identity:
            assert identity not in self.ids, identity
            self.ids[identity] = attributes


def source(name: str) -> str:
    return (STATIC / name).read_text()


def function(script: str, name: str) -> str:
    return script.split(f"function {name}(", 1)[1].split("\n}", 1)[0]


def test_screen_tabs_have_one_selection_and_reciprocal_panels() -> None:
    markup = Markup()
    markup.feed(source("index.html"))
    assert markup.ids["screens"]["role"] == "tablist"
    assert markup.ids["screens"]["aria-label"] == "Screens"
    assert markup.ids["layout"]["role"] == "group"
    for screen, selected in (("board", True), ("logs", False)):
        tab, panel = markup.ids[f"nav-{screen}"], markup.ids[screen]
        assert tab["role"] == "tab"
        assert tab["aria-selected"] == str(selected).lower()
        assert tab["tabindex"] == ("0" if selected else "-1")
        assert tab["aria-controls"] == screen
        assert panel["role"] == "tabpanel"
        assert panel["aria-labelledby"] == f"nav-{screen}"
        assert ("hidden" in panel) is not selected
    app = source("app.js")
    switching = function(app, "showScreen")
    for screen in ("board", "logs"):
        assert f'tabState($("nav-{screen}"), name === "{screen}")' in switching
        assert f'$("{screen}").hidden = name !== "{screen}"' in switching
    assert 'initTabList($("screens"))' in function(app, "start")


def test_reused_cards_have_names_and_share_pointer_and_keyboard_activation() -> None:
    app, accessibility = source("app.js"), source("accessibility.js")
    assert 'node.setAttribute("aria-label", `${t.id}: ${t.title}`)' in function(app, "fillCard")
    assert "activateCard(node, () => openDrawer(t.id))" in function(app, "newCard")
    assert "cards.set(t.id, newCard(t))" in function(app, "renderBoard")
    activation = function(accessibility, "activateCard")
    for contract in ('"role", "button"', "node.tabIndex = 0", '"click"', '"keydown"', '["Enter", " "]',
                     "event.preventDefault()", "!event.repeat", "nested(event.target)", "target.closest"):
        assert contract in activation
    assert activation.count("activate()") == 2


def test_closed_dialog_is_named_and_excluded_from_focus_until_reveal() -> None:
    markup = Markup()
    markup.feed(source("index.html"))
    dialog = markup.ids["drawer"]
    assert dialog["role"] == "dialog"
    assert dialog["aria-modal"] == "true"
    assert dialog["aria-label"]
    assert dialog["aria-hidden"] == "true"
    assert dialog["tabindex"] == "-1"
    assert "inert" in dialog
    drawer, accessibility = source("drawer.js"), source("accessibility.js")
    opening = function(drawer, "openDrawer")
    assert 'setAttribute("aria-label"' in opening
    assert opening.index("reveal()") < opening.index("await source.detail(id)")
    assert 'openDialog($("drawer"))' in function(drawer, "reveal")
    opening = function(accessibility, "openDialog")
    for contract in ("invoker = document.activeElement", "node.inert = true", "drawer.inert = false",
                     'setAttribute("aria-hidden", "false")', "drawer.focus()"):
        assert contract in opening


def test_dialog_dismissal_bounds_focus_and_returns_to_invoker_or_screen() -> None:
    drawer, accessibility = source("drawer.js"), source("accessibility.js")
    assert 'initDialog($("drawer"), closeDrawer)' in function(drawer, "initDrawer")
    assert '$("backdrop").addEventListener("click", closeDrawer)' in function(drawer, "initDrawer")
    assert "closeButton(closeDrawer)" in function(drawer, "head")
    assert "closeButton(closeDrawer)" in function(drawer, "showError")
    assert 'closeDialog($("drawer"))' in function(drawer, "closeDrawer")
    trapping = function(accessibility, "initDialog")
    for contract in ('event.key === "Escape"', "close()", 'event.key !== "Tab"', "event.shiftKey",
                     "nodes.length - 1", "index === 0", "event.preventDefault()", ".focus()"):
        assert contract in trapping
    closing = function(accessibility, "closeDialog")
    for contract in ("drawer.inert = true", 'setAttribute("aria-hidden", "true")', "node.inert = inert",
                     "invoker?.isConnected && available(invoker)", 'getElementById("nav-board")', ")?.focus()"):
        assert contract in closing


def test_redraws_preserve_focus_and_keep_stale_reply_guards() -> None:
    drawer, accessibility = source("drawer.js"), source("accessibility.js")
    assert 'preserveDialogFocus($("drawer"), renderContent)' in function(drawer, "render")
    assert "preserveDialogFocus" in function(drawer, "showError")
    preservation = function(accessibility, "preserveDialogFocus")
    for contract in ("drawer.contains(active)", "focusKey(active)", "update()", "!drawer.inert",
                     'getAttribute("aria-hidden") === "false"', "focusKey(node) === key", "replacement ?? drawer",
                     "preventScroll: true"):
        assert contract in preservation
    assert "node.id ||" in accessibility
    assert "open !== mine" in function(drawer, "openDrawer")
    assert "open === mine" in function(drawer, "loadTracker")
    assert "open === mine" in function(drawer, "bodyTab")
    assert "open === mine && mine.delivery === own" in function(drawer, "loadDelivery")
    assert "open !== mine" in function(drawer, "onTaskMoved")


def test_dynamic_tabs_cover_tracker_empty_and_result_only_views() -> None:
    drawer, accessibility = source("drawer.js"), source("accessibility.js")
    rendering = function(drawer, "renderContent")
    assert 'tabBar("drawer-view", "Task views"' in rendering
    assert 'tabPanel(taskView(open.tracker,' in rendering
    assert '"Not started: no attempt yet."), "drawer-view", view)' in rendering
    assert 'tabPanel(body, "drawer-view", view)' in rendering
    pane = function(drawer, "pane")
    assert 'if (a.step === COMMIT.id) wrap.append(content);\n  else {' in pane
    assert 'tabBar("attempt-body", "Attempt output"' in pane
    assert 'tabPanel(content, "attempt-body", tab)' in pane
    bar, panel = function(accessibility, "tabBar"), function(accessibility, "tabPanel")
    assert '"role", "tab"' in bar
    assert '"aria-controls", `${group}-panel-${id}`' in bar
    assert "tabState(button, on)" in bar
    assert "panel.hidden = true" in bar  # inactive tabs still control existing panels
    assert '"role", "tabpanel"' in panel
    assert '"aria-labelledby", `${group}-tab-${selected}`' in panel
    assert "if (node.id)" in panel and "wrap.append(node)" in panel  # retain the live Lines pane's IDs
    for key in ("ArrowLeft", "ArrowRight", "Home", "End"):
        assert f'"{key}"' in function(accessibility, "initTabList")
    assert "tabs[next].click()" in function(accessibility, "initTabList")
    assert 'button.setAttribute("aria-selected", String(selected))' in function(accessibility, "tabState")
    assert "button.tabIndex = selected ? 0 : -1" in function(accessibility, "tabState")


def test_shared_accessibility_module_is_served_and_imported_by_both_consumers() -> None:
    module = ast.parse((ROOT / "src/taskloop/dash_server.py").read_text())
    pages = next(ast.literal_eval(node.value) for node in module.body
                 if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "PAGES"
                                                        for target in node.targets))
    assert pages["accessibility.js"] == "accessibility.js"
    for consumer in ("app.js", "drawer.js"):
        assert 'from "./accessibility.js"' in source(consumer)


def test_rail_indicators_include_visible_state_and_verdict_words() -> None:
    rail = source("rail.js")
    row = function(rail, "row")
    assert "dot(st.dot)" in row
    assert 'btn.append(el("span", `block text-[11px] ${st.text}`, st.label))' in row
    assert "commitButton(factoryCommit, selected, select, a)" in row
    factory_commit = function(rail, "commitButton")
    assert '`${v.mark} ${v.label}`' in factory_commit
    assert "truncate" not in factory_commit and "sr-only" not in factory_commit
    history = function(rail, "summary")
    assert "verdict(factoryCommit)" in history and "STATE[a.state].label" in history
    assert "${lastStatus.mark} ${lastStatus.label}" in history
    assert '"; Factory commit pending"' in history


def test_all_event_kind_glyphs_have_visible_words_after_insert_or_replace() -> None:
    script = source("lines.js")
    row = function(script, "line")
    assert '`${KIND[e.type]} ${WORD[e.type]}`' in row
    assert "row.append(at, kind, content, right)" in row
    assert "sr-only" not in row
    assert "list.append(line(e, a," in function(script, "lines")
    update = function(script, "show")
    assert "const row = line(e, attempt, attempt.feed[index - 1], true, activate)" in update
    assert "old.replaceWith(row)" in update and "list.append(row)" in update


def test_existing_board_badges_quiet_age_and_check_indicators_keep_visible_words() -> None:
    app, ui = source("app.js"), source("ui.js")
    heading = function(app, "buildBoard")
    assert "col.emoji" in heading and "col.label" in heading
    card = function(app, "fillCard")
    assert '"↩ Restarted at plan" : "↻ Repeat"' in card
    assert 't.status === "abandoned" ? "Abandoned" : "Queued"' in card
    assert 'ask ? "Needs you" : `Factory problem: ${say(cause)}`' in function(ui, "holdCallout")
    quiet = function(ui, "tickQuiet")
    assert 'dot(level === "long" ? "bg-rose-500" : "bg-amber-500")' in quiet
    assert "Last activity ${fmtDur(s * 1000)} ago" in quiet
    assert "node.append(text)" in function(ui, "tag")
    assert "tag(st.label, { dotCls: st.dot, cls: st.text })" in function(source("event-detail.js"), "attemptPanel")
    assert "c.passed ? STATE.succeeded.label : STATE.failed.label" in function(source("result.js"), "check")
    assert "e.passed ? STATE.succeeded.label : STATE.failed.label" in function(source("lines.js"), "checkLine")

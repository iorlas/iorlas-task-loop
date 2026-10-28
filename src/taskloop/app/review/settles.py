"""Settles: what the engine proves itself before the verifier is asked (tl-bxk.10.9, .10.19, .10.25). An item that names a tool the repo
does not use is no check here; one that names a gate or stage check the engine runs is settled by that check; one that only doubts
whether the engine ran a check is settled by the engine's own results; one that names a linter the repo has is run here."""
from typing import Any, Final

from taskloop.adapters.gitenv import run_git
from taskloop.contracts.argv import argv_of
from taskloop.domain.plan.matchers import without_runner
from taskloop.domain.review.matchers import KNOWN_TOOLS, GateProof, Tools, word_in

Item = dict[str, Any]
LINT_DEFAULT: Final = {"ruff": "ruff check .", "flake8": "flake8", "shellcheck": None}


class Settles:
    def __init__(self, host: Any) -> None:
        self.e = host

    # -- tools the repo does not use
    def unused_tool(self, what: str) -> str:
        """The evidence that every tool an item names is one the repo does not use: nothing in the tracked tree mentions it (`git grep
        -w -I`, dot directories, CI, toolchain and agent files included), nor the engine's gate and checks, and it is not on PATH; ""
        when it names none or the repo uses one."""
        tools = Tools.named(what)
        if not tools:
            return ""
        engine_text = " ".join([self.e.cfg.gate_text] + [str(c) for c in self.e.cfg.checks])
        said = []
        for t in tools:
            r = run_git(self.e.wt, "grep", "-w", "-I", "-l", "-F", t, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode not in (0, 1):  # no git tree to read: no evidence, the item stays
                return ""
            if r.stdout.strip() or word_in(t, engine_text) or self.e.on_path(t):
                return ""
            said.append(f"git grep -w -I {t}: no match in the tracked tree nor the engine's gate and checks; which {t}: not found")
        return "not a check here: the repo does not use it ({})".format("; ".join(said))

    def lint_command(self, what: str) -> str:
        """The command the engine runs for an item naming a linter this repo uses: the backticked command if it is plain words (no shell
        syntax), else the linter's default; "" when it names none, or the repo does not use it."""
        for tool in Tools.named(what):
            if tool not in KNOWN_TOOLS or self.unused_tool(f"`{tool}`"):
                continue
            plain = Tools.plain_command(what, tool)
            if plain or LINT_DEFAULT.get(tool):
                return plain or LINT_DEFAULT[tool] or ""
        return ""

    # -- the checks the engine runs
    def gate_names(self) -> list[str]:
        """Names a verify item can use for a check the engine runs by itself (the gate, a configured check, a plan stage check or case):
        its id, its command, and the command without its runner (`just unity-tests` -> unity-tests)."""
        e = self.e
        stages = (e.plan_data or {}).get("stages") or []
        cmds = [e.cfg.gate_text] + [c.cmd for c in e.cfg.checks] + [c for st in stages for c in st["checks"]] + e.case_checks()
        names = [c.id for c in e.cfg.checks]
        for cmd in cmds:
            c = " ".join(cmd.split())
            rest = without_runner(c)
            names += [c] + ([rest] if rest != c and ("-" in rest or "_" in rest) else [])
        return [n.lower() for n in dict.fromkeys(names) if len(n) >= 4]

    def log_path_of(self, c: Any, full: bool = True) -> str:
        """The saved log of a check: absolute in the trace; in a prompt relative to the engine's run folder, since a path into it is a file
        no step can read (the brief is inline, never a path outside the worktree)."""
        return str(self.e.run_dir / c.log if full else c.log) if c.log else "none (cached: same tree and base, earlier result)"

    def checks_now(self) -> tuple[list[Any], bool]:
        """(the engine's last check results, whether they ran on the tree as it is now). After a resume the saved engine-checks.json
        stands in for the brief; its tree is unknown, so it settles nothing."""
        run = self.e.last_run
        if run is None:
            saved = self.e.stores.check_run(self.e.run_dir.name, None).read()
            return (saved.results if saved else []), False
        return run.results, bool(run.tree) and run.tree == self.e.tree_hash()

    def evidence_text(self, checks: list[Any] | None = None, current: bool | None = None) -> str:
        """The engine's check results as brief text: per check id, group, command, status, exit code, duration, log path; said plainly to
        be the engine's evidence the reader may cite. '' when none ran."""
        if checks is None:
            checks, current = self.checks_now()
        if not checks:
            return ""
        out = [self.row(c) for c in checks[:30]]
        if len(checks) > 30:
            out.append(f"- ({len(checks) - 30} more checks not listed)")
        return ("The engine's own check results for {} (the engine's evidence, run by the engine itself: you may cite them as "
                "proof; a log path is relative to the engine's run folder, which you cannot open. A check skipped for "
                "'no change under ...' matched no changed path: it is proven by design that the check does not apply, so an item "
                "whose only doubt is such a skipped check, or a check listed here as pass, is settled; cite this list):\n{}\n".format(
                    "the tree as it is now" if current else "an earlier tree (files changed since: weigh them accordingly)",
                    "\n".join(out)))

    def row(self, c: Any) -> str:
        if c.status == "skipped" or c.exit is None:
            what = "skipped (%s)" % (c.why or "no reason given")
        else:
            what = "{}, exit {}, {:g} s, log {}".format("pass" if c.exit == 0 else "fail", c.exit, c.secs, self.log_path_of(c, False))
        cmd = "" if c.cmd == c.id else f"; command `{c.cmd[:300]}`"
        last = " ".join(" ".join(c.tail.strip().splitlines()[-2:]).split())  # the log is no file the verifier can open
        row = (f"- `{c.id[:100]}` [{c.group}] {what}{cmd}")[:300]
        room = 300 - len(row) - len("; last output: ")
        if last and c.exit == 0 and room >= 20:  # what a pass printed last, within the 300-character row
            row += "; last output: " + last[-min(160, room):]
        return row

    def work_summary(self) -> str:
        """The task's changed files with their line counts, untracked files included."""
        tree = self.e.tree_hash()
        return (self.e.git("diff", "--stat", self.e.base_sha(), tree) if tree else "") or "(no files changed)"

    # -- settling
    def settle(self, gaps: list[Item]) -> tuple[list[Item], list[Item]]:
        """(items still to verify, items the engine found wrong). An item whose proof is the gate or a stage check (matched by check id
        or command name) is settled as 'the gate runs it at land': the read-only verifier cannot run it. An item naming a linter the
        repo has is run here; its exit code settles it, a red one goes to a fix round."""
        names = self.gate_names()
        left: list[Item] = []
        failed: list[Item] = []
        results, current = self.checks_now()
        for u in gaps:
            if self.by_name(u, names, results) or self.by_results(u, results, current):
                continue
            cmd = self.lint_command(u["what"])
            bad = self.run_lint(u, cmd) if cmd else None
            if bad is None:
                left.append(u)
            elif bad:
                failed.append(bad)
        return left, failed

    def settled(self, u: Item, evidence: str, why: str, verdict: str = "settled") -> None:
        self.e.verified.append({"what": u["what"], "kind": u["kind"], "verdict": verdict, "why": why, "evidence": evidence})

    def by_name(self, u: Item, names: list[str], results: list[Any]) -> bool:
        what = " ".join(u["what"].split()).lower()
        if not GateProof.says_it_passes(what):
            return False
        hit = GateProof.first_named(what, names)
        if not hit or any(c.status == "failed" and hit in (c.id.lower(), " ".join(c.cmd.split()).lower()) for c in results):
            return False  # the engine saw it red: nothing is proven
        self.settled(u, f"`{hit}` is a gate or stage check: the engine runs it, the gate at land (a red one goes to a fix round)",
                     "the gate runs it at land")
        return True

    def by_results(self, u: Item, results: list[Any], current: bool) -> bool:
        if self.e.judge.is_look(u):
            return False
        proof = self.proof(u["what"], results, current)
        if proof:
            self.settled(u, proof, "the engine's own check results settle it")
        return bool(proof)

    def run_lint(self, u: Item, cmd: str) -> Item | None:
        """None: the tool cannot start here (the verifier and the owner still judge it); {} settled; else the wrong item."""
        rc, tail = self.e.sh(argv_of(cmd), timeout=600)
        if rc in (126, 127):
            return None
        out = f"ran `{cmd}`: exit {rc}" + ((" " + tail[-300:]) if rc else "")
        self.settled(u, out, out, "settled" if rc == 0 else "wrong")
        return dict(u, why=out) if rc else {}

    def proof(self, what: str, results: list[Any], current: bool) -> str:
        """The evidence text when the item names only known check ids, each green or skipped by its path trigger, on the current known
        tree, and doubts nothing but whether the engine ran or passed them; else ''."""
        what = " ".join(what.split()).lower()
        if not current or not results or not GateProof.only_doubts_the_run(what):
            return ""
        ids = {c.id.lower(): c for c in results}
        hits = [c for i, c in ids.items() if len(i) >= 4 and word_in(i, what)]
        if not hits or any(n not in ids for n in GateProof.check_names(what)) or Tools.named(what):
            return ""
        parts = []
        for c in hits:
            idn = c.id[:80]
            if c.status == "passed" and c.exit == 0:
                parts.append(f"`{idn}` [{c.group}] passed: exit 0, {c.secs:g} s, log {self.log_path_of(c)}")
            elif c.status == "skipped" and c.why.startswith("no change under"):
                parts.append(f"`{idn}` [{c.group}] skipped: {c.why}, so the check does not apply to this change")
            else:
                return ""
        return "the engine's own check results for this tree: " + "; ".join(parts)

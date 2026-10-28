"""Worker transcripts as timeline events: one reader per harness (Claude, Codex job log, Codex rollout, OpenCode, the engine's own
log). Every reader returns [{t, kind user|msg|cmd|note|node|session|warn, text, ...}]. No regex: the text is split with str methods."""

import json
from typing import Any

from taskloop.contracts import log as rec
from taskloop_dash import jsonl
from taskloop_dash.env import Env
from taskloop_dash.readers.opencode import OpenCode, session_id
from taskloop_dash.tails import parse_ts

Event = dict[str, Any]
SHELLS = ("zsh", "bash", "sh")


def _tool_text(inp: dict[str, Any], path_key: str) -> str:
    text = inp.get("command") or inp.get("description") or inp.get(path_key) or inp.get("pattern") or inp.get("query") \
        or inp.get("prompt") or inp.get("url") or ""
    return str(text).strip()[:600]


def _js_string(src: str, at: int) -> tuple[str, int] | None:
    """The double-quoted literal that starts at src[at], decoded, and the index after it; None when src[at] opens none."""
    if at >= len(src) or src[at] != '"':
        return None
    i = at + 1
    while i < len(src):
        if src[i] == "\\":
            i += 2
            continue
        if src[i] == '"':
            raw = src[at : i + 1]
            try:
                return json.loads(raw), i + 1
            except ValueError:
                return raw[1:-1], i + 1
        i += 1
    return None


def exec_cmds(src: object) -> list[str]:
    """The shell commands in a Codex `exec` tool call, whose input is code: text(await tools.exec_command({cmd:"..."}))."""
    if not isinstance(src, str) or "exec_command(" not in src:
        return []
    out: list[str] = []
    pos = 0
    while (hit := src.find("exec_command(", pos)) >= 0:
        pos = hit + len("exec_command(")
        i = pos
        for want in ("{", None, "cmd", None, ":", None):  # {  "cmd" :  ; the quotes around cmd are optional, spaces anywhere
            if want is None:
                while i < len(src) and src[i].isspace():
                    i += 1
            elif want == "cmd":
                i += 1 if src[i : i + 1] == '"' else 0
                if src[i : i + 3] != "cmd":
                    i = -1
                    break
                i += 3
                i += 1 if src[i : i + 1] == '"' else 0
            elif src[i : i + 1] == want:
                i += 1
            else:
                i = -1
                break
        got = _js_string(src, i) if i >= 0 else None
        if got:
            out.append(got[0])
    return out


def _strip_exit(s: str) -> str:
    """'ls (exit 1)' -> 'ls'."""
    s = s.rstrip()
    start = s.rfind("(exit ")
    if start >= 0 and s.endswith(")"):
        code = s[start + 6 : -1]
        if code.lstrip("-").isdigit():
            return s[:start].rstrip()
    return s


def _unshell(s: str) -> str:
    """'bash -lc ls' -> 'ls' (once): the shell a Codex command is wrapped in."""
    for prefix in ("/bin/", ""):
        for sh in SHELLS:
            for flag in ("-lc ", "-c "):
                lead = "%s%s %s" % (prefix, sh, flag)
                if s.startswith(lead):
                    return s[len(lead) :]
    return s


def clean_cmd(s: str) -> str:
    s = _unshell(_strip_exit(s)).strip()
    if len(s) > 1 and s[0] in "'\"" and s[-1] == s[0]:
        s = s[1:-1]
    return s


def _leading_int(text: str) -> int | None:
    k = 1 if text[:1] == "-" else 0
    end = k
    while end < len(text) and "0" <= text[end] <= "9":
        end += 1
    return int(text[:end]) if end > k else None


def exit_code(output: str) -> int | None:
    """The number after 'Exit code' / 'exit code' (a colon optional, one space) in a tool output."""
    for marker in ("Exit code", "exit code"):
        at = output.find(marker)
        while at >= 0:
            rest = output[at + len(marker) :].removeprefix(":")
            got = _leading_int(rest[1:]) if rest.startswith(" ") else None
            if got is not None:
                return got
            at = output.find(marker, at + 1)
    return None


def _drop_session_ids(body: str) -> str:
    """Remove ' (a1b2c3d4-...)' and an optional following '.' (a session id the Codex plugin appends)."""
    out, i = "", 0
    while i < len(body):
        j = body.find("(", i)
        if j < 0:
            break
        k = body.find(")", j)
        inner = body[j + 1 : k] if k > 0 else ""
        if k > 0 and len(inner) >= 20 and all(c in "0123456789abcdef-" for c in inner):
            out += body[i:j].rstrip()
            i = k + 1 + (1 if body[k + 1 : k + 2] == "." else 0)
        else:
            out += body[i : j + 1]
            i = j + 1
    return out + body[i:]


class Events:
    def __init__(self, env: Env, opencode: OpenCode) -> None:
        self.env, self.opencode = env, opencode

    def claude(self, path: str, t0: float | None = None, t1: float | None = None) -> list[Event]:
        """Claude transcript (session, subagent, or claude -p stream) -> timeline events."""
        out: list[Event] = []
        pending: dict[Any, Event] = {}
        for ln in self.env.tails.window_lines(path, t0, t1):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if not isinstance(d, dict) or d.get("type") not in ("assistant", "user"):
                continue
            t = parse_ts(d.get("timestamp"))
            if t0 and t and t < t0 - 1:
                continue
            if t1 and t and t > t1 + 1:
                break
            content = (d.get("message") or {}).get("content")
            if isinstance(content, str):
                if d["type"] == "user" and content.strip() and not d.get("isMeta"):
                    out.append({"t": t, "kind": "user", "text": content.strip()[:4000]})
            elif isinstance(content, list):
                for x in content:
                    if isinstance(x, dict):
                        self._claude_part(d, x, t, out, pending)
        return out

    @staticmethod
    def _claude_part(d: Event, x: Event, t: float | None, out: list[Event], pending: dict[Any, Event]) -> None:
        k = x.get("type")
        if k == "tool_use":
            e = {"t": t, "kind": "cmd", "tool": x.get("name", ""), "text": _tool_text(x.get("input") or {}, "file_path"), "state": "run"}
            pending[x.get("id")] = e
            out.append(e)
        elif k == "tool_result":
            e = pending.pop(x.get("tool_use_id"), None)
            if e:
                e["state"] = "fail" if x.get("is_error") else "ok"
                e["dur"] = (t - e["t"]) if t and e["t"] else None
                c = x.get("content")
                if isinstance(c, list):
                    c = " ".join(y.get("text", "") for y in c if isinstance(y, dict))
                e["detail"] = str(c)[:3000]
        elif k == "text" and x.get("text", "").strip():
            if d["type"] == "assistant":
                out.append({"t": t, "kind": "msg", "text": x["text"].strip()[:6000]})
            elif not d.get("isMeta") and not x["text"].startswith("<"):
                out.append({"t": t, "kind": "user", "text": x["text"].strip()[:4000]})

    def opencode_events(self, sid: str, t0: float | None = None, t1: float | None = None) -> list[Event]:
        """An OpenCode session (xai lane: `ses_...`, read from its SQLite DB) -> timeline events. [] for a missing DB or an
        unknown id; `sid` may carry the `opencode:` prefix."""
        sid = session_id(sid)
        if not sid:
            return []
        out: list[Event] = []
        lo = int((t0 - 1) * 1000) if t0 else 0  # OpenCode stores ms
        hi = int((t1 + 1) * 1000) if t1 else 1 << 62
        rows = self.opencode.rows(  # the newest 5000 parts of the window: a long session shows its end, a poll reads no more
            "SELECT p.time_created, m.data, p.data FROM part p JOIN message m ON m.id = p.message_id WHERE p.session_id = ? "
            "AND p.time_created BETWEEN ? AND ? ORDER BY p.time_created DESC, p.id DESC LIMIT 5000", (sid, lo, hi))
        for created, mdata, pdata in reversed(rows):
            try:
                t = created / 1000.0
                role = json.loads(mdata).get("role")
                d = json.loads(pdata)
            except (ValueError, TypeError, AttributeError):
                continue
            if not isinstance(d, dict) or (t0 and t < t0 - 1):
                continue
            if t1 and t > t1 + 1:
                break
            e = self._opencode_part(d, t, role)
            if e:
                out.append(e)
        return out

    @staticmethod
    def _opencode_part(d: Event, t: float, role: object) -> Event | None:
        typ = d.get("type")
        if typ == "text" and str(d.get("text") or "").strip() and not d.get("synthetic"):
            return {"t": t, "kind": "msg" if role == "assistant" else "user", "text": d["text"].strip()[: 6000 if role == "assistant" else 4000]}
        if typ != "tool":
            return None
        st = d.get("state") if isinstance(d.get("state"), dict) else {}
        inp = st.get("input") if isinstance(st.get("input"), dict) else {}
        e: Event = {"t": t, "kind": "cmd", "tool": d.get("tool", ""), "text": _tool_text(inp, "filePath"), "state": "run"}
        if st.get("status") in ("completed", "error"):
            e["state"] = "ok" if st["status"] == "completed" else "fail"
            tm = st.get("time") if isinstance(st.get("time"), dict) else {}
            if isinstance(tm.get("start"), (int, float)) and isinstance(tm.get("end"), (int, float)):
                e["dur"] = (tm["end"] - tm["start"]) / 1000.0
            e["detail"] = str(st.get("output") or st.get("error") or "")[:3000]
        return e

    def codex_log(self, path: str, t0: float | None = None, t1: float | None = None) -> list[Event]:
        """The codex plugin's job log -> timeline events."""
        out: list[Event] = []
        open_cmd: Event | None = None
        for ln in self.env.tails.tail_lines(path):
            end = ln.find("]") if ln.startswith("[") else -1
            if end < 2 or ln[end + 1 : end + 2] != " ":
                if out and out[-1]["kind"] == "msg":
                    out[-1]["text"] = (out[-1]["text"] + "\n" + ln)[:6000]
                continue
            t, body = parse_ts(ln[1:end]), ln[end + 2 :]
            if body.startswith("Running command: "):
                open_cmd = {"t": t, "kind": "cmd", "tool": "shell", "text": clean_cmd(body[17:]), "state": "run"}
                out.append(open_cmd)
            elif body.startswith(("Command completed: ", "Command failed: ")):
                ok = body.startswith("Command completed")
                target: Event | None = open_cmd if open_cmd and open_cmd.get("state") == "run" else None
                if target is None:
                    target = {"t": t, "kind": "cmd", "tool": "shell", "text": clean_cmd(body.split(": ", 1)[1])}
                    out.append(target)
                target.update(state="ok" if ok else "fail", dur=(t - target["t"]) if t and target.get("t") else None)
                open_cmd = None
            elif body.startswith(("Assistant message captured: ", "Assistant message: ")):
                text = body.split(": ", 1)[1]
                if not (out and out[-1]["kind"] == "msg" and out[-1]["text"][:40] == text[:40]):
                    out.append({"t": t, "kind": "msg", "text": text})
            elif body.strip() and body.strip() not in ("Assistant message", "Assistant message captured"):
                out.append({"t": t, "kind": "note", "text": _drop_session_ids(body)})
        return out

    def rollout(self, path: str, t0: float | None = None, t1: float | None = None) -> list[Event]:
        """A Codex rollout file (codex exec / app-server) -> timeline events."""
        out: list[Event] = []
        pending: dict[Any, Event] = {}
        for ln in self.env.tails.window_lines(path, t0, t1):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            t = parse_ts(d.get("timestamp"))
            if t0 and t and t < t0:
                continue
            if t1 and t and t > t1:
                break
            p = d.get("payload") or {}
            typ = p.get("type")
            if d.get("type") == "response_item":
                self._rollout_item(p, typ, t, out, pending)
            elif d.get("type") == "event_msg" and typ == "user_message":
                out.append({"t": t, "kind": "user", "text": str(p.get("message", ""))[:4000]})
        return out

    @staticmethod
    def _rollout_item(p: Event, typ: object, t: float | None, out: list[Event], pending: dict[Any, Event]) -> None:
        if typ == "message" and p.get("role") == "assistant":
            text = " ".join(c.get("text", "") for c in p.get("content", []) if isinstance(c, dict)).strip()
            if text:
                out.append({"t": t, "kind": "msg", "text": text[:6000]})
        elif typ in ("function_call", "custom_tool_call", "local_shell_call"):
            args = p.get("arguments") or p.get("input") or ""
            cmds = exec_cmds(args)
            try:
                j = json.loads(args) if isinstance(args, str) else args
                cmd = j.get("cmd") or j.get("command") or args
                if isinstance(cmd, list):
                    cmd = " ".join(cmd)
            except (ValueError, AttributeError):
                cmd = args
            if cmds:
                cmd = "\n".join(cmds)
            e = {"t": t, "kind": "cmd", "tool": p.get("name", "shell"), "text": clean_cmd(str(cmd))[:600], "state": "run"}
            pending[p.get("call_id")] = e
            out.append(e)
        elif typ in ("function_call_output", "custom_tool_call_output"):
            e = pending.pop(p.get("call_id"), None)
            if e:
                o = str(p.get("output", ""))
                code = exit_code(o)
                e["state"] = "fail" if code not in (None, 0) else "ok"
                e["dur"] = (t - e["t"]) if t and e["t"] else None
                e["detail"] = o[:3000]

    def engine(self, path: str, t0: float | None = None, t1: float | None = None) -> list[Event]:
        """The engine's own log: one line per node, decision, command."""
        out: list[Event] = []
        for r in (jsonl.parse(ln) for ln in self.env.tails.tail_lines(path)):
            if isinstance(r, rec.CmdStart):
                out.append({"t": r.t, "kind": "cmd", "text": r.text, "tool": "sh", "state": "ok"})
            elif isinstance(r, rec.CmdEnd) and out and out[-1]["kind"] == "cmd":
                out[-1]["state"] = "ok" if r.exit == 0 else "fail"
                out[-1]["detail"] = "exit %d%s" % (r.exit, (": " + r.out) if r.out else "")
            elif isinstance(r, (rec.Note, rec.Warn)):
                out.append({"t": r.t, "kind": r.KIND, "text": r.text})
            elif isinstance(r, rec.StepStart):
                out.append({"t": r.t, "kind": "node", "text": r.text})
            elif isinstance(r, rec.CallEnd):
                out.append({"t": r.t, "kind": "session", "text": "%s %s  ($%.2f, %ss)" % (r.family or "?", r.ref or "(no session)", r.cost, r.secs)})
        return out

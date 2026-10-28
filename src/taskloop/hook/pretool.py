"""The PreToolUse hook. Imports nothing but the rules: it runs before every tool call and must finish in well under a second."""
import json

from taskloop.hook.rules import deny_reason


def main(stdin_text: str) -> str:
    """The hook's stdout: a deny decision with its reason, or nothing. Input it cannot read is allowed through."""
    try:
        data = json.loads(stdin_text or "{}")
        args = data.get("tool_input")
        why = deny_reason(str(data.get("tool_name") or ""), args if isinstance(args, dict) else {})
    except (ValueError, AttributeError):
        return ""
    if not why:
        return ""
    decision = {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": why}
    return json.dumps({"hookSpecificOutput": decision})

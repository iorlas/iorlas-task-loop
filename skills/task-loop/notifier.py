"""The owner's push (tl-bxk.12.2): one channel for an ask and for the morning digest.

~/.config/task-loop/notify holds ONE of:
  - a shell command (ntfy, Pushover, a Telegram bot...): it gets TL_ASK_KIND (decision, verify, ..., or `digest`),
    TL_ASK_BEAD, TL_ASK_ID, TL_ASK_TEXT (one line, at most 500 characters) and TL_DIGEST_TEXT (the whole digest);
  - the word `desktop`: a notification on this machine (macOS osascript, Linux notify-send); no account, no credentials;
  - nothing, or `off`: no push.
Which service is the owner's choice: nothing here invents a credential or an endpoint. `tl notify test` sends one.
"""

import os
import shutil
import subprocess
import sys

import tl


def channel():
    """('command', text) | ('desktop', '') | ('off', '')"""
    try:
        text = (tl.config_dir() / "notify").read_text(encoding="utf-8").strip()
    except OSError:
        return "off", ""
    if text.lower() == "desktop":
        return "desktop", ""
    if not text or text.lower() == "off":
        return "off", ""
    return "command", text


def desktop(title, text):
    """True when a desktop notification was started; False when this machine has no way to show one."""
    text = " ".join((text or "").split())[:240]
    if sys.platform == "darwin" and shutil.which("osascript"):
        cmd = ["osascript", "-e", "on run argv", "-e", "display notification (item 1 of argv) with title (item 2 of argv)",
               "-e", "end run", text, title]
    elif shutil.which("notify-send"):
        cmd = ["notify-send", title, text]
    else:
        return False
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=(os.name != "nt"))
    except OSError:
        return False
    return True


def send(kind, text, bead="", ask_id="", full="", repeat=False):
    """Push once, never wait, never raise. -> 'sent' | 'off' | 'failed: why'."""
    how, cmd = channel()
    if how == "off":
        return "off"
    if how == "desktop":
        return "sent" if desktop("task-loop: %s" % (bead or kind), text) else "failed: no desktop notifier on this machine"
    env = dict(os.environ, TL_ASK_KIND=kind, TL_ASK_BEAD=bead, TL_ASK_ID=ask_id, TL_ASK_TEXT=text[:500],
               TL_DIGEST_TEXT=full or text)
    try:
        subprocess.Popen(cmd, shell=True, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=(os.name != "nt"))
    except OSError as e:
        return "failed: %s" % e
    return "sent"

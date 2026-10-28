"""The short notes a worker is sent when its step goes on after a stop, and the gaps between network probes."""

from typing import Final

NET_BACKOFF: Final = (5, 10, 20, 40, 60, 120)  # seconds between the probes of a step that waits for the network
FRESH_WRITER_TEXT: Final = (
    "\nYou take over from an earlier writer of this task, on another model. Its work is in this "
    "tree, committed on this branch or not: read `git status` and the diff from main first, then go on "
    "from there; do not start over."
)
RESUME_AFTER_STOP: Final = (
    "\nYour last attempt at this step stopped before it gave an answer. Continue from where you stopped and "
    "answer in the required format; do not start over."
)
NOTES: Final = {
    "apply_patch": (
        "\nAn earlier attempt at this step ran a command on a secret path and was stopped. Do not read or write "
        "secret files (.env, keys, credentials); change files with your editing tool, never through a shell redirect."
    ),
    "lane_out": "",
}

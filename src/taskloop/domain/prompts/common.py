"""The text every node's prompt shares: the engine preamble, the question rules, the unchecked-items table."""
from typing import Final

COMMON: Final = ("You are one step of an unattended task engine. Nobody is watching; do not ask for confirmation. "
          "Work only in {wt}. Never commit, push, branch, or change git state. Never add suppressions or weaken, skip "
          "or delete tests; a test that contradicts an accepted requirement is fixed to match the requirement, never "
          "weakened or deleted to make the code pass. Answer with the structured result only.")

DECIDED_RULE: Final = ("A change that contradicts an accepted requirement (in the task, its acceptance criteria, or a "
                "requirement it cites) is never the owner's question: the fix is to meet the requirement. Nor is a test, "
                "check or scenario at odds with an accepted requirement: that is no conflict between two requirements. "
                "A test that contradicts an accepted requirement is fixed to match the requirement, never weakened or "
                "deleted to make the code pass. An owner's answer in the task's comments decides "
                "as an accepted requirement does. decided: the "
                "accepted requirement, quoted, that already answers your question (the engine then sends the stage "
                "back to meet it instead of asking the owner); empty when you have no question, when two accepted "
                "requirements conflict, or when no requirement decides it yet (those are the owner's).")

OPTIONS_RULE: Final = ("options: with a question, 2-4 answers the owner can click, each a short label, a one-line cost, the exact "
                "answer text the next run will read, and recommended (true for exactly one: yours); empty with no question.")

KIND_LINES: Final = (
    "engine_step: something the engine itself does after this point (files leftover or follow-up beads, lands, runs the "
    "gate, copies screenshots, closes the bead)",
    "checkable: a behaviour, a number the code computes or a rate holding across cases: a test or check could prove it",
    "external_fact: a fact from outside the repo (a price, a licence, a size quoted from a web page or a file the repo "
    "does not hold) that no check here can prove; give its source (a URL or the named outside document)",
    "taste: a look, a feel or a judgement call only a person can make",
    "owner_decision: needs the owner to decide: a change to the contract or requirements, money, an account or a login",
    "case: an acceptance case you could not run",
)

UNCHECKED_TEXT: Final = ("\nunchecked: what you could not check yourself, each with its kind: " + "; ".join(KIND_LINES) +
                  "; or other. Empty when you checked everything. "
                  "Only a visual bead is verified after you: for any other bead an unchecked item lands as a follow-up bead.")

LATER_CASES: Final = ("\nAn acceptance case this stage cannot run is not unchecked: it is checked when the last stage runs it.")

DECIDED_TEXT: Final = ("\nYou asked: %s\nAn accepted requirement already decides it: %s\nMeet that requirement: change the "
                "work, never the requirement.\n")

RULES_MAX: Final = 3 * 1024  # a worker_rules file is inlined once, in the planner's and the writer's first prompts: this many bytes at most

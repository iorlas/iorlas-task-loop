"""The reflection prompt."""

REFLECT_PROMPT = """You write a short reflection on one run of an unattended task engine, for the engineer who maintains the engine. Do not
edit files; judge only from what is below.
Bead %s: %s
Outcome: %s. Why: %s
Counts: %s
The run's worker sessions (cite the session id):
%s
The run's decisions and warnings, oldest first:
%s

Answer:
- went_well: up to 4 lines, each one concrete thing that worked.
- went_badly: up to 4 items; each: what (one line), cause (one of engine, prompt, delegate, repo_profile, bead, sandbox, other), session
  (the session id above it comes from, or "run"), evidence (a number or a quote from above). Empty when nothing went badly.
- wasted: up to 3 lines, where tokens or minutes went for nothing, with the numbers.
- change: up to 3 lines, what to change, naming the cause class.
Cite only what the data above shows; do not guess a cause it does not support."""

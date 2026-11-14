// The one table of the page's words for the factory's typed codes (a summary, a hold cause, a verification result, an answer
// disposition). A code in the table shows its words and keeps the raw code as hover text; a code not in the table shows raw, so a new
// backend code is never hidden or guessed. Display only: nothing here decides anything.

export const WORDS = {
  needs_owner: "The agent needs your decision",
  "failed:needs_owner": "The agent needs your decision",
  incomplete: "The agent stopped without finishing",
  "failed:incomplete": "The agent stopped without finishing",
  main_moved: "Main moved while the checks ran",
  "failed:main_moved": "Main moved while the checks ran",
  "answer:schema_invalid": "The agent's answer was in the wrong format",
  "failed:answer:schema_invalid": "The agent's answer was in the wrong format",
  "answer:json_invalid": "The agent's answer was not valid JSON",
  "failed:answer:json_invalid": "The agent's answer was not valid JSON",
  "answer:missing": "The agent gave no answer",
  "failed:answer:missing": "The agent gave no answer",
  "run:timeout": "The agent did not finish in time",
  "failed:run:timeout": "The agent did not finish in time",
  repeats_exhausted: "The agent did not settle its files after repeats",
  "failed:repeats_exhausted": "The agent did not settle its files after repeats",
  "failed:test:failed": "Checks failed: test",
  "held:slot_dirty": "Slot has leftover files",
  "held:slot_branch": "Slot is on another branch",
  "held:slot_redirected": "Slot pointer was rewritten",
  failed_check: "The checks failed",
  verification: "The factory's check of the answer failed",
  unsafe: "A listed path is unsafe",
  uncommitted: "Files were left uncommitted",
  ignored: "A listed path is ignored by Git",
  branch: "The slot was not on the task branch",
  rejected: "The commit broke a rule",
  repeat: "Reason not recorded",
  verified: "Checked and committed",
  reused: "Nothing new; earlier commit kept",
  "unsettled:branch": "Not committed: the slot was not on the task branch",
  "unsettled:unsafe": "Not committed: a listed path is unsafe",
  "unsettled:ignored": "Not committed: a listed path is ignored by Git",
  "unsettled:uncommitted": "Not committed: files were left uncommitted",
  "unsettled:rejected": "Not committed: the commit broke a rule",
  pending: "Not checked yet",
  registered: "Starting",
  passed: "All checks passed",
};

// A code with a family prefix and a tail the table cannot list (a rule, a check name).
const FAMILIES = [
  ["failed:rejected:", "Not committed: the commit broke a rule: "],
  ["rejected:", "Not committed: the commit broke a rule: "],
  ["failed:run:", "The agent attempt failed: "],
  ["run:", "The agent attempt failed: "],
  ["failed:test:", "Checks failed: "],
  ["test:", "Checks failed: "],
];

// The words of a code, or the code itself when the page has none for it.
export function say(code) {
  if (typeof code !== "string") return code;
  if (Object.hasOwn(WORDS, code)) return WORDS[code];
  const family = FAMILIES.find(([prefix]) => code.startsWith(prefix) && code.length > prefix.length);
  return family ? `${family[1]}${code.slice(family[0].length)}` : code;
}

// An element for a code: its words as text, the raw code as hover text when the words differ.
export function wordNode(el, code, cls) {
  const node = el("span", cls, say(code));
  if (say(code) !== code) node.title = code;
  return node;
}

// Mock data source: turns fixtures.json into the shapes in docs/design/dashboard-ui.md and replays a script of
// events on a timer. Deleted when the server slice lands; app.js only knows the source interface
// {label, snapshot(), detail(id), subscribe(on)}.

const STEPS = ["plan", "implement", "checks", "land"];
const FEED_LIMIT = 20;
const iso = (agoS) => new Date(Date.now() - agoS * 1000).toISOString();
const now = () => new Date().toISOString();

function card(t) {
  return {
    id: t.id, title: t.title, column: t.column, attempt: t.attempt, repeat: t.repeat,
    step_started_at: iso(t.step_started_ago_s), last_activity_at: iso(t.last_activity_ago_s),
    slot: t.slot, hold_cause: t.hold_cause,
  };
}

const event = ({ ago_s, ...rest }) => ({ ...rest, at: iso(ago_s) });

// One chronological list of attempts. `after` says how an attempt began: null (the previous step succeeded),
// "repeat" (same step again) or "restart_at_plan", with the `reason`. Numbers count per step.
function buildAttempts(planStarts) {
  const out = [];
  const seen = {};
  planStarts.forEach((ps, i) => {
    let first = true;
    for (const stage of ps.stages) {
      for (const a of stage.attempts) {
        seen[stage.step] = (seen[stage.step] || 0) + 1;
        const prev = out.at(-1);
        let after = null;
        let reason = null;
        if (prev && first && i > 0) [after, reason] = ["restart_at_plan", planStarts[i - 1].reason];
        else if (prev && prev.step === stage.step) [after, reason] = ["repeat", prev.summary];
        first = false;
        out.push({
          step: stage.step, n: seen[stage.step], state: a.state, started_at: iso(a.started_ago_s),
          ended_at: a.duration_s == null ? null : iso(a.started_ago_s - a.duration_s),
          summary: a.summary, after, reason, output: a.output ?? null, feed: a.feed.map(event).slice(-FEED_LIMIT),
        });
      }
    }
  });
  return out;
}

// A task with no recorded history gets one succeeded attempt per step before its column.
function plainAttempts(t) {
  if (t.column === "waiting") return [];
  const upto = t.column === "landed" ? STEPS.length : STEPS.indexOf(t.column) + 1;
  return STEPS.slice(0, upto).map((step, i) => {
    const running = i === upto - 1 && t.column !== "landed";
    return {
      step, n: 1, state: running ? "running" : "succeeded", started_at: iso(t.step_started_ago_s + (upto - i) * 300),
      ended_at: running ? null : iso(t.step_started_ago_s + (upto - i - 1) * 300),
      summary: running ? "running" : `${step} succeeded`, after: null, reason: null, output: null, feed: [],
    };
  });
}

// What the agent is told in a step. The real prompt comes from the step kind; this is a stand-in of the same shape.
function promptFor(task, fields, step, after, reason) {
  if (step !== "plan" && step !== "implement") return null;
  const head = `You are the ${step === "plan" ? "planning" : "implementing"} agent for task ${task.id}.\n\nTask: ${task.title}\n\n${fields.description}\n\n`;
  const body = step === "plan"
    ? `Write the plan to docs/design/${task.id}/plan.md. Name the files you will touch, the tests you will add and what finishes the task. Do not change code in this step.`
    : `The admitted plan is at docs/design/${task.id}/plan.md. Implement it in this slot's worktree on task branch ${fields.branch}. Run the focused tests before you answer. Do not edit check configuration unless the plan says so.`;
  const feedback = after ? `\n\nThe previous attempt ended: ${reason}\nFix that first.` : "";
  return `${head}${body}${feedback}\n\nReply with the answer JSON: {"disposition": "${step === "plan" ? "planned" : "implemented"}" | "unchanged" | "incomplete" | "needs_owner", "summary": "..."}.`;
}

// Fields the backend stores per attempt; the mock derives them from what it has.
function withDerived(d) {
  for (const a of d.attempts) {
    a.input = promptFor(d.task, d.fields, a.step, a.after, a.reason);
    const checks = a.feed.filter((e) => e.type === "check")
      .map((e) => ({ name: e.name, passed: e.passed, duration_ms: e.duration_ms, output: e.passed ? null : (a.output ?? "No output captured.") }));
    const lastMessage = a.feed.findLast((e) => e.type === "message")?.text;
    const answer = a.state === "running" || !a.input ? null
      : { disposition: a.state === "succeeded" ? (a.step === "plan" ? "planned" : "implemented") : "incomplete", text: a.state === "failed" ? (lastMessage ?? a.summary) : a.summary };
    a.result = { summary: a.summary, answer, checks, output: checks.length ? null : a.output };
  }
  return d;
}

// Keep the mock's own detail in step with the events it sends, as the real backend's store will.
function applyMove(d, next) {
  if (next.column === d.task.column) return;
  const running = d.attempts.find((a) => a.state === "running");
  const end = (state, summary) => running && Object.assign(running, { state, summary, ended_at: now() });
  if (next.column === "held") end("failed", next.hold_cause);
  else if (next.column === "landed") end("succeeded", "Landed as a squash on main.");
  else if (STEPS.includes(next.column)) {
    end("succeeded", "step succeeded");
    const prev = d.attempts.at(-1);
    const after = next.column === "plan" && d.attempts.length ? "restart_at_plan" : prev?.step === next.column ? "repeat" : null;
    const n = d.attempts.filter((a) => a.step === next.column).length + 1;
    d.attempts.push({ step: next.column, n, state: "running", started_at: now(), ended_at: null, summary: "running", after, reason: null, output: null, feed: [] });
  }
}

function applyFeed(d, step, n, e) {
  const attempt = d.attempts.find((a) => a.step === step && a.n === n);
  if (!attempt) return;
  const at = e.id ? attempt.feed.findIndex((x) => x.id === e.id) : -1;
  if (at >= 0) attempt.feed[at] = e;
  else attempt.feed.push(e);
  attempt.feed = attempt.feed.slice(-FEED_LIMIT);
}

export async function mockSource() {
  const fx = await (await fetch("fixtures.json")).json();
  const snapshot = { generated_at: now(), slots: fx.slots, tasks: fx.tasks.map(card) };
  const detail = {};
  for (const t of fx.tasks) {
    const { created_ago_s, ...fields } = t.fields;
    detail[t.id] = {
      task: card(t),
      fields: { ...fields, created_at: iso(created_ago_s), updated_at: iso(fields.updated_ago_s) },
      comments: (fx.comments[t.id] || []).map(({ ago_s, ...c }) => ({ ...c, at: iso(ago_s) })),
      attempts: fx.history[t.id] ? buildAttempts(fx.history[t.id]) : plainAttempts(t),
    };
  }
  return {
    label: "mock data",
    snapshot: async () => structuredClone(snapshot),
    detail: async (id) => structuredClone(withDerived(detail[id])),
    subscribe(on) {
      const current = new Map(snapshot.tasks.map((t) => [t.id, t]));
      for (const step of fx.script) {
        setTimeout(() => {
          if (step.kind === "feed") {
            const e = { ...step.event, at: now() };
            applyFeed(detail[step.task_id], step.step, step.attempt, e);
            return on({ kind: "feed", task_id: step.task_id, step: step.step, attempt: step.attempt, event: e });
          }
          const { step_started_ago_s = 0, ...patch } = step.task;
          const next = { ...current.get(step.task.id), ...patch, step_started_at: iso(step_started_ago_s), last_activity_at: now() };
          applyMove(detail[next.id], next);
          detail[next.id].task = next;
          current.set(next.id, next);
          on({ kind: "task", task: next });
        }, step.after_s * 1000);
      }
    },
  };
}

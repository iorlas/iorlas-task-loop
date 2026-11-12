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

// Attempt numbers count per step across plan_starts, in the order they happened.
function buildPlanStarts(plan_starts) {
  const seen = {};
  return plan_starts.map((c, i) => ({
    n: i + 1, outcome: c.outcome, reason: c.reason,
    stages: c.stages.map((s) => ({
      step: s.step,
      attempts: s.attempts.map((a) => {
        seen[s.step] = (seen[s.step] || 0) + 1;
        return {
          n: seen[s.step], state: a.state, started_at: iso(a.started_ago_s),
          ended_at: a.duration_s == null ? null : iso(a.started_ago_s - a.duration_s),
          summary: a.summary, feed: a.feed.map(event).slice(-FEED_LIMIT),
        };
      }),
    })),
  }));
}

// A task with no recorded history gets a plain one-planStart history up to its column.
function plainPlanStarts(t) {
  if (t.column === "waiting") return [];
  const upto = t.column === "landed" ? STEPS.length : STEPS.indexOf(t.column) + 1;
  const stages = STEPS.slice(0, upto).map((step, i) => {
    const running = i === upto - 1 && t.column !== "landed";
    return {
      step,
      attempts: [{
        n: 1, state: running ? "running" : "succeeded", started_at: iso(t.step_started_ago_s + (upto - i) * 300),
        ended_at: running ? null : iso(t.step_started_ago_s + (upto - i - 1) * 300),
        summary: running ? "running" : `${step} succeeded`, feed: [],
      }],
    };
  });
  return [{ n: 1, outcome: t.column === "landed" ? "landed" : "running", reason: null, stages }];
}

function lastAttempt(planStart) {
  const stage = planStart.stages[planStart.stages.length - 1];
  return stage && stage.attempts[stage.attempts.length - 1];
}

// Keep the mock's own detail in step with the events it sends, as the real backend's store will.
function applyMove(d, next) {
  if (next.column === d.task.column) return;
  let planStart = d.plan_starts[d.plan_starts.length - 1];
  if (!planStart || ["landed", "held"].includes(planStart.outcome)) {
    planStart = { n: d.plan_starts.length + 1, outcome: "running", reason: null, stages: [] };
    d.plan_starts.push(planStart);
  }
  const running = lastAttempt(planStart);
  const end = (state, summary) => {
    if (running && running.state === "running") Object.assign(running, { state, summary, ended_at: now() });
  };
  if (next.column === "held") {
    end("failed", next.hold_cause);
    planStart.outcome = "held";
  } else if (next.column === "landed") {
    end("succeeded", "Landed as a squash on main.");
    planStart.outcome = "landed";
  } else if (STEPS.includes(next.column)) {
    end("succeeded", "step succeeded");
    let stage = planStart.stages.find((s) => s.step === next.column);
    if (!stage) planStart.stages.push((stage = { step: next.column, attempts: [] }));
    const total = d.plan_starts.flatMap((c) => c.stages).filter((s) => s.step === next.column).reduce((n, s) => n + s.attempts.length, 0);
    stage.attempts.push({ n: total + 1, state: "running", started_at: now(), ended_at: null, summary: "running", feed: [] });
  }
}

function applyFeed(d, step, n, e) {
  const attempt = d.plan_starts.flatMap((c) => c.stages).filter((s) => s.step === step).flatMap((s) => s.attempts).find((a) => a.n === n);
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
      fields: { ...fields, created_at: iso(created_ago_s) },
      plan_starts: fx.plan_starts[t.id] ? buildPlanStarts(fx.plan_starts[t.id]) : plainPlanStarts(t),
    };
  }
  return {
    label: "mock data",
    snapshot: async () => structuredClone(snapshot),
    detail: async (id) => structuredClone(detail[id]),
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

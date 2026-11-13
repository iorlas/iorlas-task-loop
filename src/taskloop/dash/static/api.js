// The page's data source: JSON endpoints and one server-sent-events stream (docs/design/dashboard-ui.md).
// The same interface the page always used: {label, snapshot(), detail(id), logs(), subscribe(on)}.

const json = async (path, signal) => {
  const response = await fetch(path, { headers: { accept: "application/json" }, signal });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw Object.assign(new Error(body.error ?? `${path}: ${response.status}`), { status: response.status });
  }
  return response.json();
};

export function apiSource() {
  return {
    label: "live",
    snapshot: () => json("/api/board"),
    detail: (id) => json(`/api/tasks/${encodeURIComponent(id)}`),
    // The tracker's side of a task (`bd` calls, slow under load): a separate request, which `signal` can cancel.
    tracker: (id, signal) => json(`/api/tasks/${encodeURIComponent(id)}/tracker`, signal),
    logs: () => json("/api/log"),
    // One attempt's agent lines: its latest, or those after `after` (the cursor of the last answer, opaque to the page).
    feed: (id, step, n, after) => json(`/api/tasks/${encodeURIComponent(id)}/attempts/${step}/${n}/feed${after ? `?after=${after}` : ""}`),
    // Messages are {kind: "task" | "gone" | "feed" | "log" | "error" | "resync", ...}: `error` says the board cannot be read, `resync`
    // (after an error, and on a reconnect) says to load it again.
    subscribe(on) {
      const stream = new EventSource("/api/events");
      let seen = false;
      stream.addEventListener("open", () => {
        if (seen) on({ kind: "resync" });
        seen = true;
      });
      stream.addEventListener("message", (event) => on(JSON.parse(event.data)));
    },
  };
}

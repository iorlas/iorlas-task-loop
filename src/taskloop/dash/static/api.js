// The page's data source: JSON endpoints and one server-sent-events stream (docs/design/dashboard-ui.md).
// The page interface: {snapshot(), detail(id), logs(), subscribe(on, connection)}.

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
    snapshot: () => json("/api/board"),
    detail: (id) => json(`/api/tasks/${encodeURIComponent(id)}`),
    // The tracker's side of a task (`bd` calls, slow under load): a separate request, which `signal` can cancel.
    tracker: (id, signal) => json(`/api/tasks/${encodeURIComponent(id)}/tracker`, signal),
    logs: () => json("/api/log"),
    // What a selected attempt shows besides its lines (prompt, answer, check outputs): read only when asked.
    body: (id, step, n) => json(`/api/tasks/${encodeURIComponent(id)}/attempts/${step}/${n}`),
    // One attempt's agent lines: its latest, or those after `after` (the cursor of the last answer, opaque to the page).
    feed: (id, step, n, after) => json(`/api/tasks/${encodeURIComponent(id)}/attempts/${step}/${n}/feed${after ? `?after=${after}` : ""}`),
    // Messages are {kind: "task" | "gone" | "feed" | "log" | "error" | "resync", ...}: `error` says the board cannot be read, `resync`
    // (after an error, and on every open) says to load it again. Transport state is reported separately.
    subscribe(on, connection) {
      const stream = new EventSource("/api/events");
      stream.addEventListener("open", () => {
        connection(true);
        on({ kind: "resync" });
      });
      stream.addEventListener("error", () => connection(false));
      stream.addEventListener("message", (event) => on(JSON.parse(event.data)));
    },
  };
}

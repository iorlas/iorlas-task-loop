// The page's data source: JSON endpoints and one server-sent-events stream (docs/design/dashboard-ui.md).
// The same interface the page always used: {label, snapshot(), detail(id), logs(), subscribe(on)}.

const json = async (path) => {
  const response = await fetch(path, { headers: { accept: "application/json" } });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
};

export function apiSource() {
  return {
    label: "live",
    snapshot: () => json("/api/board"),
    detail: (id) => json(`/api/tasks/${encodeURIComponent(id)}`),
    logs: () => json("/api/log"),
    // Messages are {kind: "task" | "feed" | "log", ...}; a reconnect says {kind: "resync"} so the page reloads the board.
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

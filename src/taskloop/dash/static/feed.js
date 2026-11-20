// One selected attempt owns its requests. A stopped follower cannot update another selection.
import { $, tick } from "./ui.js";
import { apply, setNote, show, touchQuiet } from "./lines.js";
import { receiveDuration } from "./duration.js";

export function followFeed(source, id, a, hooks) {
  let active = true;
  let busy = false;
  let first = true;
  const checks = a.step === "checks";
  let cursor = checks ? undefined : a.feed_cursor ?? "0:0";
  const current = () => active && hooks.current();
  async function poll() {
    if (busy || !current()) return;
    busy = true;
    try {
      const page = await source.feed(id, a.step, a.n, cursor);
      if (!current()) return;
      const reset = page.replaced || (checks && first);
      let redraw = reset;
      if (!checks) {
        receiveDuration(page.duration);
        redraw ||= page.duration?.execution !== a.duration?.execution || page.duration?.frozen !== a.duration?.frozen;
        a.duration = page.duration;
        $("drawer").querySelectorAll("[data-duration]").forEach(tick);
      } else {
        a.feedAvailable = page.available;
        if (reset || page.events.length) hooks.invalidate();
      }
      a.feedError = null;
      cursor = page.cursor ?? cursor;
      a.feed_cursor = cursor;
      if (reset) a.feed = checks ? [] : a.feed.filter((e) => e.type === "step");
      for (const e of page.events) apply(a, e);
      first = false;
      if (redraw || (checks && page.events.length && hooks.resultOpen())) hooks.render();
      else page.events.forEach((e) => show(a, e, hooks.activate));
      setNote(a);
      touchQuiet(a);
    } catch (error) {
      if (current()) {
        a.feedError = error.message ?? String(error);
        setNote(a);
      }
    } finally {
      busy = false;
    }
  }
  const timer = a.state === "running" ? setInterval(poll, 2000) : null;
  a.feedRetry = poll;
  if (checks) poll();
  return () => {
    active = false;
    clearInterval(timer);
    if (a.feedRetry === poll) delete a.feedRetry;
  };
}

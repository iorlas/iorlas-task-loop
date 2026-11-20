// Dependency-free contracts: node --test tests/dash/navigation-codec.test.js
import assert from "node:assert/strict";
import test from "node:test";
import { decode, encode, initNavigation, resolveSelection, selectionRoute, ROUTE } from "../../src/taskloop/dash/static/navigation.js";

const detail = { attempts: [
  { step: "plan", n: 1, state: "succeeded", past: true },
  { step: "commit", n: 31, state: "succeeded", past: true },
  { step: "checks", n: 1, state: "succeeded" },
  { step: "implement", n: 2, state: "running" },
] };
const resolve = (hash, value = detail) => {
  const route = decode(hash);
  return selectionRoute({ id: route.id, detail: value, ...resolveSelection(value, route) });
};

test("fragments preserve encoded IDs and every drawer selection", () => {
  for (const hash of ["#id", "#id/task", "#id/steps", "#id/land", "#id/land/task", "#a%2Fb%20%23/plan/1/lines",
    "#id/implement/2/prompt", "#id/checks/1/result", "#id/commit/31/result", "#id/plan/1/task"]) {
    assert.equal(encode(decode(hash)), hash);
  }
  assert.deepEqual(decode("#a%2Fb%20%23/plan/1/lines"), { kind: ROUTE.attempt, id: "a/b #", step: "plan", n: 1, tab: "lines" });
});

test("malformed fragments close safely", () => {
  for (const hash of ["", "#", "#%zz", "#/plan/1/result", "#a/nonsense/1/result", "#a/plan/0/result",
    "#a/plan/-1/result", "#a/plan/1.5/result", "#a/plan/01/result", "#a/plan/9007199254740992/result",
    "#a/plan/1/nonsense", "#a/plan/1/result/extra", "#a/plan/1", "#a/land/1/result"]) {
    assert.equal(decode(hash).kind, ROUTE.closed, hash);
  }
});

test("defaults, historical attempts, factory commit and absent attempts resolve canonically", () => {
  for (const [input, output] of [
    ["#id", "#id/implement/2/lines"],
    ["#id/task", "#id/implement/2/task"],
    ["#id/plan/1/prompt", "#id/plan/1/prompt"],
    ["#id/plan/1/task", "#id/plan/1/task"],
    ["#id/checks/1/result", "#id/checks/1/result"],
    ["#id/commit/31/lines", "#id/commit/31/result"],
    ["#id/implement/99/result", "#id/implement/2/lines"],
    ["#id/plan/99/prompt", "#id/implement/2/lines"],
    ["#id/land", "#id/land"], ["#id/land/task", "#id/land/task"],
  ]) assert.equal(encode(resolve(input)), output);
  assert.equal(encode(resolve("#id", { attempts: [] })), "#id/task");
  assert.equal(encode(resolve("#id/steps", { attempts: [] })), "#id/steps");
  assert.equal(encode(resolve("#id/land", { attempts: [] })), "#id/land");
  const ended = { attempts: [{ step: "implement", n: 2, state: "succeeded" }] };
  assert.equal(encode(resolve("#id", ended)), "#id/implement/2/result");
  assert.equal(encode(selectionRoute(null)), "");
  assert.equal(encode(selectionRoute({ id: "loading", detail: null })), "#loading");
});

// A semantic browser port: state writes never emit navigation events; traversals emit both events.
function browserPort(hash = "") {
  const events = new EventTarget();
  const location = { hash, pathname: "/dash", search: "?repo=test" };
  const entries = [hash];
  const writes = [];
  let index = 0;
  const write = (replace, url) => {
    assert.ok(url.startsWith("/dash?repo=test"));
    location.hash = url.includes("#") ? url.slice(url.indexOf("#")) : "";
    if (replace) entries[index] = location.hash;
    else { entries.splice(index + 1); entries.push(location.hash); index++; }
    writes.push(replace ? "replace" : "push");
  };
  return {
    location, entries, writes,
    addEventListener: (...args) => events.addEventListener(...args),
    removeEventListener: (...args) => events.removeEventListener(...args),
    history: { pushState: (_state, _unused, url) => write(false, url), replaceState: (_state, _unused, url) => write(true, url) },
    go(offset) {
      index += offset;
      location.hash = entries[index];
      events.dispatchEvent(new Event("popstate"));
      events.dispatchEvent(new Event("hashchange"));
    },
  };
}

test("initial restoration and Back/Forward apply each location once without adding entries", () => {
  const browser = browserPort("#id/plan/1/prompt");
  const applied = [];
  const navigation = initNavigation((route) => applied.push(encode(route)), browser);
  navigation.start();
  assert.deepEqual(applied, ["#id/plan/1/prompt"]);
  assert.deepEqual(browser.writes, []);
  navigation.changed(decode("#id/implement/2/lines"));
  navigation.changed(decode("#id/implement/2/task"));
  navigation.changed(decode(""));
  assert.equal(browser.entries.length, 4);
  browser.go(-1); browser.go(-1); browser.go(-1); browser.go(1); browser.go(1); browser.go(1);
  assert.deepEqual(applied.slice(1), ["#id/implement/2/task", "#id/implement/2/lines", "#id/plan/1/prompt",
    "#id/implement/2/lines", "#id/implement/2/task", ""]);
  assert.deepEqual(browser.writes, ["push", "push", "push"]);
  navigation.stop();
  browser.go(-1);
  assert.equal(applied.length, 7, "stopped controller no longer applies locations");
});

test("default resolution replaces its entry, redraws do not write and malformed URLs repair closure", () => {
  const browser = browserPort("#id");
  let navigation;
  navigation = initNavigation((route) => navigation.changed(resolve(encode(route)), true), browser);
  navigation.start();
  assert.deepEqual(browser.entries, ["#id/implement/2/lines"]);
  assert.deepEqual(browser.writes, ["replace"]);
  navigation.changed(resolve("#id"), true);
  assert.deepEqual(browser.writes, ["replace"]);
  navigation.stop();
  const malformed = browserPort("#id/plan/0/result");
  const repair = initNavigation((route) => assert.equal(route.kind, ROUTE.closed), malformed);
  repair.start();
  assert.deepEqual(malformed.entries, [""]);
  assert.deepEqual(malformed.writes, ["replace"]);
  repair.stop();
});

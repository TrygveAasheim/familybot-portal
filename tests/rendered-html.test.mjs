import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(new Request("http://localhost/", { headers: { accept: "text/html" } }), { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } }, { waitUntil() {}, passThroughOnException() {} });
}

test("server-renders the iPad family dashboard shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.doesNotMatch(html, /codex-preview/i);
  assert.match(html, /<title>Familieportalen<\/title>/i);
  assert.match(html, /Familieportalen våkner/);
  assert.doesNotMatch(html, /example data|eksempeldata|react-loading-skeleton/i);
});

test("source keeps the data boundary and functional surfaces explicit", async () => {
  const [page, consoleSource, apiSource, styles] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/_components/FamilyConsole.tsx", import.meta.url), "utf8"),
    readFile(new URL("../local_api/familybot_api.py", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);
  assert.doesNotMatch(page, /codex-preview/);
  assert.match(consoleSource, /Familiens oversikt/);
  assert.match(consoleSource, /Hva vil du gjøre/);
  assert.match(consoleSource, /Legg til gjøremål/);
  assert.match(consoleSource, /repeat_weekdays/);
  assert.match(consoleSource, /mission-progress/);
  assert.match(consoleSource, /Nullstill begge/);
  assert.match(consoleSource, /Fullførte uker/);
  assert.match(consoleSource, /weekly-achievement/);
  assert.match(consoleSource, /function completionKey/);
  assert.match(consoleSource, /sessionToken\.current&&sessionToken\.current!==nextToken/);
  assert.match(consoleSource, /window\.location\.reload\(\)/);
  assert.match(consoleSource, /Skolen denne uken/);
  assert.match(consoleSource, /function renderWeekPlanText/);
  assert.match(consoleSource, /function renderWeekPlanInterpretation/);
  assert.match(consoleSource, /week-plan-interpretation/);
  assert.match(consoleSource, /week-plan-rich-text/);
  assert.match(consoleSource, /week-plan-list/);
  assert.doesNotMatch(consoleSource, /<pre>\{detail\.full_text\}<\/pre>/);
  assert.match(consoleSource, /Neste 5 dager/);
  assert.match(consoleSource, /function upcomingEventsFor/);
  assert.match(consoleSource, /slice\(0,4\)/);
  assert.match(consoleSource, /Kanban/);
  assert.match(consoleSource, /New/);
  assert.match(consoleSource, /In Progress/);
  assert.match(consoleSource, /Pause/);
  assert.match(consoleSource, /Done/);
  assert.match(consoleSource, /api\/kanban/);
  assert.match(consoleSource, /Kanban er skrivebeskyttet/);
  assert.match(consoleSource, /function TransportCountdown/);
  assert.match(consoleSource, /Familiebot fungerer/);
  assert.match(consoleSource, /Familiebot har stoppet/);
  assert.match(consoleSource, /Familiebot fungerer med avvik/);
  assert.doesNotMatch(consoleSource, /<p className="eyebrow">Hjemme<\/p><h2>FamilyBot<\/h2>/);
  assert.match(consoleSource, /God morgen/);
  assert.match(consoleSource, /God dag/);
  assert.match(consoleSource, /God ettermiddag/);
  assert.match(consoleSource, /God kveld/);
  const greetingSource = consoleSource.match(/function greetingForHour\(hour:number\)\{[^}]+\}/)?.[0];
  assert.ok(greetingSource);
  const greetingForHour = Function(`${greetingSource.replace("hour:number", "hour")}; return greetingForHour;`)();
  assert.equal(greetingForHour(7), "God morgen");
  assert.equal(greetingForHour(12), "God dag");
  assert.equal(greetingForHour(16), "God ettermiddag");
  assert.equal(greetingForHour(20), "God kveld");
  assert.equal(greetingForHour(2), "God kveld");
  assert.doesNotMatch(consoleSource, /Spør FamilyBot i Telegram/);
  assert.match(styles, /\.realtime-badge\{[^}]*white-space:nowrap/);
  assert.match(styles, /\.departure-countdown\{[^}]*white-space:nowrap/);
  assert.match(consoleSource, /setInterval\(\(\)=>setNow\(Date\.now\(\)\),1_000\)/);
  assert.match(consoleSource, /Neste mot sentrum|transport\.status/);
  assert.match(apiSource, /centre_quay_id/);
  assert.match(apiSource, /ET-Client-Name/);
  assert.doesNotMatch(consoleSource, /crypto\.randomUUID\(\)/);
  assert.match(apiSource, /0\.0\.0\.0/);
  assert.match(apiSource, /X-FamilyBot-Local-Token/);
  assert.match(apiSource, /X-FamilyBot-Parent-Token/);
  assert.match(apiSource, /archived_at=datetime\('now'\)/);
  assert.match(apiSource, /chore_cycles/);
  assert.match(apiSource, /reset_child/);
  assert.match(apiSource, /LANES = \{"todo", "inprogress", "onhold", "done"\}/);
  assert.match(apiSource, /api\/kanban/);
  assert.match(apiSource, /NOT EXISTS \(SELECT 1 FROM family_chore_meta/);
  assert.match(apiSource, /weekly_achievement_cycles/);
  assert.match(apiSource, /weekly_surprise_levels/);
  assert.doesNotMatch(apiSource, /SELECT \*/i);
});

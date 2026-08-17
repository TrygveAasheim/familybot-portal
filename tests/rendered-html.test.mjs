import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const developmentPreviewMeta = /<meta(?=[^>]*\bname=["']codex-preview["'])(?=[^>]*\bcontent=["']development["'])[^>]*>/i;

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
  assert.match(html, developmentPreviewMeta);
  assert.match(html, /<title>Familieportalen<\/title>/i);
  assert.match(html, /Familieportalen våkner/);
  assert.doesNotMatch(html, /example data|eksempeldata|react-loading-skeleton/i);
});

test("source keeps the data boundary and functional surfaces explicit", async () => {
  const [page, consoleSource, apiSource] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/_components/FamilyConsole.tsx", import.meta.url), "utf8"),
    readFile(new URL("../local_api/familybot_api.py", import.meta.url), "utf8"),
  ]);
  assert.match(page, /codex-preview/);
  assert.match(consoleSource, /Familiens oversikt/);
  assert.match(consoleSource, /Hva vil du gjøre/);
  assert.match(consoleSource, /Legg til gjøremål/);
  assert.match(consoleSource, /function completionKey/);
  assert.match(consoleSource, /Skolen denne uken/);
  assert.match(consoleSource, /function TransportCountdown/);
  assert.match(consoleSource, /setInterval\(\(\)=>setNow\(Date\.now\(\)\),1_000\)/);
  assert.match(consoleSource, /Neste mot sentrum|transport\.status/);
  assert.match(apiSource, /centre_quay_id/);
  assert.match(apiSource, /ET-Client-Name/);
  assert.doesNotMatch(consoleSource, /crypto\.randomUUID\(\)/);
  assert.match(apiSource, /0\.0\.0\.0/);
  assert.match(apiSource, /X-FamilyBot-Local-Token/);
  assert.match(apiSource, /X-FamilyBot-Parent-Token/);
  assert.match(apiSource, /archived_at=datetime\('now'\)/);
  assert.doesNotMatch(apiSource, /SELECT \*/i);
});

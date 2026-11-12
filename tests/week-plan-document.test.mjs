import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const source = await readFile(new URL("../app/_components/WeekPlanDocument.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
}).outputText
  .replaceAll('"react/jsx-runtime"', JSON.stringify(import.meta.resolve("react/jsx-runtime")))
  .replaceAll('from "react"', `from ${JSON.stringify(import.meta.resolve("react"))}`);
const { WeekPlanDocument } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("document controls server-render without browser APIs or exposing session credentials", () => {
  const html = renderToStaticMarkup(createElement(WeekPlanDocument, { url: "/fictional.pdf", token: "private-test-token" }));
  assert.match(html, /Original ukeplan/);
  assert.match(html, /Forrige side/);
  assert.match(html, /Neste side/);
  assert.match(html, /Tilpass bredde/);
  assert.match(html, /Zoom inn/);
  assert.match(html, /<canvas[^>]*hidden=""/);
  assert.doesNotMatch(html, /private-test-token|iframe|<object|<embed|fictional.pdf/);
});

test("viewer remains passive, bounded and locally bundled", async () => {
  assert.match(source, /X-FamilyBot-Local-Token/);
  assert.match(source, /cache: "no-store"/);
  assert.match(source, /enableXfa: false/);
  assert.match(source, /MAX_PAGES = 20/);
  assert.match(source, /new AbortController/);
  assert.match(source, /render.cancel\(\)/);
  assert.match(source, /task\?\.destroy\(\)/);
  assert.doesNotMatch(source, /window.open|dangerouslySetInnerHTML|getJavaScript|getJSActions|AnnotationLayer|https:\/\//);
  const deploy = await readFile(new URL("../scripts/deploy-local.sh", import.meta.url), "utf8");
  assert.match(deploy, /local_api\/week_plan_document\.py/);
});

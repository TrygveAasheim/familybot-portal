import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { weekPlanBlocks } from "../app/_components/weekPlanText.ts";

// Compile the actual leaf component in memory, not a copied/template renderer.
// No new test framework, browser API, provider connection or household data.
const source = await readFile(new URL("../app/_components/WeekPlanContent.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
}).outputText
  .replaceAll('"react/jsx-runtime"', JSON.stringify(import.meta.resolve("react/jsx-runtime")))
  .replaceAll('"./weekPlanText"', JSON.stringify(new URL("../app/_components/weekPlanText.ts", import.meta.url).href));
const { WeekPlanText, WeekPlanInterpreted } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const renderText = text => renderToStaticMarkup(createElement(WeekPlanText, { text }));

test("flattened subject-labelled text becomes separate headings and paragraphs", () => {
  assert.deepEqual(weekPlanBlocks("Norsk: Les side 12. Matematikk: Regn oppgave 4. Engelsk: Øv på glosene."), [
    { kind: "heading", text: "Norsk" }, { kind: "paragraph", text: "Les side 12." },
    { kind: "heading", text: "Matematikk" }, { kind: "paragraph", text: "Regn oppgave 4." },
    { kind: "heading", text: "Engelsk" }, { kind: "paragraph", text: "Øv på glosene." },
  ]);
});

test("standalone labels, CRLF, blank paragraphs and compound subjects are retained", () => {
  assert.deepEqual(weekPlanBlocks("Norsk\r\nLes sammen.\r\nØv høyt.\r\n\r\nSkriv to setninger.\r\nKunst og håndverk: Ta med papir."), [
    { kind: "heading", text: "Norsk" }, { kind: "paragraph", text: "Les sammen.\nØv høyt." },
    { kind: "paragraph", text: "Skriv to setninger." },
    { kind: "heading", text: "Kunst og håndverk" }, { kind: "paragraph", text: "Ta med papir." },
  ]);
});

test("Nynorsk and all-capital explicit labels work without altering content", () => {
  const blocks = weekPlanBlocks("Måndag: Les ei bok. MATEMATIKK: Oppgåve 2. Hugs: Tursekk.");
  assert.deepEqual(blocks.filter(b => b.kind === "heading").map(b => b.text), ["Måndag", "MATEMATIKK", "Hugs"]);
  assert.ok(blocks.some(b => b.text === "Oppgåve 2."));
});

test("ordinary prose, clocks, URLs and unlabelled subjects are not guessed", () => {
  const text = "Vi leser norsk og engelsk på tur. Avreise 09:30. Se https://example.invalid/plan.\nVi øver på norsk: substantiv.";
  assert.deepEqual(weekPlanBlocks(text), [{ kind: "paragraph", text }]);
});

test("bullets and numbered instructions keep order, labels and list structure", () => {
  const blocks = weekPlanBlocks("Lekser\n• Norsk: Les side 12.\n• Matematikk: Oppgave 4.\n\n1. Finn en bok.\n2. Les høyt.");
  assert.deepEqual(blocks, [
    { kind: "heading", text: "Lekser" },
    { kind: "list", ordered: false, items: ["Norsk: Les side 12.", "Matematikk: Oppgave 4."] },
    { kind: "list", ordered: true, start: 1, items: ["Finn en bok.", "Les høyt."] },
  ]);
});

test("unknown headings and unlabeled content remain visible", () => {
  assert.deepEqual(weekPlanBlocks("Prosjektverksted:\nBygg en bro.\n\nNoe mer fra skolen."), [
    { kind: "heading", text: "Prosjektverksted" }, { kind: "paragraph", text: "Bygg en bro." },
    { kind: "paragraph", text: "Noe mer fra skolen." },
  ]);
  assert.deepEqual(weekPlanBlocks("  \n\r\n"), []);
});

test("real text component renders headings, lists and escaped untrusted text", () => {
  const html = renderText("Norsk: Les <script>alert(1)</script> og <SCRIPT>alert(2)</SCRIPT>. Matematikk: Regn.\n• Ta med bok.");
  assert.match(html, /<h3 class="week-plan-heading">Norsk<\/h3><p>Les &lt;script&gt;/);
  assert.match(html, /<h3 class="week-plan-heading">Matematikk<\/h3><p>Regn\.<\/p>/);
  assert.match(html, /<ul class="week-plan-list"><li><div[^>]*><p>Ta med bok\.<\/p><\/div><\/li><\/ul>/);
  assert.match(html, /&lt;SCRIPT&gt;alert\(2\)&lt;\/SCRIPT&gt;/);
  assert.doesNotMatch(html, /<script\b/i);
  assert.match(renderText(""), /Ingen plantekst er tilgjengelig/);
});

test("subject labels inside bullets and original numbering remain readable", () => {
  const html = renderText("• Norsk: Les side 12. Engelsk: Øv på ord.\n\n3. Finn boken.\n4. Les side 7.\n8. Skriv svar.");
  assert.match(html, /<h3 class="week-plan-heading">Norsk<\/h3>/);
  assert.match(html, /<h3 class="week-plan-heading">Engelsk<\/h3>/);
  assert.match(html, /<ol class="week-plan-list" start="3">/);
  assert.match(html, /<ol class="week-plan-list" start="8">/);
});

test("adversarial bullet nesting is bounded and content remains escaped", () => {
  const html = renderText(`${"• ".repeat(2000)}<img src=x onerror=alert(1)>`);
  assert.ok((html.match(/<ul/g) || []).length <= 2);
  assert.match(html, /&lt;img/);
  assert.doesNotMatch(html, /<img/);
});

const item = (category, text) => ({ category, text, source_blocks: ["fictional-block"], confidence: 1 });
test("interpretation has day/category/subject hierarchy and distinct weekly information", () => {
  const interpretation = {
    version: 1, week: 46, year: 2026,
    days: [{ date: "2026-11-09", weekday: "Mandag", items: [
      item("homework", "Norsk: Les side 12. Matematikk: Regn oppgave 4."),
      item("bring", "Gymtøy og vannflaske."),
      item("homework", "Les én gang til."),
    ] }],
    weekly_tasks: [{ text: "Engelsk: Øv på glosene.", source_blocks: [] }],
    general_info: [], general_notes: [{ text: "Beskjeder: Foreldremøte torsdag.", source_blocks: [] }],
  };
  const before = JSON.stringify(interpretation);
  const html = renderToStaticMarkup(createElement(WeekPlanInterpreted, { interpretation }));
  assert.match(html, /<h3>Mandag<\/h3>/);
  assert.match(html, /<h4>Lekser<\/h4>/);
  assert.match(html, /<h5 class="week-plan-heading">Norsk<\/h5>/);
  assert.match(html, /<h5 class="week-plan-heading">Matematikk<\/h5>/);
  assert.match(html, /Ta med \/ husk/);
  assert.match(html, /Dette må gjøres denne uken/);
  assert.match(html, /<h4 class="week-plan-heading">Engelsk<\/h4>/);
  assert.match(html, /Generell informasjon/);
  assert.match(html, /Foreldremøte torsdag/);
  assert.ok(html.indexOf("Gymtøy") < html.indexOf("Les én gang til"));
  assert.equal(JSON.stringify(interpretation), before);
  for (const phrase of ["Les side 12.", "Regn oppgave 4.", "Gymtøy og vannflaske.", "Les én gang til."]) {
    assert.equal(html.split(phrase).length - 1, 1);
  }
});

test("empty interpretation remains honest and current general information takes precedence", () => {
  const interpretation = { version: 1, week: 46, year: 2026, days: [] };
  assert.match(renderToStaticMarkup(createElement(WeekPlanInterpreted, { interpretation })), /Ingen strukturerte punkter/);
  interpretation.general_info = [{ text: "Aktuell beskjed" }];
  interpretation.general_notes = [{ text: "Gammel beskjed" }];
  const html = renderToStaticMarkup(createElement(WeekPlanInterpreted, { interpretation }));
  assert.match(html, /Aktuell beskjed/);
  assert.doesNotMatch(html, /Gammel beskjed/);
});

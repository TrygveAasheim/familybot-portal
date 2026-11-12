// Optional local browser gate; use only scripts/preview-ukeplan-document.mjs.
// Playwright is a test tool, not a production dependency. Pass its module path
// as argv[2] if it isn't installed in this checkout.
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const { webkit } = await import(process.argv[2] ? pathToFileURL(process.argv[2]).href : "playwright");
const browser = await webkit.launch({ headless: true });
const output = await mkdtemp(join(tmpdir(), "familybot-pdf-browser-"));
const origin = "http://127.0.0.1:43127";
const errors = [];
const external = [];
try {
  const context = await browser.newContext({ viewport: { width: 768, height: 1024 }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  context.on("request", request => { if (!request.url().startsWith(origin) && !request.url().startsWith("blob:")) external.push(request.url()); });
  const ready = async () => {
    await page.locator("canvas:not([hidden])").waitFor();
    assert.equal(await page.getByRole("alert").count(), 0);
  };
  await page.goto(origin);
  await ready();
  assert.match(await page.locator("body").innerText(), /Side 1 av 2/);
  const canvas = page.locator("canvas");
  const initial = await canvas.boundingBox();
  assert.ok(initial.width > 600);
  await page.screenshot({ path: join(output, "tablet-page-1.png"), fullPage: true });
  await page.getByRole("button", { name: "Neste side →" }).click();
  await ready();
  await page.getByText("Lesbar tekst for denne siden").click();
  assert.match(await page.locator(".document-readable-text").innerText(), /house.*hus.*book.*bok/);
  await page.screenshot({ path: join(output, "tablet-page-2.png"), fullPage: true });
  await page.getByRole("button", { name: "Zoom inn", exact: true }).click();
  await ready();
  assert.ok((await canvas.boundingBox()).width > initial.width);
  await page.getByRole("button", { name: "Tilpass bredde" }).click();
  await ready();
  assert.ok(Math.abs((await canvas.boundingBox()).width - initial.width) < 2);
  // Rapid changes exercise cancellation and React StrictMode setup/cleanup.
  for (let count = 0; count < 3; count++) {
    await page.getByRole("button", { name: "Plan B", exact: true }).click();
    await page.getByRole("button", { name: "Plan A", exact: true }).click();
  }
  await page.getByRole("button", { name: "Plan B", exact: true }).click();
  await ready();
  assert.match(await page.locator(".document-readable-text").textContent(), /Annen fiktiv plan/);
  await page.setViewportSize({ width: 390, height: 844 });
  await ready();
  await page.waitForFunction(() => document.querySelector("canvas").getBoundingClientRect().width < 390);
  await ready();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.screenshot({ path: join(output, "phone-page.png"), fullPage: true });
  for (const name of ["Mangler", "Ugyldig"]) {
    await page.getByRole("button", { name, exact: true }).click();
    await page.getByRole("alert").waitFor();
    assert.equal(await page.locator("canvas:not([hidden])").count(), 0);
    const disclosure = page.locator("main > details");
    if (!await disclosure.getAttribute("open").then(value => value !== null)) {
      await page.getByText("Tekst fra ukeplanen", { exact: true }).click();
    }
    assert.match(await page.locator("body").innerText(), /Norsk: Les side 12/);
  }
  await page.getByRole("button", { name: "Tilbake", exact: true }).click();
  assert.equal(await page.locator("canvas").count(), 0);
  assert.equal(context.pages().length, 1, "No popups");
  assert.deepEqual(errors, [], "No uncaught browser errors");
  assert.deepEqual(external, [], "No external document/asset requests");
  console.log(`PASS: WebKit page navigation, zoom/fit, switch/cancel, 768/390px, errors/fallback, back, no popups/external requests. Screenshots: ${output}`);
} finally {
  await browser.close();
}

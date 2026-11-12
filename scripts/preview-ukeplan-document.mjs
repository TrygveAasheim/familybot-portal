// Local-only, fictional browser fixture. Does not start Core/API or read config.
import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import { fictionalPlan } from "../tests/fixtures/ukeplan-pdf.mjs";
await import("./prepare-pdf-assets.mjs");
const root = new URL("../", import.meta.url).pathname;
const fixture = { name: "fictional-plan", configureServer(server) {
server.middlewares.use(async (req, res, next) => {
  if (req.url?.startsWith("/__fixture__/")) {
    const valid = req.headers["x-familybot-local-token"] === "fictional-session";
    const missing = req.url === "/__fixture__/missing.pdf";
    const body = req.url === "/__fixture__/broken.pdf" ? Buffer.from("%PDF-1.4\nbroken") :
      fictionalPlan(req.url === "/__fixture__/other.pdf" ? "Annen fiktiv plan" : "Fiktiv ukeplan");
    res.writeHead(!valid ? 403 : missing ? 404 : 200, {
      "Content-Type": "application/pdf", "Cache-Control": "no-store",
    });
    res.end(valid && !missing ? body : "Unavailable");
  } else if (req.url === "/") {
    res.setHeader("Content-Type", "text/html");
    res.end(await server.transformIndexHtml("/", '<!doctype html><html lang="nb"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Fictional Ukeplan test</title><div id="root"></div><script type="module" src="/tests/fixtures/document-viewer.tsx"></script></html>'));
  } else next();
});
} };
const server = await createServer({ root, configFile: false, plugins: [react(), fixture],
  server: { host: "127.0.0.1", port: 43127, strictPort: true } });
await server.listen();
console.log("Fictional PDF viewer: http://127.0.0.1:43127 (Ctrl-C to stop)");

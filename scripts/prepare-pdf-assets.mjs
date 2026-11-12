// Local, pinned PDF.js resources. No CDN or document upload at runtime.
import { cp, mkdir } from "node:fs/promises";
const root = new URL("../", import.meta.url);
await mkdir(new URL("public/pdf-assets/", root), { recursive: true });
await cp(new URL("node_modules/pdfjs-dist/LICENSE", root), new URL("public/pdf-assets/LICENSE", root));
for (const name of ["cmaps", "standard_fonts", "wasm"]) {
  const target = new URL(`public/pdf-assets/${name}/`, root);
  await mkdir(target, { recursive: true });
  await cp(new URL(`node_modules/pdfjs-dist/${name}/`, root), target, { recursive: true });
}

"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy, PDFDocumentLoadingTask } from "pdfjs-dist";

const MAX_BYTES = 15 * 1024 * 1024;
const MAX_PAGES = 20;

/** Passive rendering only: no PDF actions, forms, attachments or annotation links. */
export function WeekPlanDocument({ url, token }: { url: string; token: string }) {
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [width, setWidth] = useState(640);
  const [error, setError] = useState("");
  const [rendering, setRendering] = useState(true);
  const [pageText, setPageText] = useState("");
  const container = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(entries => setWidth(Math.max(240, entries[0].contentRect.width - 24)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    let task: PDFDocumentLoadingTask | undefined;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      controller.abort();
      void task?.destroy();
      if (!cancelled) setError("Dokumentet brukte for lang tid på å åpne. Gå tilbake og prøv igjen.");
    }, 30_000);
    // eslint-disable-next-line react/set-state-in-effect -- reset the external document resource when its identity/session changes
    setDocument(null); setError(""); setPage(1); setZoom(1); setRendering(true);
    void (async () => {
      const response = await fetch(url, { headers: { "X-FamilyBot-Local-Token": token }, cache: "no-store", signal: controller.signal });
      if (!response.ok || !response.headers.get("Content-Type")?.startsWith("application/pdf")) throw new Error("unavailable");
      if (Number(response.headers.get("Content-Length")) > MAX_BYTES) throw new Error("oversized");
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (cancelled) return;
      if (bytes.byteLength > MAX_BYTES) throw new Error("oversized");
      const pdf = await import("pdfjs-dist/legacy/build/pdf.mjs");
      const worker = await import("pdfjs-dist/legacy/build/pdf.worker.min.mjs?url");
      if (cancelled || controller.signal.aborted) return;
      pdf.GlobalWorkerOptions.workerSrc = worker.default;
      const assets = `${window.location.origin}/pdf-assets/`;
      task = pdf.getDocument({ data: bytes, enableXfa: false, stopAtErrors: true,
        maxImageSize: 16_000_000, canvasMaxAreaInBytes: 32_000_000,
        cMapUrl: `${assets}cmaps/`, cMapPacked: true,
        standardFontDataUrl: `${assets}standard_fonts/`, wasmUrl: `${assets}wasm/`,
      });
      const loaded = await task.promise;
      if (loaded.numPages < 1 || loaded.numPages > MAX_PAGES) throw new Error("page limit");
      if (!cancelled) setDocument(loaded);
    })().catch(() => {
      void task?.destroy();
      if (!cancelled) setError("Originaldokumentet kunne ikke vises. Lagret tekst finnes under «Tekst fra ukeplanen».");
    }).finally(() => window.clearTimeout(timer));
    return () => { cancelled = true; controller.abort(); window.clearTimeout(timer); void task?.destroy(); };
  }, [url, token]);

  useEffect(() => {
    if (!document || !canvas.current) return;
    let cancelled = false;
    let cancelRender: (() => void) | undefined;
    const target = canvas.current;
    setRendering(true); setPageText(""); setError("");
    const timer = window.setTimeout(() => {
      cancelled = true; cancelRender?.(); setError("Siden kunne ikke tegnes innen tidsgrensen.");
    }, 20_000);
    void (async () => {
      const source = await document.getPage(page);
      if (cancelled) return;
      const base = source.getViewport({ scale: 1 });
      const scale = Math.min(width, 1400) / base.width * zoom;
      const viewport = source.getViewport({ scale });
      if (!Number.isFinite(viewport.width * viewport.height) || viewport.width * viewport.height > 12_000_000) throw new Error("canvas limit");
      const ratio = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(12_000_000 / (viewport.width * viewport.height)));
      target.width = Math.ceil(viewport.width * ratio); target.height = Math.ceil(viewport.height * ratio);
      target.style.width = `${viewport.width}px`; target.style.height = `${viewport.height}px`;
      const context = target.getContext("2d");
      if (!context) throw new Error("canvas unavailable");
      const render = source.render({ canvas: target, canvasContext: context, viewport,
        transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] });
      cancelRender = () => render.cancel();
      await render.promise;
      if (cancelled) return;
      setRendering(false);
      window.clearTimeout(timer);
      // Optional text extraction must never hide an already rendered page.
      void source.getTextContent().then(text => {
        if (!cancelled) setPageText(text.items.map(item => "str" in item ? item.str : "").join(" ").slice(0, 50_000));
      }).catch(() => { /* Scanned/unsupported text can still have a valid visual page. */ });
    })().catch(() => { if (!cancelled) setError("Denne PDF-siden kunne ikke vises. Lagret tekst er fortsatt tilgjengelig nedenfor."); })
      .finally(() => window.clearTimeout(timer));
    return () => { cancelled = true; cancelRender?.(); window.clearTimeout(timer); };
  }, [document, page, width, zoom]);

  return <section className="week-plan-document" aria-label="Original ukeplan">
    <div className="document-controls" aria-label="Dokumentkontroller">
      <button type="button" disabled={!document || page <= 1} onClick={() => setPage(value => value - 1)}>← Forrige side</button>
      <span role="status">{error ? "Dokument utilgjengelig" : document ? `Side ${page} av ${document.numPages}` : "Åpner dokument …"}</span>
      <button type="button" disabled={!document || page >= document.numPages} onClick={() => setPage(value => value + 1)}>Neste side →</button>
      <button type="button" aria-label="Zoom ut" disabled={!document || zoom <= 1} onClick={() => setZoom(value => Math.max(1, value - .25))}>−</button>
      <button type="button" disabled={!document} onClick={() => setZoom(1)}>Tilpass bredde</button>
      <button type="button" aria-label="Zoom inn" disabled={!document || zoom >= 2.5} onClick={() => setZoom(value => Math.min(2.5, value + .25))}>+</button>
    </div>
    {error && <p role="alert" className="error-text">{error}</p>}
    {!error && rendering && <p role="status">Laster side …</p>}
    {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- keyboard users need to scroll the zoomed document region */}
    <div className="document-page-scroll" ref={container} tabIndex={0} role="region" aria-label="Dokumentside – rull for å se hele siden">
      <canvas ref={canvas} hidden={Boolean(error) || rendering} role="img" aria-label={`Original ukeplan, side ${page}`} />
    </div>
    {pageText && <details className="document-readable-text"><summary>Lesbar tekst for denne siden</summary><p>{pageText}</p></details>}
    <p className="parent-help">Originaldokumentet vises uendret. Uke og barn følger registreringen over, selv om skolen har gjenbrukt en gammel overskrift. Lenker og skjemaer i PDF-en er ikke aktive i denne visningen.</p>
  </section>;
}

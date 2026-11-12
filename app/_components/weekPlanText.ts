/** Presentation only: recognize explicit labels, never infer subjects or dates. */
export type PlanBlock =
  | { kind: "heading"; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; start?: number; items: string[] };

const labels = [
  "Norsk", "Matematikk", "Matte", "Engelsk", "Naturfag", "Samfunnsfag", "KRLE",
  "Kroppsøving", "Gym", "Musikk", "Kunst og håndverk", "Mat og helse",
  "Lesing", "Skriving", "Regning", "Læringsmål", "Mål for uken", "Mål for veka",
  "Ukens ord", "Ukas ord", "Vekas ord", "Gloser", "Lekser", "Lekser denne uken",
  "Hjemmearbeid", "Heimearbeid", "Husk", "Hugs", "Ta med", "Beskjeder",
  "Meldinger", "Meldingar", "Informasjon", "Generell informasjon", "Dette skjer",
  "Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag",
  "Måndag", "Tysdag", "Laurdag", "Sundag",
];
const labelPattern = [...labels].sort((a, b) => b.length - a.length).join("|");
const inlineLabels = [...new Set(labels.flatMap(label => [label, label.toUpperCase()]))]
  .sort((a, b) => b.length - a.length).join("|");
const labelledLine = new RegExp(`^(${labelPattern})\\s*:\\s*(.*)$`, "i");
const bareLabel = new RegExp(`^(?:${labelPattern})$`, "i");
const inlineLabel = new RegExp(`([^\\S\\n]+)(?=(?:${inlineLabels})\\s*:)`, "g");
const bullet = /^(?:([-–—*•·▪◦‣])|(\d+[.)])|([A-Za-zÆØÅæøå][.)]))\s+(.+)$/;

function isHeading(line: string) {
  return line.length <= 100 && (bareLabel.test(line) || /:$/.test(line)
    || /^(?:ukeplan|uke\s+\d+)\b/i.test(line)
    || /^[A-ZÆØÅ0-9][A-ZÆØÅ0-9\s–—-]{3,}$/.test(line));
}

export function weekPlanBlocks(text: string): PlanBlock[] {
  // Lowercase subject mentions in ordinary prose are deliberately not split.
  const lines = text.replace(/\r\n?/g, "\n").split("\n").flatMap(line => {
    // Preserve list markers/numbers rather than mistaking their labels for headings.
    if (bullet.test(line.trim())) return [line.trim()];
    return line.replace(inlineLabel, "\n").split("\n").map(part => part.trim());
  });
  const blocks: PlanBlock[] = [];
  let separate = true;
  for (const line of lines) {
    if (!line) { separate = true; continue; }
    const match = line.match(bullet);
    if (match) {
      const ordered = Boolean(match[2]);
      const start = ordered ? Number.parseInt(match[2], 10) : undefined;
      const previous = blocks.at(-1);
      if (!separate && previous?.kind === "list" && previous.ordered === ordered
          && (!ordered || start === (previous.start ?? 1) + previous.items.length)) previous.items.push(match[4]);
      else blocks.push({ kind: "list", ordered, ...(ordered ? { start } : {}), items: [match[4]] });
      separate = false;
      continue;
    }
    const labelled = line.match(labelledLine);
    if (labelled) {
      blocks.push({ kind: "heading", text: labelled[1] });
      if (labelled[2]) blocks.push({ kind: "paragraph", text: labelled[2] });
    } else if (isHeading(line)) {
      blocks.push({ kind: "heading", text: line.replace(/:$/, "") });
    } else {
      const previous = blocks.at(-1);
      if (!separate && previous?.kind === "paragraph") previous.text += `\n${line}`;
      else blocks.push({ kind: "paragraph", text: line });
    }
    separate = false;
  }
  return blocks;
}

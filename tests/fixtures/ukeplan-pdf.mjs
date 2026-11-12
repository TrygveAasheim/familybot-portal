// Entirely fictional, deterministic two-page PDF; no school/household data.
// Minimal PDF writer keeps the visual fixture dependency-free.
export function fictionalPlan(label = "Fiktiv ukeplan") {
  const literal = value => value.replaceAll("\\", "\\\\").replaceAll("(", "\\(").replaceAll(")", "\\)");
  const text = (x, y, size, value) => `BT /F1 ${size} Tf ${x} ${y} Td (${literal(value)}) Tj ET\n`;
  const content = [
    text(44, 790, 24, label) + text(44, 760, 12, "Eksempelskolen - uke 46 - kun testdata") +
    "0.85 0.95 0.92 rg 40 660 515 60 re f 0 0 0 rg\n" +
    text(52, 695, 16, "Mandag") + text(310, 695, 16, "Tirsdag") +
    "40 580 515 140 re S 295 580 m 295 720 l S\n" +
    text(52, 640, 14, "Norsk: Les side 12.") + text(310, 640, 14, "Matematikk: Regn 1-4.") +
    text(52, 610, 14, "Ta med lesebok.") + text(310, 610, 14, "Ta med blyant.") +
    text(44, 520, 18, "Beskjeder") + text(44, 490, 14, "Husk tursekk pa onsdag.") + text(44, 40, 12, "Side 1 av 2"),
    text(44, 790, 24, "Ord for uken") + text(44, 745, 16, "Engelsk") + text(310, 745, 16, "Norsk") +
    text(44, 705, 16, "house") + text(310, 705, 16, "hus") +
    text(44, 670, 16, "book") + text(310, 670, 16, "bok") +
    text(44, 40, 12, "Side 2 av 2"),
  ];
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [4 0 R 6 0 R] /Count 2 >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ...content.flatMap((stream, index) => [
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents ${5 + index * 2} 0 R >>`,
      `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}endstream`,
    ]),
  ];
  let body = "%PDF-1.4\n";
  const offsets = [0];
  for (const [index, value] of objects.entries()) {
    offsets.push(Buffer.byteLength(body));
    body += `${index + 1} 0 obj\n${value}\nendobj\n`;
  }
  const offset = Buffer.byteLength(body);
  body += `xref\n0 ${offsets.length}\n0000000000 65535 f \n`;
  body += offsets.slice(1).map(value => `${String(value).padStart(10, "0")} 00000 n \n`).join("");
  body += `trailer\n<< /Size ${offsets.length} /Root 1 0 R >>\nstartxref\n${offset}\n%%EOF\n`;
  return Buffer.from(body);
}

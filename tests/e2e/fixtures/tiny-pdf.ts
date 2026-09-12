function createPdf(): Buffer {
  const stream = "BT /F1 12 Tf 8 36 Td (Synthetic Alma E2E CV) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    [
      "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 216 72]",
      "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    ].join(" "),
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];

  let body = "%PDF-1.4\n";
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(body));
    body += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }

  const xrefOffset = Buffer.byteLength(body);
  const xref = [
    "xref",
    `0 ${objects.length + 1}`,
    "0000000000 65535 f ",
    ...offsets
      .slice(1)
      .map((offset) => `${String(offset).padStart(10, "0")} 00000 n `),
  ].join("\n");

  return Buffer.from(
    `${body}${xref}\ntrailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`,
  );
}

export const tinyPdf = {
  name: "synthetic-alma-e2e-cv.pdf",
  mimeType: "application/pdf",
  buffer: createPdf(),
} as const;

export const invalidTextFile = {
  name: "not-a-cv.txt",
  mimeType: "text/plain",
  buffer: Buffer.from("Synthetic invalid upload fixture.\n"),
} as const;

export function oversizedPdf(maxBytes: number) {
  const targetBytes = Math.max(maxBytes + 1, tinyPdf.buffer.byteLength + 1);
  return {
    name: "synthetic-oversized-cv.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.concat([
      tinyPdf.buffer,
      Buffer.alloc(targetBytes - tinyPdf.buffer.byteLength, 0x20),
    ]),
  };
}

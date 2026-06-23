import type { ResearchSession } from "@/lib/api";

type PdfLine = {
  text: string;
  font: "regular" | "bold";
  size: number;
  gapBefore?: number;
};

function safeFilePart(value: string): string {
  const cleaned = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return cleaned || "research-report";
}

function normalisePdfText(value: string): string {
  return value
    .replace(/[“”]/g, "\"")
    .replace(/[‘’]/g, "'")
    .replace(/[–—]/g, "-")
    .replace(/…/g, "...")
    .replace(/·/g, "*")
    .normalize("NFKD")
    .replace(/[^\x09\x0A\x0D\x20-\x7E]/g, "");
}

function escapePdfString(value: string): string {
  return normalisePdfText(value)
    .replace(/\\/g, "\\\\")
    .replace(/\(/g, "\\(")
    .replace(/\)/g, "\\)");
}

function formatSessionMarkdown(session: ResearchSession): string {
  const updatedAt = new Date(session.updated_at).toISOString();
  const citationList = session.citations
    .map((citation, index) => `${index + 1}. ${citation.title}\n   ${citation.url}`)
    .join("\n\n");
  const promptHistory = session.turns
    .map((turn, index) => `${index + 1}. ${turn.prompt}`)
    .join("\n");

  return [
    `# ${session.title}`,
    "",
    `Last updated: ${updatedAt}`,
    session.model ? `Model: ${session.model}` : "",
    `Web searches: ${session.web_search_requests}`,
    "",
    promptHistory ? "## Prompt history\n\n" + promptHistory : "",
    "",
    "---",
    "",
    session.report_markdown.trim(),
    citationList ? "\n---\n\n## Citation Index\n\n" + citationList : "",
    "",
  ]
    .filter((line) => line !== undefined)
    .join("\n");
}

function wrapText(text: string, size: number, maxWidth: number): string[] {
  const maxChars = Math.max(24, Math.floor(maxWidth / (size * 0.52)));
  const words = normalisePdfText(text).split(/\s+/).filter(Boolean);
  if (words.length === 0) return [""];

  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= maxChars) {
      current = candidate;
      continue;
    }
    if (current) lines.push(current);
    current = word.length > maxChars ? word.slice(0, maxChars) : word;
  }
  if (current) lines.push(current);
  return lines;
}

function markdownToPdfLines(markdown: string): PdfLine[] {
  const sourceLines = markdown.split(/\r?\n/);
  const pdfLines: PdfLine[] = [];

  for (const rawLine of sourceLines) {
    const line = rawLine.trimEnd();
    if (!line.trim() || line.trim() === "---") {
      pdfLines.push({ text: "", font: "regular", size: 10, gapBefore: 4 });
      continue;
    }

    if (line.startsWith("# ")) {
      pdfLines.push({ text: line.replace(/^#\s+/, ""), font: "bold", size: 18, gapBefore: 10 });
    } else if (line.startsWith("## ")) {
      pdfLines.push({ text: line.replace(/^##\s+/, ""), font: "bold", size: 14, gapBefore: 8 });
    } else if (line.startsWith("### ")) {
      pdfLines.push({ text: line.replace(/^###\s+/, ""), font: "bold", size: 12, gapBefore: 6 });
    } else {
      pdfLines.push({ text: line, font: "regular", size: 10 });
    }
  }

  return pdfLines;
}

function buildPdf(markdown: string): string {
  const pageWidth = 612;
  const pageHeight = 792;
  const marginX = 54;
  const marginTop = 54;
  const marginBottom = 54;
  const textWidth = pageWidth - marginX * 2;
  const topY = pageHeight - marginTop;
  const bottomY = marginBottom;
  const pages: string[] = [];
  let commands = "";
  let y = topY;

  const finishPage = () => {
    pages.push(commands);
    commands = "";
    y = topY;
  };

  for (const line of markdownToPdfLines(markdown)) {
    if (line.gapBefore) y -= line.gapBefore;

    const wrapped = line.text ? wrapText(line.text, line.size, textWidth) : [""];
    for (const wrappedLine of wrapped) {
      const lineHeight = Math.ceil(line.size * 1.45);
      if (y - lineHeight < bottomY) {
        finishPage();
      }
      if (wrappedLine) {
        const fontName = line.font === "bold" ? "F2" : "F1";
        commands += `BT /${fontName} ${line.size} Tf ${marginX} ${y} Td (${escapePdfString(wrappedLine)}) Tj ET\n`;
      }
      y -= lineHeight;
    }
  }
  if (commands || pages.length === 0) finishPage();

  const objects: string[] = [];
  objects[1] = "<< /Type /Catalog /Pages 2 0 R >>";
  objects[3] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>";
  objects[4] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>";

  const pageRefs: string[] = [];
  let nextId = 5;
  for (const pageContent of pages) {
    const pageId = nextId++;
    const contentId = nextId++;
    pageRefs.push(`${pageId} 0 R`);
    objects[pageId] = [
      "<< /Type /Page",
      "/Parent 2 0 R",
      `/MediaBox [0 0 ${pageWidth} ${pageHeight}]`,
      "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >>",
      `/Contents ${contentId} 0 R`,
      ">>",
    ].join(" ");
    objects[contentId] = `<< /Length ${pageContent.length} >>\nstream\n${pageContent}endstream`;
  }

  objects[2] = `<< /Type /Pages /Kids [${pageRefs.join(" ")}] /Count ${pages.length} >>`;

  let body = "%PDF-1.4\n";
  const offsets: number[] = [0];
  for (let id = 1; id < objects.length; id += 1) {
    offsets[id] = body.length;
    body += `${id} 0 obj\n${objects[id]}\nendobj\n`;
  }

  const xrefOffset = body.length;
  body += `xref\n0 ${objects.length}\n0000000000 65535 f \n`;
  for (let id = 1; id < objects.length; id += 1) {
    body += `${String(offsets[id]).padStart(10, "0")} 00000 n \n`;
  }
  body += `trailer << /Size ${objects.length} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;
  return body;
}

export function downloadResearchSessionReport(session: ResearchSession): void {
  const pdf = buildPdf(formatSessionMarkdown(session));
  const blob = new Blob([pdf], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${safeFilePart(session.title)}-research.pdf`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

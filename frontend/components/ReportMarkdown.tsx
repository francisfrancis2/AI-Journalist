import type { ReactNode } from "react";

// Lightweight Markdown renderer shared by the Research Tab and the script
// research dossier. Supports headings, bullet lists, paragraphs, and inline
// links — no external dependency.

export function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const linkRe = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = linkRe.exec(text)) !== null) {
    if (match.index > lastIndex) {
      out.push(<span key={`t-${key++}`}>{text.slice(lastIndex, match.index)}</span>);
    }
    out.push(
      <a
        key={`a-${key++}`}
        href={match[2]}
        target="_blank"
        rel="noopener noreferrer"
        style={{ color: "var(--color-action)", textDecoration: "underline", overflowWrap: "anywhere" }}
      >
        {match[1]}
      </a>
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    out.push(<span key={`t-${key++}`}>{text.slice(lastIndex)}</span>);
  }
  return out;
}

export function ReportMarkdown({ markdown }: { markdown: string }) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let listBuf: string[] = [];
  let paraBuf: string[] = [];

  const flushList = () => {
    if (listBuf.length === 0) return;
    blocks.push(
      <ul key={`ul-${blocks.length}`} style={{ paddingLeft: 20, margin: "8px 0", display: "flex", flexDirection: "column", gap: 4 }}>
        {listBuf.map((item, idx) => (
          <li key={idx} style={{ fontSize: 13, lineHeight: 1.7, color: "var(--color-text-primary)" }}>
            {renderInline(item)}
          </li>
        ))}
      </ul>
    );
    listBuf = [];
  };

  const flushPara = () => {
    if (paraBuf.length === 0) return;
    const text = paraBuf.join(" ");
    blocks.push(
      <p
        key={`p-${blocks.length}`}
        style={{ fontSize: 13, lineHeight: 1.75, margin: "6px 0", color: "var(--color-text-primary)" }}
      >
        {renderInline(text)}
      </p>
    );
    paraBuf = [];
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flushList();
      flushPara();
      continue;
    }
    if (line.startsWith("# ")) {
      flushList();
      flushPara();
      blocks.push(
        <h1 key={`h1-${blocks.length}`} style={{ fontSize: 20, fontWeight: 600, margin: "16px 0 8px" }}>
          {renderInline(line.slice(2))}
        </h1>
      );
      continue;
    }
    if (line.startsWith("## ")) {
      flushList();
      flushPara();
      blocks.push(
        <h2 key={`h2-${blocks.length}`} style={{ fontSize: 15, fontWeight: 600, margin: "14px 0 6px", color: "var(--color-text-primary)" }}>
          {renderInline(line.slice(3))}
        </h2>
      );
      continue;
    }
    if (line.startsWith("### ")) {
      flushList();
      flushPara();
      blocks.push(
        <h3 key={`h3-${blocks.length}`} style={{ fontSize: 13, fontWeight: 600, margin: "10px 0 4px", color: "var(--color-text-primary)" }}>
          {renderInline(line.slice(4))}
        </h3>
      );
      continue;
    }
    if (line.startsWith("- ") || line.startsWith("* ")) {
      flushPara();
      listBuf.push(line.slice(2));
      continue;
    }
    flushList();
    paraBuf.push(line);
  }
  flushList();
  flushPara();

  return <>{blocks}</>;
}

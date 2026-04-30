import type { FinalScript } from "@/lib/api";

type ExportSource = {
  title: string;
  url: string | null;
  credibility?: string | null;
  type?: string | null;
  author?: string | null;
  published_at?: string | null;
};

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatDuration(seconds: number): string {
  const safeSeconds = Math.max(0, Math.round(seconds));
  return `${Math.floor(safeSeconds / 60)}:${String(safeSeconds % 60).padStart(2, "0")}`;
}

function paragraphHtml(value: string): string {
  return escapeHtml(value).replace(/\n/g, "<br>");
}

function formatPublishedAt(value: string | null | undefined): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function openPrintPreview(title: string, html: string): boolean {
  const blob = new Blob([html], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  const win = window.open(url, "_blank");
  if (!win) {
    URL.revokeObjectURL(url);
    return false;
  }
  win.focus();
  setTimeout(() => {
    win.print();
    URL.revokeObjectURL(url);
  }, 400);
  return true;
}

export function downloadScriptPdf(script: FinalScript): boolean {
  const actsHtml = script.sections
    .map(
      (section) => `
    <div class="act">
      <h3>Act ${section.section_number}: ${escapeHtml(section.title)}
        <span class="dur">${formatDuration(section.estimated_seconds)}</span>
      </h3>
      <p>${paragraphHtml(section.narration)}</p>
    </div>`
    )
    .join("");

  const sourcesHtml = script.sources
    .map((source, index) => {
      const title = escapeHtml(source.title);
      const url = source.url ? escapeHtml(source.url) : "";
      const credibility = source.credibility?.toUpperCase() ?? "";
      const type = source.type ? escapeHtml(source.type.replace(/_/g, " ")) : "";
      return `<li>
        <div class="src-row">
          <span class="src-num">${index + 1}</span>
          <div>
            <div class="src-title">${url ? `<a href="${url}">${title}</a>` : title}${credibility ? ` <span class="src-cred src-cred-${source.credibility}">${credibility}</span>` : ""}</div>
            ${type ? `<div class="src-meta">${type}</div>` : ""}
            ${url ? `<div class="src-url">${url}</div>` : ""}
          </div>
        </div>
      </li>`;
    })
    .join("");

  const html = `<!DOCTYPE html><html><head><meta charset="utf-8">
<title>${escapeHtml(script.title)}</title>
<style>
  @page{margin:22mm 18mm}
  *{box-sizing:border-box}
  body{font-family:Georgia,"Times New Roman",serif;max-width:720px;margin:40px auto;color:#111;font-size:13px;line-height:1.8}
  h1{font-size:22px;line-height:1.25;margin:0 0 6px}
  .meta{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#777;margin-bottom:18px}
  .logline{font-style:italic;color:#555;margin-bottom:24px}
  .hook{background:#f4f4f8;border-left:3px solid #1c26a8;padding:12px 16px;margin-bottom:28px}
  .hook-label{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:#1c26a8;margin-bottom:6px;font-weight:bold}
  .act{margin-bottom:24px;break-inside:avoid;page-break-inside:avoid}
  .act h3{font-size:13px;font-weight:bold;border-bottom:1px solid #e0e0e0;padding-bottom:4px;margin-bottom:6px;display:flex;justify-content:space-between;gap:16px}
  .dur{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:11px;color:#888;font-weight:normal;white-space:nowrap}
  .closing{border-top:1px solid #ddd;padding-top:20px;margin-top:28px;break-inside:avoid;page-break-inside:avoid}
  .appendix-header{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:#1c26a8;font-weight:bold;margin:32px 0 12px;border-top:2px solid #1c26a8;padding-top:16px}
  ul.src{list-style:none;padding:0;margin:0}
  ul.src li{margin-bottom:10px;break-inside:avoid;page-break-inside:avoid}
  .src-row{display:flex;gap:10px;align-items:flex-start;background:#f7f7fb;border:1px solid #e4e4ec;border-radius:4px;padding:8px 10px}
  .src-num{flex-shrink:0;width:20px;height:20px;background:#e4e4ec;border-radius:3px;font-size:10px;font-weight:700;color:#555;display:flex;align-items:center;justify-content:center;margin-top:1px}
  .src-title{font-size:12px;font-weight:600;color:#111;line-height:1.4;margin-bottom:2px}
  .src-cred{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;padding:1px 4px;border-radius:2px;vertical-align:middle;margin-left:4px}
  .src-cred-high{color:#15803d;border:1px solid #15803d}
  .src-cred-medium{color:#b45309;border:1px solid #b45309}
  .src-cred-low{color:#b91c1c;border:1px solid #b91c1c}
  .src-meta{font-size:10px;color:#777;text-transform:capitalize;margin-bottom:1px}
  .src-url{font-size:10px;color:#1c26a8;word-break:break-all;line-height:1.4}
  a{color:#1c26a8}
  @media print{body{margin:0;max-width:none}.no-print{display:none}}
</style></head><body>
<h1>${escapeHtml(script.title)}</h1>
<div class="meta">${script.total_word_count.toLocaleString()} words &middot; ~${script.estimated_duration_minutes} min &middot; ${script.sections.length} acts</div>
<p class="logline">"${escapeHtml(script.logline)}"</p>
<div class="hook"><div class="hook-label">Opening Hook</div><p>${paragraphHtml(script.opening_hook)}</p></div>
${actsHtml}
<div class="closing"><h3>Closing Statement</h3><p>${paragraphHtml(script.closing_statement)}</p></div>
<div class="appendix-header">Appendix: Sources (${script.sources.length})</div>
<ul class="src">${sourcesHtml}</ul>
</body></html>`;

  return openPrintPreview(script.title, html);
}

export function downloadSourceListPdf(title: string, sources: ExportSource[]): boolean {
  const rowsHtml = sources
    .map((source, index) => {
      const sourceTitle = escapeHtml(source.title);
      const sourceUrl = source.url ? escapeHtml(source.url) : "";
      const sourceType = source.type ? escapeHtml(source.type.replace(/_/g, " ")) : "";
      const credibility = source.credibility ? escapeHtml(source.credibility.toUpperCase()) : "";
      const author = source.author ? escapeHtml(source.author) : "";
      const publishedAt = source.published_at ? escapeHtml(formatPublishedAt(source.published_at)) : "";
      return `<tr>
        <td>${index + 1}</td>
        <td>${sourceTitle}</td>
        <td>${sourceUrl ? `<a href="${sourceUrl}">${sourceUrl}</a>` : "&mdash;"}</td>
        <td>${sourceType || "&mdash;"}</td>
        <td>${credibility || "&mdash;"}</td>
        <td>${author || "&mdash;"}</td>
        <td>${publishedAt || "&mdash;"}</td>
      </tr>`;
    })
    .join("");

  const html = `<!DOCTYPE html><html><head><meta charset="utf-8">
<title>${escapeHtml(title)} — Source List</title>
<style>
  @page{margin:18mm 14mm}
  *{box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#111;margin:32px auto;max-width:920px;font-size:12px;line-height:1.5}
  h1{font-size:22px;line-height:1.2;margin:0 0 6px}
  .meta{font-size:11px;color:#666;margin-bottom:18px}
  table{width:100%;border-collapse:collapse;table-layout:fixed}
  th,td{border:1px solid #d9dce5;padding:8px 10px;vertical-align:top;text-align:left}
  th{background:#f4f6fb;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#4b5563}
  td{font-size:11px;word-break:break-word}
  th:nth-child(1),td:nth-child(1){width:42px;text-align:center}
  th:nth-child(2),td:nth-child(2){width:21%}
  th:nth-child(4),td:nth-child(4){width:13%}
  th:nth-child(5),td:nth-child(5){width:11%}
  th:nth-child(6),td:nth-child(6){width:14%}
  th:nth-child(7),td:nth-child(7){width:13%}
  a{color:#1c26a8;text-decoration:none}
  a:hover{text-decoration:underline}
  @media print{body{margin:0;max-width:none}}
</style></head><body>
<h1>${escapeHtml(title)}</h1>
<div class="meta">Source list export · ${sources.length} linked sources</div>
<table>
  <thead>
    <tr>
      <th>#</th>
      <th>Source</th>
      <th>Link</th>
      <th>Type</th>
      <th>Credibility</th>
      <th>Author</th>
      <th>Published</th>
    </tr>
  </thead>
  <tbody>${rowsHtml}</tbody>
</table>
</body></html>`;

  return openPrintPreview(`${title} - Source List`, html);
}

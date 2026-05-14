function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
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

export function downloadAgentManualMarkdown(markdown: string): void {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "ai-journalist-agent-operating-manual.md";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function downloadAgentManualPdf(markdown: string): boolean {
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8">
<title>AI Journalist Agent Operating Manual</title>
<style>
  @page{margin:16mm 14mm}
  *{box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#111;margin:28px auto;max-width:980px;font-size:12px;line-height:1.55}
  h1{font-size:22px;margin:0 0 10px}
  .meta{font-size:10px;color:#666;margin-bottom:18px;text-transform:uppercase;letter-spacing:.08em}
  pre{white-space:pre-wrap;word-break:break-word;font-family:"SFMono-Regular",Consolas,"Liberation Mono",monospace;font-size:10px;line-height:1.55;background:#f7f7fb;border:1px solid #e4e4ec;border-radius:6px;padding:14px}
  @media print{body{margin:0;max-width:none}pre{border:none;background:#fff;padding:0}}
</style></head><body>
<h1>AI Journalist Agent Operating Manual</h1>
<div class="meta">Markdown source rendered for PDF export</div>
<pre>${escapeHtml(markdown)}</pre>
</body></html>`;

  return openPrintPreview("AI Journalist Agent Operating Manual", html);
}

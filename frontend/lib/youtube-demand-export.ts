import { buildPdf, downloadPdfBody, safeFilePart } from "@/lib/research-report-export";
import type { YouTubeDemandReport } from "@/lib/api";

function formatViews(value: number): string {
  return value.toLocaleString("en-US");
}

/** Render the demand report as markdown, then reuse the shared PDF builder. */
export function youTubeDemandMarkdown(report: YouTubeDemandReport): string {
  const lines: string[] = [];
  lines.push(`# YouTube Research and Analysis`);
  lines.push(`## ${report.topic}`);
  lines.push("");
  lines.push(`Source: vidIQ. Subject searched: ${report.search_seed}.`);
  if (report.seed_keyword) {
    const s = report.seed_keyword;
    lines.push(
      `Seed demand: ${formatViews(s.estimated_monthly_search)} searches/month ` +
        `(volume ${Math.round(s.volume)}/100, competition ${
          s.competition === null || s.competition === undefined ? "n/a" : Math.round(s.competition)
        }/100).`
    );
  }
  lines.push("");

  if (report.keywords.length > 0) {
    lines.push("### 1. Top keywords and phrases by search volume");
    lines.push("");
    for (const k of report.keywords) {
      const comp =
        k.competition === null || k.competition === undefined ? "n/a" : Math.round(k.competition);
      lines.push(
        `- ${k.keyword} - ${k.monthly_display || formatViews(k.estimated_monthly_search)} searches/mo ` +
          `| volume ${Math.round(k.volume)}/100 | competition ${comp}/100 | ${k.label}`
      );
    }
    lines.push("");
  }

  if (report.videos.length > 0) {
    lines.push("### 2. Top long-form videos for these keywords");
    lines.push("");
    report.videos.forEach((v, index) => {
      lines.push(`${index + 1}. ${v.title}`);
      lines.push(
        `   ${v.channel || "Unknown channel"} | ${v.duration_display} | ${formatViews(
          v.view_count
        )} views${v.published_at ? ` | ${v.published_at}` : ""}`
      );
      lines.push(`   ${v.url}`);
      lines.push("");
    });
  }

  lines.push("### Method and caveats");
  lines.push("");
  lines.push("- Keyword metrics from vidIQ; videos matched on relevance then ranked by views.");
  lines.push("- Views are lifetime totals, not recent momentum.");
  lines.push("- Titles were screened against a topic vocabulary derived from vidIQ keywords.");
  lines.push("- YouTube exposes no documentary genre filter; long-form is a duration proxy.");
  lines.push("- Search volumes are vidIQ estimates, not YouTube-published figures.");
  return lines.join("\n");
}

export function downloadYouTubeDemandReport(report: YouTubeDemandReport): void {
  const pdf = buildPdf(youTubeDemandMarkdown(report));
  downloadPdfBody(pdf, `${safeFilePart(report.topic)}-youtube-research.pdf`);
}

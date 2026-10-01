"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Download, ExternalLink, Loader2, Youtube } from "lucide-react";

import type { YouTubeDemandReport } from "@/lib/api";
import { downloadYouTubeDemandReport } from "@/lib/youtube-demand-export";

type Notice = { tone: "success" | "error"; text: string };

function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

function compact(value: number): string {
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value);
}

/**
 * "YouTube Research and Analysis" — keyword demand plus top long-form videos.
 *
 * Used in two places with the same contract: the Research Hub (as its own window)
 * and the script workspace sidebar (alongside Research signals).
 */
export function YouTubeResearchPanel({
  report,
  variant = "panel",
}: {
  report: YouTubeDemandReport | null | undefined;
  variant?: "panel" | "window";
}) {
  const [expandedKeywords, setExpandedKeywords] = useState(false);
  const [expandedVideos, setExpandedVideos] = useState(variant === "window");
  const [downloading, setDownloading] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const maxMonthly = useMemo(
    () => Math.max(1, ...(report?.keywords ?? []).map((k) => k.estimated_monthly_search)),
    [report]
  );

  if (!report || (report.keywords.length === 0 && report.videos.length === 0)) {
    return (
      <section className="card" style={{ padding: 16 }}>
        <p className="section-label" style={{ marginBottom: 4 }}>YouTube research and analysis</p>
        <p style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
          No YouTube demand data for this story. It is gathered during research when vidIQ is
          configured and available.
        </p>
      </section>
    );
  }

  const keywords = expandedKeywords ? report.keywords : report.keywords.slice(0, 6);
  const videos = expandedVideos ? report.videos : report.videos.slice(0, 3);

  const handleDownload = () => {
    setDownloading(true);
    try {
      downloadYouTubeDemandReport(report);
      setNotice({ tone: "success", text: "Downloaded the YouTube research PDF." });
    } catch {
      setNotice({ tone: "error", text: "Could not build the PDF. Please try again." });
    } finally {
      setDownloading(false);
    }
  };

  return (
    <section
      className="card"
      style={{
        padding: variant === "window" ? "20px 24px" : 16,
        display: "flex",
        flexDirection: "column",
        gap: 12,
        maxHeight: variant === "panel" ? 560 : undefined,
        overflowY: variant === "panel" ? "auto" : undefined,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
        <div>
          <p className="section-label" style={{ marginBottom: 3, display: "flex", alignItems: "center", gap: 6 }}>
            <Youtube size={13} style={{ color: "var(--color-action)" }} />
            YouTube research and analysis
          </p>
          <p style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {report.keywords.length} keywords · {report.videos.length} videos · searched
            {" "}&ldquo;{report.search_seed}&rdquo;
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary"
          onClick={handleDownload}
          disabled={downloading}
          style={{ padding: "5px 9px", fontSize: 11, flexShrink: 0 }}
        >
          {downloading ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
          Download PDF
        </button>
      </div>

      {notice && (
        <p style={{ fontSize: 11, color: notice.tone === "success" ? "var(--color-success, #1baf7a)" : "var(--color-danger, #e34948)" }}>
          {notice.text}
        </p>
      )}

      {report.seed_keyword && (
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 11, color: "var(--color-text-secondary)" }}>
          <span><b style={{ color: "var(--color-text-primary)" }}>{formatCount(report.seed_keyword.estimated_monthly_search)}</b> searches/mo</span>
          <span>volume <b style={{ color: "var(--color-text-primary)" }}>{Math.round(report.seed_keyword.volume)}</b>/100</span>
          {report.seed_keyword.competition !== null && report.seed_keyword.competition !== undefined && (
            <span>competition <b style={{ color: "var(--color-text-primary)" }}>{Math.round(report.seed_keyword.competition)}</b>/100</span>
          )}
          <span><b style={{ color: "var(--color-text-primary)" }}>{compact(report.videos.reduce((sum, v) => sum + v.view_count, 0))}</b> combined views</span>
        </div>
      )}

      {/* ── Keywords ── */}
      {report.keywords.length > 0 && (
        <div>
          <p style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-tertiary)", marginBottom: 6 }}>
            Top keywords by search volume
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            {keywords.map((kw) => (
              <div key={kw.keyword} style={{ display: "grid", gridTemplateColumns: "1fr 58px 44px", gap: 8, alignItems: "center", fontSize: 11 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{kw.keyword}</div>
                  <div style={{ height: 4, background: "var(--color-border, #e9eef6)", borderRadius: 3, marginTop: 3, overflow: "hidden" }}>
                    <span
                      style={{
                        display: "block",
                        height: "100%",
                        width: `${Math.max(2, (kw.estimated_monthly_search / maxMonthly) * 100)}%`,
                        background: "var(--color-action)",
                        borderRadius: 3,
                      }}
                    />
                  </div>
                </div>
                <span style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
                  {kw.monthly_display || formatCount(kw.estimated_monthly_search)}
                </span>
                <span style={{ textAlign: "right", color: "var(--color-text-tertiary)", fontVariantNumeric: "tabular-nums" }}>
                  {kw.competition === null || kw.competition === undefined ? "—" : Math.round(kw.competition)}
                </span>
              </div>
            ))}
          </div>
          {report.keywords.length > 6 && (
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setExpandedKeywords((v) => !v)}
              aria-expanded={expandedKeywords}
              style={{ padding: "4px 0", fontSize: 11, marginTop: 4 }}
            >
              <ChevronDown size={12} style={{ transform: expandedKeywords ? "rotate(180deg)" : "none", transition: "transform 0.12s ease" }} />
              {expandedKeywords ? "Show fewer" : `Show all ${report.keywords.length}`}
            </button>
          )}
        </div>
      )}

      {/* ── Videos ── */}
      {report.videos.length > 0 && (
        <div>
          <p style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-tertiary)", marginBottom: 6 }}>
            Top long-form videos
          </p>
          <ol style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
            {videos.map((video, index) => (
              <li key={video.video_id} style={{ display: "flex", gap: 8, fontSize: 11 }}>
                <span style={{ color: "var(--color-text-tertiary)", fontVariantNumeric: "tabular-nums", minWidth: 14 }}>
                  {index + 1}
                </span>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <a
                    href={video.url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: "var(--color-text-primary)", fontWeight: 600, textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 4 }}
                  >
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{video.title}</span>
                    <ExternalLink size={10} style={{ flexShrink: 0, color: "var(--color-text-tertiary)" }} />
                  </a>
                  <div style={{ color: "var(--color-text-tertiary)", marginTop: 1 }}>
                    {video.channel || "Unknown"} · {video.duration_display} · {formatCount(video.view_count)} views
                  </div>
                </div>
              </li>
            ))}
          </ol>
          {report.videos.length > 3 && (
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setExpandedVideos((v) => !v)}
              aria-expanded={expandedVideos}
              style={{ padding: "4px 0", fontSize: 11, marginTop: 4 }}
            >
              <ChevronDown size={12} style={{ transform: expandedVideos ? "rotate(180deg)" : "none", transition: "transform 0.12s ease" }} />
              {expandedVideos ? "Show fewer" : `Show all ${report.videos.length}`}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

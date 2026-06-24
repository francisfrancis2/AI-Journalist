"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { Loader2, ArrowLeft, Download, CheckCircle2, XCircle, ChevronDown, ChevronUp, AlertTriangle, X } from "lucide-react";
import { apiClient, type Story, type FinalScript, type ResearchSource } from "@/lib/api";
import { getUserInfo } from "@/lib/auth";
import { downloadScriptPdf, downloadSourceListPdf } from "@/lib/script-export";
import {
  ANGLE_SELECTION_STOPPED_MESSAGE,
  isAngleSelectionExpired,
  isTerminalStoryStatus,
  storyStatusLabel,
  storyStatusTitle,
} from "@/lib/story-status";

type Tab = "script";
const TOP_RESEARCH_SOURCES_LIMIT = 10;

type DisplaySource = {
  source_id?: string | null;
  title: string;
  url: string | null;
  credibility: string;
  type: string;
  author?: string | null;
  published_at?: string | null;
  relevance_score?: number;
};
type ExportNotice = {
  tone: "success" | "error";
  text: string;
};

function sourceKey(source: Pick<DisplaySource, "source_id" | "url" | "title">): string {
  return source.source_id || source.url || source.title.trim().toLowerCase();
}

function buildSourceLookup(
  scriptSources: FinalScript["sources"],
  researchSources: ResearchSource[]
): Map<string, DisplaySource> {
  const lookup = new Map<string, DisplaySource>();

  for (const source of researchSources) {
    lookup.set(sourceKey(source), {
      source_id: source.source_id ?? null,
      title: source.title,
      url: source.url,
      credibility: source.credibility,
      type: source.source_type,
      author: source.author,
      published_at: source.published_at,
      relevance_score: source.relevance_score,
    });
  }

  for (const source of scriptSources) {
    const key = sourceKey(source);
    const existing = lookup.get(key);
    lookup.set(key, {
      source_id: source.source_id ?? existing?.source_id ?? null,
      title: source.title,
      url: source.url ?? existing?.url ?? null,
      credibility: source.credibility ?? existing?.credibility ?? "medium",
      type: source.type ?? existing?.type ?? "source",
      author: existing?.author ?? null,
      published_at: existing?.published_at ?? null,
      relevance_score: existing?.relevance_score,
    });
  }

  return lookup;
}

function topSidebarSources(
  scriptSources: FinalScript["sources"],
  researchSources: ResearchSource[]
): DisplaySource[] {
  if (researchSources.length > 0) {
    return researchSources.slice(0, TOP_RESEARCH_SOURCES_LIMIT).map((source) => ({
      source_id: source.source_id ?? null,
      title: source.title,
      url: source.url,
      credibility: source.credibility,
      type: source.source_type,
      author: source.author,
      published_at: source.published_at,
      relevance_score: source.relevance_score,
    }));
  }

  return scriptSources.slice(0, TOP_RESEARCH_SOURCES_LIMIT).map((source) => ({
    source_id: source.source_id ?? null,
    title: source.title,
    url: source.url,
    credibility: source.credibility,
    type: source.type,
    author: null,
    published_at: null,
  }));
}

function sourcesUsedInScript(
  script: FinalScript,
  researchSources: ResearchSource[]
): DisplaySource[] {
  const sourceLookup = buildSourceLookup(script.sources, researchSources);
  const usedSources: DisplaySource[] = [];
  const seen = new Set<string>();

  for (const section of script.sections) {
    for (const sourceId of section.source_ids ?? []) {
      const source = sourceLookup.get(sourceId);
      if (!source) continue;
      const key = sourceKey(source);
      if (seen.has(key)) continue;
      seen.add(key);
      usedSources.push(source);
    }
  }

  if (usedSources.length > 0) {
    return usedSources;
  }

  return script.sources.map((source) => ({
    source_id: source.source_id ?? null,
    title: source.title,
    url: source.url,
    credibility: source.credibility,
    type: source.type,
    author: null,
    published_at: null,
  }));
}

function allResearchSourcesForExport(
  script: FinalScript,
  researchSources: ResearchSource[]
): DisplaySource[] {
  if (researchSources.length > 0) {
    return researchSources.map((source) => ({
      source_id: source.source_id ?? null,
      title: source.title,
      url: source.url,
      credibility: source.credibility,
      type: source.source_type,
      author: source.author,
      published_at: source.published_at,
      relevance_score: source.relevance_score,
    }));
  }

  return script.sources.map((source) => ({
    source_id: source.source_id ?? null,
    title: source.title,
    url: source.url,
    credibility: source.credibility,
    type: source.type,
    author: null,
    published_at: null,
  }));
}

export default function ResultsPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const currentUser = getUserInfo();
  const isAdmin = currentUser?.is_admin ?? false;
  const [tab, setTab] = useState<Tab>("script");
  const [downloading, setDownloading] = useState(false);
  const [dismissedFailureBannerKey, setDismissedFailureBannerKey] = useState<string | null>(null);

  const { data: story, isLoading } = useQuery<Story>({
    queryKey: ["story", id],
    queryFn: () => apiClient.getStory(id),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s && isTerminalStoryStatus(s) ? false : 4000;
    },
  });

  const { data: script } = useQuery<FinalScript>({
    queryKey: ["script", id],
    queryFn: () => apiClient.getScript(id),
    enabled: story?.status === "completed",
  });

  const { data: researchSources = [] } = useQuery<ResearchSource[]>({
    queryKey: ["story", id, "sources"],
    queryFn: () => apiClient.getResearchSources(id),
    enabled: story?.status === "completed",
  });

  useEffect(() => {
    if (!id) return;
    return apiClient.streamStoryEvents(
      id,
      (nextStory) => {
        queryClient.setQueryData(["story", id], nextStory);
        if (nextStory.status === "completed") {
          queryClient.invalidateQueries({ queryKey: ["script", id] });
        }
      },
      () => undefined
    );
  }, [id, queryClient]);

  const handleDownload = async () => {
    if (!script) return;
    setDownloading(true);
    try { downloadScriptPdf(script); } finally { setDownloading(false); }
  };

  if (isLoading) {
    return (
      <div style={{ display: "flex", height: "100%", alignItems: "center", justifyContent: "center", background: "var(--color-background-tertiary)" }}>
        <Loader2 size={20} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
      </div>
    );
  }

  if (!story) {
    return (
      <div style={{ display: "flex", height: "100%", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12 }}>
        <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Story not found.</p>
        <button onClick={() => router.push("/")} className="btn-secondary">Go home</button>
      </div>
    );
  }

  const isComplete = story.status === "completed";
  const isFailed   = story.status === "failed";
  const isStopped  = isAngleSelectionExpired(story.status);
  const isRunning  = !isComplete && !isFailed && !isStopped;
  const failureBannerKey = story.pipeline_failure_summary
    ? `${story.id}:${story.pipeline_failure_summary}`
    : null;
  const showFailureBanner = Boolean(
    story.pipeline_failure_summary
      && failureBannerKey
      && dismissedFailureBannerKey !== failureBannerKey
  );

  const revisionNumber = story.revision > 1 ? story.revision : null;

  const TABS: { id: Tab; label: string; available: boolean }[] = [
    { id: "script",     label: revisionNumber ? `Script v${revisionNumber}` : "Script", available: isComplete },
  ];

  return (
    <div style={{ minHeight: "100%", background: "var(--color-background-tertiary)" }}>
      {/* Topbar */}
      <div
        style={{
          background: "var(--color-background-primary)",
          borderBottom: "0.5px solid var(--color-border-tertiary)",
        }}
      >
        <div style={{ padding: "14px 28px 0" }}>
          <button
            onClick={() => router.back()}
            className="btn-ghost"
            style={{ padding: "4px 0", marginBottom: 12, fontSize: 12, gap: 4 }}
          >
            <ArrowLeft size={13} /> Back
          </button>

          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: showFailureBanner ? 12 : 14 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              {/* Status + tone row */}
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                {isComplete && <span className="badge badge-success" style={{ fontSize: 11 }}><CheckCircle2 size={10} /> Completed</span>}
                {isFailed   && <span className="badge badge-danger"  style={{ fontSize: 11 }}><XCircle size={10} /> Failed</span>}
                {isStopped  && <span className="badge badge-warning" style={{ fontSize: 11 }}><AlertTriangle size={10} /> Script writing stopped</span>}
                {isRunning  && <span className="badge badge-active"  style={{ fontSize: 11 }}><Loader2 size={10} className="animate-spin" /> {storyStatusLabel(story.status)}</span>}
                <span className={`badge tone-${story.tone}`} style={{ fontSize: 11, border: "none" }}>{story.tone}</span>
              </div>

              <h1 style={{ fontSize: 18, fontWeight: 500, marginBottom: 4 }}>{story.title}</h1>
              <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>{story.topic}</p>
              {isAdmin && story.owner_email && (
                <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 4 }}>
                  Created by {story.owner_email}
                </p>
              )}

              {/* Metrics */}
              {isComplete && (
                <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
                  {story.word_count && (
                    <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                      Words <strong style={{ color: "var(--color-text-primary)" }}>{story.word_count.toLocaleString()}</strong>
                    </span>
                  )}
                  {story.estimated_duration_minutes && (
                    <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                      Duration <strong style={{ color: "var(--color-text-primary)" }}>{story.estimated_duration_minutes} min</strong>
                    </span>
                  )}
                </div>
              )}
            </div>

            {isComplete && script && (
              <div style={{ display: "flex", gap: 8, flexShrink: 0, marginLeft: 16 }}>
                <button onClick={handleDownload} disabled={downloading} className="btn-secondary">
                  {downloading ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                  Download PDF
                </button>
              </div>
            )}
          </div>

          {showFailureBanner && story.pipeline_failure_summary && failureBannerKey && (
            <div
              role="alert"
              style={{
                position: "relative",
                maxWidth: 760,
                margin: "0 0 14px",
                padding: "12px 44px 12px 14px",
                background: "var(--color-danger-bg)",
                border: "0.5px solid #fecaca",
                borderRadius: 8,
                display: "flex",
                gap: 10,
                alignItems: "flex-start",
              }}
            >
              <AlertTriangle size={16} style={{ color: "var(--color-danger)", flexShrink: 0, marginTop: 2 }} />
              <div style={{ minWidth: 0 }}>
                <p style={{ fontSize: 12, fontWeight: 600, color: "var(--color-danger)", marginBottom: 4 }}>
                  AI Journalist could not complete the script cleanly
                </p>
                <p style={{ fontSize: 11, color: "var(--color-text-secondary)", whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
                  {story.pipeline_failure_summary}
                </p>
                <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 6 }}>
                  The latest available script is shown below.
                </p>
              </div>
              <button
                type="button"
                aria-label="Dismiss pipeline warning"
                title="Dismiss"
                onClick={() => setDismissedFailureBannerKey(failureBannerKey)}
                style={{
                  position: "absolute",
                  top: 8,
                  right: 8,
                  width: 30,
                  height: 30,
                  padding: 0,
                  border: "none",
                  borderRadius: "var(--border-radius-sm)",
                  background: "transparent",
                  color: "var(--color-danger)",
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <X size={16} />
              </button>
            </div>
          )}

          {/* Tabs */}
          {isComplete && (
            <div style={{ display: "flex", gap: 0, marginBottom: -1 }}>
              {TABS.filter(t => t.available).map(({ id: tid, label }) => (
                <button
                  key={tid}
                  onClick={() => setTab(tid)}
                  style={{
                    padding: "9px 14px",
                    fontSize: 13,
                    fontWeight: tab === tid ? 500 : 400,
                    color: tab === tid ? "var(--color-text-primary)" : "var(--color-text-secondary)",
                    background: "none",
                    border: "none",
                    borderBottom: tab === tid ? "1.5px solid var(--color-action)" : "1.5px solid transparent",
                    cursor: "pointer",
                    fontFamily: "var(--font-sans)",
                    transition: "color 0.12s",
                    marginBottom: 0,
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Content */}
      <div style={{ padding: "28px", maxWidth: 800 }}>
        {isRunning  && <PipelineStatus story={story} />}
        {isFailed   && <FailedState story={story} />}
        {isStopped  && <AngleSelectionStoppedState story={story} />}
        {isComplete && tab === "script"     && script && (
          <ScriptPanel
            script={script}
            researchSources={researchSources}
            versionNumber={revisionNumber}
          />
        )}
      </div>
    </div>
  );
}

/* ── Pipeline status ── */
function PipelineStatus({ story }: { story: Story }) {
  const STAGES = ["researching", "analysing", "writing_storyline", "evaluating", "scripting"];
  const current = STAGES.indexOf(story.status);
  const pct = Math.max(((current + 1) / STAGES.length) * 100, 8);
  return (
    <div className="card" style={{ padding: "24px", maxWidth: 480, margin: "0 auto", textAlign: "center" }}>
      <Loader2 size={20} className="animate-spin" style={{ color: "var(--color-text-tertiary)", marginBottom: 14 }} />
      <p style={{ fontSize: 14, fontWeight: 500, marginBottom: 4 }}>
        {storyStatusTitle(story.status)}…
      </p>
      <p style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 16 }}>
        Stage {Math.max(current + 1, 1)} of {STAGES.length}
      </p>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/* ── Angle selection stopped state ── */
function AngleSelectionStoppedState({ story }: { story: Story }) {
  return (
    <div className="card" style={{ padding: "32px", maxWidth: 520, margin: "0 auto", textAlign: "center" }}>
      <AlertTriangle size={24} style={{ color: "var(--color-warning)", marginBottom: 10 }} />
      <p style={{ fontSize: 14, fontWeight: 500, marginBottom: 6 }}>Script writing stopped</p>
      <p style={{ fontSize: 12, color: "var(--color-warning)", background: "var(--color-warning-bg)", padding: "10px 12px", borderRadius: 8, border: "0.5px solid #fed7aa" }}>
        {story.error_message || ANGLE_SELECTION_STOPPED_MESSAGE}
      </p>
    </div>
  );
}

/* ── Failed state ── */
function FailedState({ story }: { story: Story }) {
  return (
    <div className="card" style={{ padding: "32px", maxWidth: 440, margin: "0 auto", textAlign: "center" }}>
      <XCircle size={24} style={{ color: "var(--color-danger)", marginBottom: 10 }} />
      <p style={{ fontSize: 14, fontWeight: 500, marginBottom: 6 }}>Generation failed</p>
      {story.error_message && (
        <p style={{ fontSize: 12, color: "var(--color-danger)", background: "var(--color-danger-bg)", padding: "10px 12px", borderRadius: 8, border: "0.5px solid #fecaca" }}>
          {story.error_message}
        </p>
      )}
    </div>
  );
}

/* ── Script panel ── */
function ScriptPanel({
  script,
  researchSources,
  versionNumber,
}: {
  script: FinalScript;
  researchSources: ResearchSource[];
  versionNumber: number | null;
}) {
  const [open, setOpen] = useState<number[]>([0]);
  const [downloadingSourceList, setDownloadingSourceList] = useState<"used" | "all" | null>(null);
  const [exportNotice, setExportNotice] = useState<ExportNotice | null>(null);
  const toggle = (i: number) => setOpen(p => p.includes(i) ? p.filter(x => x !== i) : [...p, i]);
  const sourceLookup = buildSourceLookup(script.sources, researchSources);
  const sidebarSources = topSidebarSources(script.sources, researchSources);
  const exportSources = sourcesUsedInScript(script, researchSources);
  const allResearchExportSources = allResearchSourcesForExport(script, researchSources);

  useEffect(() => {
    if (!exportNotice) return;
    const timer = window.setTimeout(() => setExportNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [exportNotice]);

  const handleSourceListDownload = (mode: "used" | "all") => {
    const sources = mode === "used" ? exportSources : allResearchExportSources;
    if (sources.length === 0) return;
    setDownloadingSourceList(mode);
    try {
      const opened = downloadSourceListPdf(
        mode === "used" ? `${script.title} — Sources Used in Script` : `${script.title} — All Research Sources`,
        sources
      );
      setExportNotice(
        opened
          ? { tone: "success", text: "Opened a print-ready PDF in a new tab." }
          : { tone: "error", text: "Browser blocked the export window. Please allow pop-ups and try again." }
      );
    } finally {
      setDownloadingSourceList(null);
    }
  };

  return (
    <div>
      {versionNumber && (
        <div style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              padding: "3px 10px",
              background: "var(--color-action)",
              color: "#fff",
              borderRadius: 6,
              fontSize: 12,
              fontWeight: 600,
              letterSpacing: "0.03em",
            }}
          >
            v{versionNumber}
          </span>
          <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>
            Revised script — original version preserved in History
          </span>
        </div>
      )}
      {/* Two-column layout */}
      <div style={{ display: "flex", gap: 24 }}>
        {/* Left: TOC + Sources */}
        <div style={{ width: 180, flexShrink: 0 }}>
          <div className="card" style={{ padding: "14px 16px", position: "sticky", top: 24 }}>
            <p className="section-label">Contents</p>
            <ol style={{ listStyle: "none", padding: 0, margin: 0 }}>
              <li
                style={{ padding: "5px 0", fontSize: 12, color: "var(--color-text-secondary)", borderBottom: "0.5px solid var(--color-border-tertiary)", marginBottom: 4 }}
              >
                Opening
              </li>
              {script.sections.map((s, i) => (
                <li
                  key={i}
                  style={{ padding: "5px 0", fontSize: 12, color: "var(--color-text-secondary)", cursor: "pointer" }}
                  onClick={() => { if (!open.includes(i)) toggle(i); }}
                >
                  {s.section_number}. {s.title}
                </li>
              ))}
              <li
                style={{ padding: "5px 0", fontSize: 12, color: "var(--color-text-secondary)", borderTop: "0.5px solid var(--color-border-tertiary)", marginTop: 4 }}
              >
                Closing
              </li>
            </ol>

            {sidebarSources.length > 0 && (
              <div style={{ marginTop: 16, paddingTop: 14, borderTop: "0.5px solid var(--color-border-tertiary)" }}>
                <p className="section-label">Top Research Sources ({sidebarSources.length})</p>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {sidebarSources.map((src, i) => (
                    src.url
                      ? <a key={i} href={src.url} target="_blank" rel="noopener noreferrer"
                          className="source-chip"
                          style={{ textDecoration: "none", color: "var(--color-action)" }}
                          title={src.title}>
                          {i + 1}. {src.title.slice(0, 26)}{src.title.length > 26 ? "…" : ""}
                        </a>
                      : <span key={i} className="source-chip" title={src.title}>
                          {i + 1}. {src.title.slice(0, 26)}{src.title.length > 26 ? "…" : ""}
                        </span>
                  ))}
                </div>
                {exportSources.length > 0 && (
                  <button
                    type="button"
                    onClick={() => handleSourceListDownload("used")}
                    disabled={downloadingSourceList !== null}
                    className="btn-secondary"
                    style={{ width: "100%", marginTop: 10, justifyContent: "center" }}
                  >
                    {downloadingSourceList === "used" ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                    Download used sources
                  </button>
                )}
                {allResearchExportSources.length > 0 && (
                  <button
                    type="button"
                    onClick={() => handleSourceListDownload("all")}
                    disabled={downloadingSourceList !== null}
                    className="btn-secondary"
                    style={{ width: "100%", marginTop: 8, justifyContent: "center" }}
                  >
                    {downloadingSourceList === "all" ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                    Download all research sources
                  </button>
                )}
                {exportNotice && (
                  <p
                    style={{
                      marginTop: 8,
                      fontSize: 11,
                      lineHeight: 1.5,
                      color: exportNotice.tone === "success" ? "var(--color-success)" : "var(--color-danger)",
                    }}
                  >
                    {exportNotice.text}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Right: script body */}
        <div style={{ flex: 1, minWidth: 0 }}>

          {/* Logline */}
          <div className="card" style={{ padding: "18px 20px", marginBottom: 16 }}>
            <div className="section-rule"><span>Logline</span></div>
            <p style={{ fontSize: 13, lineHeight: 1.7 }}>{script.logline}</p>
          </div>

          {/* Opening hook */}
          <div className="card" style={{ padding: "18px 20px", marginBottom: 16 }}>
            <div className="section-rule"><span>Opening Hook</span></div>
            <p style={{ fontSize: 13, lineHeight: 1.7 }}>{script.opening_hook}</p>
          </div>

          {/* Acts */}
          {script.sections.map((section, i) => {
            const sectionSources = (section.source_ids ?? [])
              .map((sourceId) => sourceLookup.get(sourceId))
              .filter(Boolean) as DisplaySource[];
            return (
            <div key={i} className="card" style={{ marginBottom: 10, overflow: "hidden" }}>
              <button
                onClick={() => toggle(i)}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "14px 20px",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontFamily: "var(--font-sans)",
                  textAlign: "left",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span
                    style={{
                      width: 20,
                      height: 20,
                      background: "var(--color-action)",
                      color: "#fff",
                      borderRadius: 4,
                      fontSize: 11,
                      fontWeight: 500,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
                    }}
                  >
                    {section.section_number}
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text-primary)" }}>{section.title}</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{Math.round(section.estimated_seconds / 60)} min</span>
                  {open.includes(i) ? <ChevronUp size={14} style={{ color: "var(--color-text-tertiary)" }} /> : <ChevronDown size={14} style={{ color: "var(--color-text-tertiary)" }} />}
                </div>
              </button>

	              {open.includes(i) && (
	                <div style={{ padding: "16px 20px 20px", borderTop: "0.5px solid var(--color-border-tertiary)" }}>
	                  <p style={{ fontSize: 13, lineHeight: 1.8 }}>{section.narration}</p>
                    {sectionSources.length > 0 && (
                      <div style={{ marginTop: 14, display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {sectionSources.map((source, sourceIndex) => (
                          source.url
                            ? <a
                                key={`${source.source_id}-${sourceIndex}`}
                                href={source.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="source-chip"
                                style={{ textDecoration: "none", color: "var(--color-action)" }}
                              >
                                {source.title.slice(0, 32)}{source.title.length > 32 ? "..." : ""}
                              </a>
                            : <span key={`${source.source_id}-${sourceIndex}`} className="source-chip">
                                {source.title.slice(0, 32)}{source.title.length > 32 ? "..." : ""}
                              </span>
                        ))}
                      </div>
                    )}
	                </div>
	              )}
	            </div>
            );
          })}

          {/* Closing */}
          <div className="card" style={{ padding: "18px 20px" }}>
            <div className="section-rule"><span>Closing Statement</span></div>
            <p style={{ fontSize: 13, lineHeight: 1.7 }}>{script.closing_statement}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

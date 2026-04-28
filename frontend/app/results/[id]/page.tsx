"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Loader2, ArrowLeft, Download, CheckCircle2, XCircle, ChevronDown, ChevronUp } from "lucide-react";
import { apiClient, type Story, type FinalScript } from "@/lib/api";
import { downloadScriptPdf } from "@/lib/script-export";

type Tab = "script" | "evaluation";

const SCRIPT_GRADE_HELP =
  "Measures final script quality across hook, flow, evidence, pacing, writing, and production readiness.";
const BENCHMARK_GRADE_HELP =
  "Measures how closely the story matches the benchmark corpus in hook, structure, data density, human narrative, and closing pattern.";
const GRADE_SCALE_HELP = "Letter scale: A 85%+, B 70-84%, C 55-69%, D below 55%.";

export default function ResultsPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("script");
  const [downloading, setDownloading] = useState(false);

  const { data: story, isLoading } = useQuery<Story>({
    queryKey: ["story", id],
    queryFn: () => apiClient.getStory(id),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s && ["completed", "failed"].includes(s) ? false : 4000;
    },
  });

  const { data: script } = useQuery<FinalScript>({
    queryKey: ["script", id],
    queryFn: () => apiClient.getScript(id),
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

  const rewriteMutation = useMutation({
    mutationFn: () => apiClient.rewriteStory(id),
    onSuccess: (nextStory) => {
      queryClient.invalidateQueries({ queryKey: ["stories"] });
      router.push(`/results/${nextStory.id}`);
    },
  });

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
  const isRunning  = !isComplete && !isFailed;

  const revisionNumber = story.revision > 1 ? story.revision : null;

  const TABS: { id: Tab; label: string; available: boolean }[] = [
    { id: "script",     label: revisionNumber ? `Script v${revisionNumber}` : "Script", available: isComplete },
    { id: "evaluation", label: "Script Evaluation", available: isComplete },
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

          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 14 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              {/* Status + tone row */}
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                {isComplete && <span className="badge badge-success" style={{ fontSize: 11 }}><CheckCircle2 size={10} /> Completed</span>}
                {isFailed   && <span className="badge badge-danger"  style={{ fontSize: 11 }}><XCircle size={10} /> Failed</span>}
                {isRunning  && <span className="badge badge-active"  style={{ fontSize: 11 }}><Loader2 size={10} className="animate-spin" /> {story.status.replace(/_/g, " ")}</span>}
                <span className={`badge tone-${story.tone}`} style={{ fontSize: 11, border: "none" }}>{story.tone}</span>
              </div>

              <h1 style={{ fontSize: 18, fontWeight: 500, marginBottom: 4 }}>{story.title}</h1>
              <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>{story.topic}</p>

              {/* Metrics */}
              {isComplete && (
                <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
                  {story.quality_score != null && (
                    <Link
                      href={`/results/${id}/evaluation`}
                      title="Double-click for full breakdown"
                      onDoubleClick={(e) => { e.preventDefault(); router.push(`/results/${id}/evaluation`); }}
                      style={{ fontSize: 12, color: "var(--color-text-secondary)", textDecoration: "none", cursor: "pointer" }}
                    >
                      Quality <strong style={{ color: "var(--color-action)", textDecoration: "underline dotted" }}>{(story.quality_score * 100).toFixed(0)}%</strong>
                    </Link>
                  )}
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
                  {story.benchmark_data && (
                    <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }} title={BENCHMARK_GRADE_HELP}>
                      Benchmark <strong style={{ color: "var(--color-text-primary)" }}>{story.benchmark_data.grade}</strong>
                    </span>
                  )}
                  {story.script_audit_data && (
                    <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }} title={SCRIPT_GRADE_HELP}>
                      Script Grade <strong style={{ color: "var(--color-text-primary)" }}>{story.script_audit_data.grade}</strong>
                    </span>
                  )}
                </div>
              )}
            </div>

            {isComplete && script && (
              <div style={{ display: "flex", gap: 8, flexShrink: 0, marginLeft: 16 }}>
                {story.script_audit_data && (
                  <button
                    onClick={() => rewriteMutation.mutate()}
                    disabled={rewriteMutation.isPending}
                    className="btn-secondary"
                  >
                    {rewriteMutation.isPending && <Loader2 size={13} className="animate-spin" />}
                    Rewrite from audit
                  </button>
                )}
                <button onClick={handleDownload} disabled={downloading} className="btn-secondary">
                  {downloading ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                  Download PDF
                </button>
              </div>
            )}
          </div>

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
        {isComplete && tab === "script"     && script && <ScriptPanel script={script} versionNumber={revisionNumber} />}
        {isComplete && tab === "evaluation" && <ScriptEvaluationPanel story={story} storyId={id} />}
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
        {story.status.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}…
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
function ScriptPanel({ script, versionNumber }: { script: FinalScript; versionNumber: number | null }) {
  const [open, setOpen] = useState<number[]>([0]);
  const toggle = (i: number) => setOpen(p => p.includes(i) ? p.filter(x => x !== i) : [...p, i]);

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

            {script.sources.length > 0 && (
              <div style={{ marginTop: 16, paddingTop: 14, borderTop: "0.5px solid var(--color-border-tertiary)" }}>
                <p className="section-label">Sources ({script.sources.length})</p>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {script.sources.map((src, i) => (
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
              .map((sourceId) => script.sources.find((source) => source.source_id === sourceId))
              .filter(Boolean) as FinalScript["sources"];
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

/* ── Evaluation panel ── */
function EvaluationPanel({ data }: { data: NonNullable<Story["evaluation_data"]> }) {
  const criteria = [
    { key: "factual_accuracy",       label: "Factual Accuracy" },
    { key: "narrative_coherence",    label: "Narrative Coherence" },
    { key: "audience_engagement",    label: "Audience Engagement" },
    { key: "source_diversity",       label: "Source Diversity" },
    { key: "originality",            label: "Originality" },
    { key: "production_feasibility", label: "Production Feasibility" },
  ] as const;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Score header */}
      <div className="card" style={{ padding: "18px 20px", display: "flex", alignItems: "center", gap: 20 }}>
        <div style={{ textAlign: "center", flexShrink: 0 }}>
          <p style={{ fontSize: 32, fontWeight: 500, lineHeight: 1 }}>{(data.overall_score * 100).toFixed(0)}<span style={{ fontSize: 16, color: "var(--color-text-tertiary)" }}>%</span></p>
          <p style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>Overall</p>
        </div>
        <div style={{ width: "0.5px", height: 48, background: "var(--color-border-tertiary)", flexShrink: 0 }} />
        <div>
          <p style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 8 }}>{data.evaluator_notes}</p>
          <span className={data.approved_for_scripting ? "badge badge-success" : "badge badge-danger"} style={{ fontSize: 11 }}>
            {data.approved_for_scripting ? <CheckCircle2 size={10} /> : <XCircle size={10} />}
            {data.approved_for_scripting ? "Approved for scripting" : "Not approved"}
          </span>
        </div>
      </div>

      {/* Criteria */}
      <div className="card" style={{ padding: "18px 20px" }}>
        <div className="section-rule"><span>Criteria breakdown</span></div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {criteria.map(({ key, label }) => {
            const score = data.criteria[key] ?? 0;
            return (
              <div key={key}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{label}</span>
                  <span style={{ fontSize: 12, fontWeight: 500 }}>{(score * 100).toFixed(0)}%</span>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${score * 100}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Strengths + weaknesses */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div className="card" style={{ padding: "16px 18px" }}>
          <p className="section-label" style={{ color: "var(--color-success)" }}>Strengths</p>
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
            {data.strengths.map((s, i) => (
              <li key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>
                <CheckCircle2 size={13} style={{ color: "var(--color-success)", flexShrink: 0, marginTop: 1 }} />
                {s}
              </li>
            ))}
          </ul>
        </div>
        <div className="card" style={{ padding: "16px 18px" }}>
          <p className="section-label" style={{ color: "var(--color-danger)" }}>Areas to improve</p>
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
            {data.weaknesses.map((w, i) => (
              <li key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>
                <XCircle size={13} style={{ color: "var(--color-danger)", flexShrink: 0, marginTop: 1 }} />
                {w}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

/* ── Script audit panel ── */
function researchHref(storyId: string, objective: string) {
  return `/research?story=${storyId}&objective=${encodeURIComponent(objective)}`;
}

function ScriptAuditPanel({ data, storyId }: { data: NonNullable<Story["script_audit_data"]>; storyId: string }) {
  const criteria = [
    { key: "hook_strength", label: "Hook Strength" },
    { key: "narrative_flow", label: "Narrative Flow" },
    { key: "evidence_and_specificity", label: "Evidence & Specificity" },
    { key: "pacing", label: "Pacing" },
    { key: "writing_quality", label: "Writing Quality" },
    { key: "production_readiness", label: "Production Readiness" },
  ] as const;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="card" style={{ padding: "18px 20px", display: "flex", alignItems: "center", gap: 20 }}>
        <div
          style={{
            width: 64,
            height: 64,
            background: "var(--color-action)",
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 12,
            fontSize: 26,
            fontWeight: 600,
            flexShrink: 0,
          }}
        >
          {data.grade}
        </div>
        <div style={{ flex: 1 }}>
          <p style={{ fontSize: 13, fontWeight: 500, marginBottom: 6 }}>
            Script score: {(data.overall_score * 100).toFixed(0)}%
          </p>
          <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
            {SCRIPT_GRADE_HELP}
          </p>
          <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 6 }}>
            {GRADE_SCALE_HELP}
          </p>
          <span className={data.ready_for_production ? "badge badge-success" : "badge badge-danger"} style={{ fontSize: 11, marginBottom: 8 }}>
            {data.ready_for_production ? <CheckCircle2 size={10} /> : <XCircle size={10} />}
            {data.ready_for_production ? "Ready for production" : "Needs another script pass"}
          </span>
          {data.audit_summary && (
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6, marginTop: 8 }}>
              {data.audit_summary}
            </p>
          )}
        </div>
      </div>

      <div className="card" style={{ padding: "18px 20px" }}>
        <div className="section-rule"><span>Criteria breakdown</span></div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {criteria.map(({ key, label }) => {
            const score = data.criteria[key] ?? 0;
            return (
              <div key={key}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{label}</span>
                  <span style={{ fontSize: 12, fontWeight: 500 }}>{(score * 100).toFixed(0)}%</span>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${score * 100}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div className="card" style={{ padding: "16px 18px" }}>
          <p className="section-label" style={{ color: "var(--color-success)" }}>Strengths</p>
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
            {data.strengths.map((item, i) => (
              <li key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>
                <CheckCircle2 size={13} style={{ color: "var(--color-success)", flexShrink: 0, marginTop: 1 }} />
                {item}
              </li>
            ))}
          </ul>
        </div>
        <div className="card" style={{ padding: "16px 18px" }}>
          <p className="section-label" style={{ color: "var(--color-danger)" }}>Weaknesses</p>
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
            {data.weaknesses.map((item, i) => (
              <li key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>
                <XCircle size={13} style={{ color: "var(--color-danger)", flexShrink: 0, marginTop: 1 }} />
                {item}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {data.rewrite_priorities.length > 0 && (
        <div className="card" style={{ padding: "16px 18px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 10 }}>
            <p className="section-label" style={{ marginBottom: 0 }}>Rewrite priorities</p>
            <Link
              href={researchHref(storyId, data.rewrite_priorities[0] ?? "Find stronger sources for the weakest script sections.")}
              className="btn-secondary"
              style={{ textDecoration: "none" }}
            >
              Run focused research
            </Link>
          </div>
          <ol style={{ margin: 0, padding: "0 0 0 16px", display: "flex", flexDirection: "column", gap: 6 }}>
            {data.rewrite_priorities.map((item, i) => (
              <li key={i} style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                {item}
              </li>
            ))}
          </ol>
        </div>
      )}

      {data.benchmark_comparison && (
        <div className="card" style={{ padding: "18px 20px" }}>
          <div className="section-rule"><span>Best-in-class comparison</span></div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
              {sanitizeBenchmarkText(data.benchmark_comparison.alignment_summary)}
            </p>
            {[
              ["Hook", data.benchmark_comparison.hook_comparison],
              ["Structure", data.benchmark_comparison.structure_comparison],
              ["Data Density", data.benchmark_comparison.data_density_comparison],
              ["Closing", data.benchmark_comparison.closing_comparison],
            ].map(([label, value]) => (
              <div key={label}>
                <p style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-tertiary)", marginBottom: 3 }}>
                  {label}
                </p>
                <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                  {sanitizeBenchmarkText(value)}
                </p>
              </div>
            ))}
            {data.benchmark_comparison.best_in_class_takeaways.length > 0 && (
              <div>
                <p className="section-label" style={{ marginBottom: 8 }}>Takeaways</p>
                <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
                  {data.benchmark_comparison.best_in_class_takeaways.map((item, i) => (
                    <li key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>
                      <CheckCircle2 size={13} style={{ color: "var(--color-success)", flexShrink: 0, marginTop: 1 }} />
                      {sanitizeBenchmarkText(item)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {data.section_audits.map((section) => (
          <div key={section.section_number} className="card" style={{ padding: "16px 18px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 8 }}>
              <div>
                <p style={{ fontSize: 13, fontWeight: 500 }}>
                  Section {section.section_number}: {section.title}
                </p>
                <p style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 4 }}>
                  {section.summary}
                </p>
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)", flexShrink: 0 }}>
                {(section.score * 100).toFixed(0)}%
              </div>
            </div>

            {(section.strengths.length > 0 || section.weaknesses.length > 0) && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 10 }}>
                <div>
                  <p className="section-label" style={{ color: "var(--color-success)", marginBottom: 6 }}>Strengths</p>
                  <ul style={{ margin: 0, paddingLeft: 16 }}>
                    {section.strengths.map((item, i) => (
                      <li key={i} style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>{item}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <p className="section-label" style={{ color: "var(--color-danger)", marginBottom: 6 }}>Weaknesses</p>
                  <ul style={{ margin: 0, paddingLeft: 16 }}>
                    {section.weaknesses.map((item, i) => (
                      <li key={i} style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>{item}</li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            {section.benchmark_notes.length > 0 && (
              <div style={{ marginBottom: 10 }}>
                <p className="section-label" style={{ marginBottom: 6 }}>Benchmark notes</p>
                <ul style={{ margin: 0, paddingLeft: 16 }}>
                  {section.benchmark_notes.map((item, i) => (
                    <li key={i} style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                      {sanitizeBenchmarkText(item)}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div
              style={{
                borderTop: "0.5px solid var(--color-border-tertiary)",
                paddingTop: 10,
                fontSize: 12,
                color: "var(--color-text-secondary)",
                lineHeight: 1.6,
              }}
            >
              <strong style={{ color: "var(--color-text-primary)" }}>Rewrite recommendation:</strong>{" "}
              {section.rewrite_recommendation}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Combined Script Evaluation panel ── */
function ScriptEvaluationPanel({ story, storyId: _storyId }: { story: Story; storyId: string }) {
  const eval_data = story.evaluation_data;
  const audit_data = story.script_audit_data;
  const bm_data = story.benchmark_data;

  const evalCriteria = [
    { key: "factual_accuracy",       label: "Factual Accuracy" },
    { key: "narrative_coherence",    label: "Narrative Coherence" },
    { key: "audience_engagement",    label: "Audience Engagement" },
    { key: "source_diversity",       label: "Source Diversity" },
    { key: "originality",            label: "Originality" },
    { key: "production_feasibility", label: "Production Feasibility" },
  ] as const;

  const auditCriteria = [
    { key: "hook_strength",              label: "Hook Strength" },
    { key: "narrative_flow",             label: "Narrative Flow" },
    { key: "evidence_and_specificity",   label: "Evidence & Specificity" },
    { key: "pacing",                     label: "Pacing" },
    { key: "writing_quality",            label: "Writing Quality" },
    { key: "production_readiness",       label: "Production Readiness" },
  ] as const;

  const bmMetrics = [
    { key: "hook_potency",              label: "Hook Potency" },
    { key: "title_formula_fit",         label: "Title Formula Fit" },
    { key: "act_architecture",          label: "Act Architecture" },
    { key: "data_density",              label: "Data Density" },
    { key: "human_narrative_placement", label: "Human Narrative" },
    { key: "tension_release_rhythm",    label: "Tension / Release" },
    { key: "closing_device",            label: "Closing Device" },
  ] as const;

  const allStrengths = [
    ...(eval_data?.strengths ?? []),
    ...(audit_data?.strengths ?? []),
    ...(bm_data?.strengths ?? []),
  ];
  const allWeaknesses = [
    ...(eval_data?.weaknesses ?? []),
    ...(audit_data?.weaknesses ?? []),
    ...(bm_data?.gaps ?? []),
  ];

  const bc = audit_data?.benchmark_comparison ?? null;

  if (!eval_data && !audit_data && !bm_data) {
    return (
      <div className="card" style={{ padding: "32px", textAlign: "center", maxWidth: 480, margin: "0 auto" }}>
        <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>No evaluation data available for this story.</p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Score summary */}
      <div className="card" style={{ padding: "18px 24px", display: "flex", gap: 32, flexWrap: "wrap", alignItems: "center" }}>
        {eval_data && (
          <div style={{ textAlign: "center" }}>
            <p style={{ fontSize: 30, fontWeight: 600, lineHeight: 1, color: "var(--color-action)" }}>
              {(eval_data.overall_score * 100).toFixed(0)}<span style={{ fontSize: 16, color: "var(--color-text-tertiary)" }}>%</span>
            </p>
            <p style={{ fontSize: 11, fontWeight: 500, marginTop: 4, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Content Quality</p>
          </div>
        )}
        {eval_data && (audit_data || bm_data) && (
          <div style={{ width: "0.5px", height: 40, background: "var(--color-border-tertiary)", flexShrink: 0 }} />
        )}
        {audit_data && (
          <div style={{ textAlign: "center", maxWidth: 190 }}>
            <p style={{ fontSize: 30, fontWeight: 600, lineHeight: 1, color: "var(--color-action)" }}>{audit_data.grade}</p>
            <p style={{ fontSize: 11, fontWeight: 500, marginTop: 4, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Script Grade</p>
            <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 2 }}>{(audit_data.overall_score * 100).toFixed(0)}% audit score</p>
            <p style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 4, lineHeight: 1.5 }}>
              Final script quality.
            </p>
          </div>
        )}
        {audit_data && bm_data && (
          <div style={{ width: "0.5px", height: 40, background: "var(--color-border-tertiary)", flexShrink: 0 }} />
        )}
        {bm_data && (
          <div style={{ textAlign: "center", maxWidth: 190 }}>
            <p style={{ fontSize: 30, fontWeight: 600, lineHeight: 1, color: "var(--color-action)" }}>{bm_data.grade}</p>
            <p style={{ fontSize: 11, fontWeight: 500, marginTop: 4, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Benchmark Grade</p>
            <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 2 }}>{Math.round(bm_data.bi_similarity_score * 100)}% similarity</p>
            <p style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 4, lineHeight: 1.5 }}>
              Match to benchmark corpus.
            </p>
          </div>
        )}
        {audit_data && (
          <div style={{ flex: 1, minWidth: 200 }}>
            <span className={audit_data.ready_for_production ? "badge badge-success" : "badge badge-danger"} style={{ fontSize: 11 }}>
              {audit_data.ready_for_production ? <CheckCircle2 size={10} /> : <XCircle size={10} />}
              {audit_data.ready_for_production ? "Ready for production" : "Needs another pass"}
            </span>
            {audit_data.audit_summary && (
              <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6, marginTop: 8 }}>
                {audit_data.audit_summary}
              </p>
            )}
          </div>
        )}
      </div>

      {/* Evaluator notes */}
      {eval_data?.evaluator_notes && (
        <div className="card" style={{ padding: "14px 20px" }}>
          <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.7 }}>{eval_data.evaluator_notes}</p>
          <span className={eval_data.approved_for_scripting ? "badge badge-success" : "badge badge-danger"} style={{ fontSize: 11, marginTop: 8, display: "inline-flex" }}>
            {eval_data.approved_for_scripting ? <CheckCircle2 size={10} /> : <XCircle size={10} />}
            {eval_data.approved_for_scripting ? "Approved for scripting" : "Not approved"}
          </span>
        </div>
      )}

      {/* Grade breakdown */}
      <div className="card" style={{ padding: "18px 20px" }}>
        <div className="section-rule"><span>Grade breakdown</span></div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: eval_data || audit_data
              ? bm_data
                ? "repeat(auto-fit, minmax(260px, 1fr))"
                : "minmax(0, 1fr)"
              : "minmax(0, 1fr)",
            gap: 20,
            alignItems: "start",
          }}
        >
          {(eval_data || audit_data) && (
            <div style={{ minWidth: 0 }}>
              <p className="section-label" style={{ marginTop: 8, marginBottom: 6 }}>Script Grade</p>
              <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6, marginBottom: 12 }}>
                {SCRIPT_GRADE_HELP}
              </p>

              {eval_data && (
                <div style={{ marginBottom: audit_data ? 18 : 0 }}>
                  <p className="section-label" style={{ marginBottom: 10 }}>Content quality</p>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {evalCriteria.map(({ key, label }) => {
                      const score = eval_data.criteria[key] ?? 0;
                      return (
                        <div key={key}>
                          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                            <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{label}</span>
                            <span style={{ fontSize: 12, fontWeight: 500 }}>{(score * 100).toFixed(0)}%</span>
                          </div>
                          <div className="progress-track"><div className="progress-fill" style={{ width: `${score * 100}%` }} /></div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {audit_data && (
                <div>
                  <p className="section-label" style={{ marginBottom: 10 }}>Final script audit</p>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {auditCriteria.map(({ key, label }) => {
                      const score = audit_data.criteria[key] ?? 0;
                      return (
                        <div key={key}>
                          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                            <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{label}</span>
                            <span style={{ fontSize: 12, fontWeight: 500 }}>{(score * 100).toFixed(0)}%</span>
                          </div>
                          <div className="progress-track"><div className="progress-fill" style={{ width: `${score * 100}%` }} /></div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {bm_data && (
            <div style={{ minWidth: 0 }}>
              <p className="section-label" style={{ marginTop: 8, marginBottom: 6 }}>Benchmark Grade</p>
              <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6, marginBottom: 12 }}>
                {BENCHMARK_GRADE_HELP}
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {bmMetrics.map(({ key, label }) => {
                  const score = (bm_data[key] as number) ?? 0;
                  return (
                    <div key={key}>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                        <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{label}</span>
                        <span style={{ fontSize: 12, fontWeight: 500 }}>{(score * 100).toFixed(0)}%</span>
                      </div>
                      <div className="progress-track"><div className="progress-fill" style={{ width: `${score * 100}%` }} /></div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Strengths + weaknesses */}
      {(allStrengths.length > 0 || allWeaknesses.length > 0) && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {allStrengths.length > 0 && (
            <div className="card" style={{ padding: "16px 18px" }}>
              <p className="section-label" style={{ color: "var(--color-success)" }}>Strengths</p>
              <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
                {allStrengths.map((s, i) => (
                  <li key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>
                    <CheckCircle2 size={13} style={{ color: "var(--color-success)", flexShrink: 0, marginTop: 1 }} />
                    {sanitizeBenchmarkText(s)}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {allWeaknesses.length > 0 && (
            <div className="card" style={{ padding: "16px 18px" }}>
              <p className="section-label" style={{ color: "var(--color-danger)" }}>Areas to improve</p>
              <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
                {allWeaknesses.map((w, i) => (
                  <li key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>
                    <XCircle size={13} style={{ color: "var(--color-danger)", flexShrink: 0, marginTop: 1 }} />
                    {sanitizeBenchmarkText(w)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Best-in-class comparison */}
      {bc && (
        <div className="card" style={{ padding: "18px 20px" }}>
          <div className="section-rule"><span>Best-in-class comparison</span></div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {bc.alignment_summary && (
              <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
                {sanitizeBenchmarkText(bc.alignment_summary)}
              </p>
            )}
            {([
              ["Hook", bc.hook_comparison],
              ["Structure", bc.structure_comparison],
              ["Data Density", bc.data_density_comparison],
              ["Closing", bc.closing_comparison],
            ] as [string, string][]).filter(([, v]) => v).map(([label, value]) => (
              <div key={label}>
                <p style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-tertiary)", marginBottom: 3 }}>{label}</p>
                <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>{sanitizeBenchmarkText(value)}</p>
              </div>
            ))}
            {bc.best_in_class_takeaways.length > 0 && (
              <div>
                <p className="section-label" style={{ marginBottom: 8 }}>Takeaways</p>
                <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
                  {bc.best_in_class_takeaways.map((item, i) => (
                    <li key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>
                      <CheckCircle2 size={13} style={{ color: "var(--color-success)", flexShrink: 0, marginTop: 1 }} />
                      {sanitizeBenchmarkText(item)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function BenchmarkUnavailablePanel() {
  return (
    <div className="card" style={{ padding: "24px 26px", maxWidth: 560 }}>
      <div className="section-rule"><span>Benchmark unavailable</span></div>
      <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.7, marginBottom: 14 }}>
        This story finished without a benchmark score. That usually means the benchmark corpus
        has not been built yet, the cache is missing, or the library needs a refresh.
      </p>
      <Link href="/benchmarking" className="btn-secondary" style={{ textDecoration: "none" }}>
        Open Benchmarking Admin
      </Link>
    </div>
  );
}

const BENCHMARK_SOURCE_NAMES = /\b(Business Insider|CNBC Make It|CNBC Making It|Vox|Johnny Harris|BI)\b/gi;

function sanitizeBenchmarkText(value: string) {
  return value.replace(BENCHMARK_SOURCE_NAMES, "benchmark corpus");
}

/* ── Benchmark panel ── */
function BenchmarkPanel({ data, storyId }: { data: NonNullable<Story["benchmark_data"]>; storyId: string }) {
  const metrics = [
    { key: "hook_potency",              label: "Hook Potency" },
    { key: "title_formula_fit",         label: "Title Formula Fit" },
    { key: "act_architecture",          label: "Act Architecture" },
    { key: "data_density",              label: "Data Density" },
    { key: "human_narrative_placement", label: "Human Narrative" },
    { key: "tension_release_rhythm",    label: "Tension / Release" },
    { key: "closing_device",            label: "Closing Device" },
  ] as const;
  const detailByCriterion = new Map(
    (data.criterion_details ?? []).map((detail) => [detail.criterion, detail])
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Grade header */}
      <div className="card" style={{ padding: "18px 20px", display: "flex", alignItems: "center", gap: 20 }}>
        <div
          style={{
            width: 56,
            height: 56,
            background: "var(--color-action)",
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 10,
            fontSize: 24,
            fontWeight: 500,
            flexShrink: 0,
          }}
        >
          {data.grade}
        </div>
        <div>
          <p style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
            Benchmark score: {(data.bi_similarity_score * 100).toFixed(0)}%
          </p>
          <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
            {BENCHMARK_GRADE_HELP}
          </p>
          <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 6 }}>
            {GRADE_SCALE_HELP}
          </p>
          {data.stale && (
            <p style={{ fontSize: 12, color: "var(--color-warning)", marginTop: 4 }}>
              Benchmark corpus is stale. Scores may be directionally useful but should be refreshed.
            </p>
          )}
        </div>
      </div>

      {/* Metrics */}
      <div className="card" style={{ padding: "18px 20px" }}>
        <div className="section-rule"><span>Evaluation criteria</span></div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {metrics.map(({ key, label }) => {
            const score = (data[key] as number) ?? 0;
            const detail = detailByCriterion.get(key);
            return (
              <div key={key}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{label}</span>
                  <span style={{ fontSize: 12, fontWeight: 500 }}>{(score * 100).toFixed(0)}%</span>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${score * 100}%` }} />
                </div>
                {detail && (
                  <div style={{ marginTop: 8, display: "grid", gap: 4 }}>
                    <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                      {sanitizeBenchmarkText(detail.assessment)}
                    </p>
                    {detail.improvement && (
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                        <p style={{ fontSize: 12, color: "var(--color-text-tertiary)", lineHeight: 1.5 }}>
                          <strong style={{ color: "var(--color-text-secondary)" }}>Improve:</strong>{" "}
                          {sanitizeBenchmarkText(detail.improvement)}
                        </p>
                        <Link
                          href={researchHref(storyId, detail.improvement)}
                          className="btn-ghost"
                          style={{ textDecoration: "none", flexShrink: 0 }}
                        >
                          Research
                        </Link>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Strengths + gaps */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div className="card" style={{ padding: "16px 18px" }}>
          <p className="section-label" style={{ color: "var(--color-success)" }}>Strengths</p>
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
            {data.strengths.map((s, i) => (
              <li key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>
                <CheckCircle2 size={13} style={{ color: "var(--color-success)", flexShrink: 0, marginTop: 1 }} />
                {sanitizeBenchmarkText(s)}
              </li>
            ))}
          </ul>
        </div>
        <div className="card" style={{ padding: "16px 18px" }}>
          <p className="section-label" style={{ color: "var(--color-danger)" }}>Gaps</p>
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
            {data.gaps.map((g, i) => (
              <li key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>
                <XCircle size={13} style={{ color: "var(--color-danger)", flexShrink: 0, marginTop: 1 }} />
                {sanitizeBenchmarkText(g)}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {data.status_notes && data.status_notes.length > 0 && (
        <div className="card" style={{ padding: "16px 18px" }}>
          <p className="section-label" style={{ marginBottom: 8 }}>Corpus notes</p>
          <ul style={{ margin: 0, paddingLeft: 16 }}>
            {data.status_notes.map((note, i) => (
              <li key={i} style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                {sanitizeBenchmarkText(note)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

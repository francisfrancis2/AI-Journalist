"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { Loader2, ArrowLeft, Download, CheckCircle2, XCircle, ChevronDown, ChevronUp } from "lucide-react";
import { apiClient, type Story, type FinalScript } from "@/lib/api";

type Tab = "script" | "evaluation" | "benchmark";

export default function ResultsPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
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

  const handleDownload = async () => {
    if (!script) return;
    setDownloading(true);
    try { downloadScriptFile(script); } finally { setDownloading(false); }
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

  const TABS: { id: Tab; label: string; available: boolean }[] = [
    { id: "script",     label: "Script",       available: isComplete },
    { id: "evaluation", label: "Evaluation",   available: !!story.evaluation_data },
    { id: "benchmark",  label: "BI Benchmark", available: !!story.benchmark_data },
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
                    <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                      Quality <strong style={{ color: "var(--color-text-primary)" }}>{(story.quality_score * 100).toFixed(0)}%</strong>
                    </span>
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
                    <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                      Grade <strong style={{ color: "var(--color-text-primary)" }}>{story.benchmark_data.grade}</strong>
                    </span>
                  )}
                </div>
              )}
            </div>

            {isComplete && script && (
              <button onClick={handleDownload} disabled={downloading} className="btn-secondary" style={{ flexShrink: 0, marginLeft: 16 }}>
                {downloading ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                Download .txt
              </button>
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
        {isComplete && tab === "script"     && script                && <ScriptPanel script={script} />}
        {isComplete && tab === "evaluation" && story.evaluation_data && <EvaluationPanel data={story.evaluation_data} />}
        {isComplete && tab === "benchmark"  && story.benchmark_data  && <BenchmarkPanel data={story.benchmark_data} />}
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
function ScriptPanel({ script }: { script: FinalScript }) {
  const [open, setOpen] = useState<number[]>([0]);
  const toggle = (i: number) => setOpen(p => p.includes(i) ? p.filter(x => x !== i) : [...p, i]);

  return (
    <div>
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
                    <span key={i} className="source-chip" title={src.url ?? undefined}>
                      {i + 1}. {src.title.slice(0, 28)}{src.title.length > 28 ? "…" : ""}
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
          {script.sections.map((section, i) => (
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
                <div style={{ padding: "0 20px 20px", borderTop: "0.5px solid var(--color-border-tertiary)" }}>
                  <div style={{ paddingTop: 16 }}>
                    <div className="section-rule"><span>Narration</span></div>
                    <p style={{ fontSize: 13, lineHeight: 1.7, marginBottom: 16 }}>{section.narration}</p>

                    {section.on_screen_text && (
                      <>
                        <div className="section-rule"><span>On screen</span></div>
                        <div className="stat-callout" style={{ marginBottom: 16 }}>
                          <p style={{ fontSize: 13 }}>{section.on_screen_text}</p>
                        </div>
                      </>
                    )}

                    {section.b_roll_suggestions.length > 0 && (
                      <>
                        <div className="section-rule"><span>B-Roll</span></div>
                        <ul style={{ margin: "0 0 16px", padding: 0, listStyle: "none" }}>
                          {section.b_roll_suggestions.map((b, j) => (
                            <li key={j} style={{ fontSize: 13, color: "var(--color-text-secondary)", padding: "3px 0", paddingLeft: 12, position: "relative" }}>
                              <span style={{ position: "absolute", left: 0, color: "var(--color-text-tertiary)" }}>·</span>
                              {b}
                            </li>
                          ))}
                        </ul>
                      </>
                    )}

                    {section.interview_cues.length > 0 && (
                      <>
                        <div className="section-rule"><span>Interview cues</span></div>
                        <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
                          {section.interview_cues.map((q, j) => (
                            <li key={j} style={{ fontSize: 13, color: "var(--color-text-secondary)", padding: "3px 0" }}>
                              <span style={{ fontWeight: 500, color: "var(--color-text-primary)", marginRight: 6 }}>Q</span>
                              {q}
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}

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

/* ── Benchmark panel ── */
function BenchmarkPanel({ data }: { data: NonNullable<Story["benchmark_data"]> }) {
  const metrics = [
    { key: "hook_potency",              label: "Hook Potency" },
    { key: "title_formula_fit",         label: "Title Formula Fit" },
    { key: "act_architecture",          label: "Act Architecture" },
    { key: "data_density",              label: "Data Density" },
    { key: "human_narrative_placement", label: "Human Narrative" },
    { key: "tension_release_rhythm",    label: "Tension / Release" },
    { key: "closing_device",            label: "Closing Device" },
  ] as const;

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
            BI Similarity: {(data.bi_similarity_score * 100).toFixed(0)}%
          </p>
          {data.closest_reference_title && (
            <p style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              Closest reference: <em>{data.closest_reference_title}</em>
            </p>
          )}
        </div>
      </div>

      {/* Metrics */}
      <div className="card" style={{ padding: "18px 20px" }}>
        <div className="section-rule"><span>Metric scores</span></div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {metrics.map(({ key, label }) => {
            const score = (data[key] as number) ?? 0;
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

      {/* Strengths + gaps */}
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
          <p className="section-label" style={{ color: "var(--color-danger)" }}>Gaps</p>
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
            {data.gaps.map((g, i) => (
              <li key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>
                <XCircle size={13} style={{ color: "var(--color-danger)", flexShrink: 0, marginTop: 1 }} />
                {g}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function downloadScriptFile(script: FinalScript) {
  const lines: string[] = [
    script.title.toUpperCase(), "=".repeat(60), "",
    `Logline: ${script.logline}`, "", "OPENING HOOK", script.opening_hook, "",
  ];
  for (const s of script.sections) {
    lines.push("─".repeat(60), `ACT ${s.section_number}: ${s.title.toUpperCase()}`, "", "NARRATION:", s.narration, "");
    if (s.on_screen_text) lines.push(`[ON SCREEN]: ${s.on_screen_text}`, "");
    if (s.b_roll_suggestions.length) lines.push("B-ROLL:", ...s.b_roll_suggestions.map(b => `  • ${b}`), "");
    if (s.interview_cues.length)     lines.push("INTERVIEWS:", ...s.interview_cues.map(q => `  ? ${q}`), "");
  }
  lines.push("─".repeat(60), "CLOSING STATEMENT", script.closing_statement, "", "─".repeat(60), "SOURCES",
    ...script.sources.map((s, i) => `${i + 1}. [${s.credibility?.toUpperCase()}] ${s.title} — ${s.url ?? "N/A"}`));
  const blob = new Blob([lines.join("\n")], { type: "text/plain" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url;
  a.download = `${script.title.replace(/[^a-z0-9]/gi, "_")}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}

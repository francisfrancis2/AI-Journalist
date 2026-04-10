"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { apiClient, type Story } from "@/lib/api";

const CRITERIA = [
  { key: "factual_accuracy",       label: "Factual Accuracy",       weight: "25%", desc: "All claims are well-sourced and verifiable." },
  { key: "narrative_coherence",    label: "Narrative Coherence",    weight: "20%", desc: "The story flows logically with a compelling structure." },
  { key: "audience_engagement",    label: "Audience Engagement",    weight: "20%", desc: "Holds viewer attention for the full duration." },
  { key: "source_diversity",       label: "Source Diversity",       weight: "15%", desc: "Multiple perspectives and source types are represented." },
  { key: "originality",            label: "Originality",            weight: "10%", desc: "Offers a fresh angle or new insight on the topic." },
  { key: "production_feasibility", label: "Production Feasibility", weight: "10%", desc: "Can realistically be produced with available visuals and interviews." },
] as const;

export default function EvaluationPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const { data: story, isLoading } = useQuery<Story>({
    queryKey: ["story", id],
    queryFn: () => apiClient.getStory(id),
  });

  if (isLoading) {
    return (
      <div style={{ display: "flex", height: "100%", alignItems: "center", justifyContent: "center" }}>
        <Loader2 size={20} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
      </div>
    );
  }

  const ev = story?.evaluation_data;
  if (!ev) {
    return (
      <div style={{ display: "flex", height: "100%", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12 }}>
        <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>No evaluation data available.</p>
        <button onClick={() => router.back()} className="btn-secondary">Go back</button>
      </div>
    );
  }

  const overallPct = Math.round(ev.overall_score * 100);

  return (
    <div style={{ minHeight: "100%", background: "var(--color-background-tertiary)" }}>
      {/* Topbar */}
      <div style={{ background: "var(--color-background-primary)", borderBottom: "0.5px solid var(--color-border-tertiary)", padding: "14px 28px" }}>
        <button onClick={() => router.back()} className="btn-ghost" style={{ padding: "4px 0", marginBottom: 10, fontSize: 12, gap: 4 }}>
          <ArrowLeft size={13} /> Back
        </button>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <h1 style={{ fontSize: 18, fontWeight: 500 }}>Quality Breakdown</h1>
          <span style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>{story?.title}</span>
        </div>
      </div>

      <div style={{ padding: "28px", maxWidth: 680 }}>

        {/* Overall score hero */}
        <div className="card" style={{ padding: "24px 28px", marginBottom: 20, display: "flex", alignItems: "center", gap: 24 }}>
          <div style={{ textAlign: "center", flexShrink: 0 }}>
            <div style={{ fontSize: 48, fontWeight: 600, lineHeight: 1, color: "var(--color-action)" }}>
              {overallPct}<span style={{ fontSize: 24, color: "var(--color-text-tertiary)" }}>%</span>
            </div>
            <p style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 6, textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Overall score
            </p>
          </div>
          <div style={{ width: "0.5px", height: 56, background: "var(--color-border-tertiary)", flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <span className={ev.approved_for_scripting ? "badge badge-success" : "badge badge-danger"} style={{ fontSize: 12, marginBottom: 8, display: "inline-flex" }}>
              {ev.approved_for_scripting ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
              {ev.approved_for_scripting ? "Approved for scripting" : "Below approval threshold"}
            </span>
            {ev.evaluator_notes && (
              <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>{ev.evaluator_notes}</p>
            )}
          </div>
        </div>

        {/* Weighted criteria breakdown */}
        <div className="card" style={{ padding: "20px 24px", marginBottom: 20 }}>
          <p className="section-label" style={{ marginBottom: 16 }}>Criteria breakdown</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            {CRITERIA.map(({ key, label, weight, desc }) => {
              const score: number = ev.criteria?.[key] ?? 0;
              const pct = Math.round(score * 100);
              const color = pct >= 80 ? "var(--color-success)" : pct >= 60 ? "var(--color-action)" : "var(--color-danger)";
              return (
                <div key={key}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
                    <div>
                      <span style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text-primary)" }}>{label}</span>
                      <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginLeft: 6 }}>weight {weight}</span>
                    </div>
                    <span style={{ fontSize: 14, fontWeight: 600, color }}>{pct}%</span>
                  </div>
                  <div className="progress-track" style={{ marginBottom: 4 }}>
                    <div className="progress-fill" style={{ width: `${pct}%`, background: color }} />
                  </div>
                  <p style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{desc}</p>
                </div>
              );
            })}
          </div>
        </div>

        {/* Strengths + weaknesses */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 20 }}>
          <div className="card" style={{ padding: "16px 18px" }}>
            <p className="section-label" style={{ color: "var(--color-success)", marginBottom: 10 }}>Strengths</p>
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
              {(ev.strengths ?? []).map((s: string, i: number) => (
                <li key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                  <CheckCircle2 size={13} style={{ color: "var(--color-success)", flexShrink: 0, marginTop: 2 }} />
                  {s}
                </li>
              ))}
            </ul>
          </div>
          <div className="card" style={{ padding: "16px 18px" }}>
            <p className="section-label" style={{ color: "var(--color-danger)", marginBottom: 10 }}>Areas to improve</p>
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
              {(ev.weaknesses ?? []).map((w: string, i: number) => (
                <li key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                  <XCircle size={13} style={{ color: "var(--color-danger)", flexShrink: 0, marginTop: 2 }} />
                  {w}
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Improvement suggestions */}
        {(ev.improvement_suggestions ?? []).length > 0 && (
          <div className="card" style={{ padding: "16px 18px" }}>
            <p className="section-label" style={{ marginBottom: 10 }}>Suggestions</p>
            <ol style={{ margin: 0, padding: "0 0 0 16px", display: "flex", flexDirection: "column", gap: 6 }}>
              {ev.improvement_suggestions.map((s: string, i: number) => (
                <li key={i} style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>{s}</li>
              ))}
            </ol>
          </div>
        )}

      </div>
    </div>
  );
}

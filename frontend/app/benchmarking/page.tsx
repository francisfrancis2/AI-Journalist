"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format, formatDistanceToNow } from "date-fns";
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Database,
  ExternalLink,
  Gauge,
  Loader2,
  RefreshCw,
  Sparkles,
  Wrench,
} from "lucide-react";
import {
  apiClient,
  type BenchmarkAdminStatus,
  type BenchmarkData,
  type BenchmarkLibraryStatus,
  type BenchmarkReferenceDoc,
  type Story,
  type ScriptVersion,
} from "@/lib/api";
import { getUserInfo } from "@/lib/auth";

const BENCHMARK_GRADE_HELP =
  "Benchmark grade measures how closely the story matches the benchmark corpus in hook, structure, data density, human narrative, and closing pattern.";
const GRADE_SCALE_HELP = "Letter scale: A 85%+, B 70-84%, C 55-69%, D below 55%.";

function formatTimestamp(value: string | null) {
  if (!value) return "Not available";
  const date = new Date(value);
  return `${format(date, "MMM d, yyyy • HH:mm")} (${formatDistanceToNow(date, { addSuffix: true })})`;
}

function libraryHealthBadge(library: BenchmarkLibraryStatus) {
  if (!library.implemented) return <span className="badge badge-neutral">Planned</span>;
  if (!library.available)   return <span className="badge badge-danger">Unavailable</span>;
  if (library.stale)        return <span className="badge badge-warning">Needs refresh</span>;
  return <span className="badge badge-success">Healthy</span>;
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = pct >= 75 ? "var(--color-success)" : pct >= 50 ? "var(--color-action)" : "var(--color-danger)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div style={{ flex: 1, height: 4, borderRadius: 2, background: "var(--color-border-tertiary)", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 2, transition: "width 0.4s ease" }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 500, color, minWidth: 32, textAlign: "right" }}>{pct}%</span>
    </div>
  );
}

function CriterionCard({
  criterion,
  checked,
  onCheck,
}: {
  criterion: NonNullable<BenchmarkData["criterion_details"]>[number];
  checked: boolean;
  onCheck: (rec: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const score = Math.round(criterion.score * 100);
  const isWeak = score < 70;
  const rec = criterion.improvement || criterion.assessment;

  return (
    <div
      className="card"
      style={{
        padding: "14px 16px",
        borderLeft: `3px solid ${isWeak ? "var(--color-danger)" : score >= 80 ? "var(--color-success)" : "var(--color-action)"}`,
        background: checked ? "rgba(28, 38, 168, 0.04)" : undefined,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 10 }}>
        <input
          type="checkbox"
          checked={checked}
          onChange={() => onCheck(rec)}
          style={{ marginTop: 3, cursor: "pointer", accentColor: "var(--color-action)", flexShrink: 0 }}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <span style={{ fontSize: 13, fontWeight: 500 }}>{criterion.label}</span>
            {isWeak && <span className="badge badge-danger" style={{ fontSize: 10 }}>Needs work</span>}
          </div>
          <ScoreBar score={criterion.score} />
        </div>
      </div>

      <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6, marginBottom: criterion.improvement ? 8 : 0 }}>
        {criterion.assessment}
      </p>

      {criterion.improvement && (
        <>
          <button
            type="button"
            onClick={() => setExpanded(e => !e)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              fontSize: 11,
              color: "var(--color-action)",
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 0,
              fontWeight: 500,
            }}
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {expanded ? "Hide suggestion" : "Show improvement suggestion"}
          </button>
          {expanded && (
            <p style={{
              marginTop: 8,
              fontSize: 12,
              color: "var(--color-text-secondary)",
              lineHeight: 1.6,
              padding: "10px 12px",
              background: "rgba(28, 38, 168, 0.04)",
              borderRadius: 8,
              border: "0.5px solid rgba(28, 38, 168, 0.12)",
            }}>
              {criterion.improvement}
            </p>
          )}
        </>
      )}
    </div>
  );
}

function ScriptVersionHistory({ versions }: { versions: ScriptVersion[] }) {
  const [expandedVersion, setExpandedVersion] = useState<number | null>(null);
  if (versions.length === 0) return null;

  return (
    <div className="card" style={{ padding: "18px 20px" }}>
      <div className="section-rule"><span>Previous script versions ({versions.length})</span></div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
        {[...versions].reverse().map((v) => (
          <div key={v.version} style={{ borderRadius: 10, border: "0.5px solid var(--color-border-tertiary)", overflow: "hidden" }}>
            <button
              onClick={() => setExpandedVersion(expandedVersion === v.version ? null : v.version)}
              style={{
                width: "100%",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "12px 14px",
                background: "none",
                border: "none",
                cursor: "pointer",
                fontFamily: "var(--font-sans)",
                textAlign: "left",
              }}
            >
              <div>
                <span style={{ fontSize: 13, fontWeight: 500 }}>Version {v.version}</span>
                {v.reason && (
                  <span style={{ fontSize: 12, color: "var(--color-text-secondary)", marginLeft: 10 }}>{v.reason}</span>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
                  {formatDistanceToNow(new Date(v.created_at), { addSuffix: true })}
                </span>
                {expandedVersion === v.version ? <ChevronUp size={13} style={{ color: "var(--color-text-tertiary)" }} /> : <ChevronDown size={13} style={{ color: "var(--color-text-tertiary)" }} />}
              </div>
            </button>
            {expandedVersion === v.version && (
              <div style={{ borderTop: "0.5px solid var(--color-border-tertiary)", padding: "14px 16px", background: "var(--color-background-secondary)" }}>
                <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 8 }}>{v.script.title}</p>
                <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6, marginBottom: 10 }}>
                  <strong>Opening hook:</strong> {v.script.opening_hook?.slice(0, 220)}{(v.script.opening_hook?.length ?? 0) > 220 ? "…" : ""}
                </p>
                <div style={{ display: "flex", gap: 14 }}>
                  {v.script.total_word_count && (
                    <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{v.script.total_word_count.toLocaleString()} words</span>
                  )}
                  {v.script.estimated_duration_minutes && (
                    <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{v.script.estimated_duration_minutes} min</span>
                  )}
                  <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{v.script.sections?.length ?? 0} sections</span>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

const EVAL_CRITERIA = [
  { key: "factual_accuracy",       label: "Factual Accuracy" },
  { key: "narrative_coherence",    label: "Narrative Coherence" },
  { key: "audience_engagement",    label: "Audience Engagement" },
  { key: "source_diversity",       label: "Source Diversity" },
  { key: "originality",            label: "Originality" },
  { key: "production_feasibility", label: "Production Feasibility" },
] as const;

const AUDIT_CRITERIA = [
  { key: "hook_strength",            label: "Hook Strength" },
  { key: "narrative_flow",           label: "Narrative Flow" },
  { key: "evidence_and_specificity", label: "Evidence & Specificity" },
  { key: "pacing",                   label: "Pacing" },
  { key: "writing_quality",          label: "Writing Quality" },
  { key: "production_readiness",     label: "Production Readiness" },
] as const;

function HeuristicRow({ label, score }: { label: string; score: number }) {
  const pct = Math.round(score * 100);
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
        <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{label}</span>
        <span style={{ fontSize: 12, fontWeight: 500 }}>{pct}%</span>
      </div>
      <ScoreBar score={score} />
    </div>
  );
}

function UserBenchmarkView() {
  const qc = useQueryClient();
  const [selectedStoryId, setSelectedStoryId] = useState<string | null>(null);
  const [selectedRecs, setSelectedRecs] = useState<Set<string>>(new Set());

  const storiesQuery = useQuery<Story[]>({
    queryKey: ["stories", "list"],
    queryFn: () => apiClient.listStories(50),
    refetchInterval: 15_000,
  });

  const completedStories = useMemo(
    () => (storiesQuery.data ?? []).filter(s => s.status === "completed"),
    [storiesQuery.data]
  );

  const selectedStoryListItem = useMemo(
    () => completedStories.find(s => s.id === selectedStoryId) ?? completedStories[0] ?? null,
    [completedStories, selectedStoryId]
  );

  // Fetch full story to get evaluation_data and script_audit_data
  const fullStoryQuery = useQuery<Story>({
    queryKey: ["story", selectedStoryListItem?.id],
    queryFn: () => apiClient.getStory(selectedStoryListItem!.id),
    enabled: !!selectedStoryListItem?.id,
  });

  const selectedStory = fullStoryQuery.data ?? selectedStoryListItem;

  const implementMutation = useMutation({
    mutationFn: ({ storyId, recs }: { storyId: string; recs: string[] }) =>
      apiClient.implementRecommendations(storyId, recs),
    onSuccess: (updated) => {
      qc.setQueryData(["stories", "list"], (old: Story[] | undefined) =>
        old ? old.map(s => s.id === updated.id ? updated : s) : [updated]
      );
      qc.setQueryData(["story", updated.id], updated);
      setSelectedRecs(new Set());
    },
  });

  const handleCheck = (rec: string) => {
    setSelectedRecs(prev => {
      const next = new Set(prev);
      if (next.has(rec)) next.delete(rec); else next.add(rec);
      return next;
    });
  };

  const handleSelectStory = (id: string) => {
    setSelectedStoryId(id);
    setSelectedRecs(new Set());
  };

  const bm = selectedStory?.benchmark_data ?? null;
  const criteria = bm?.criterion_details ?? [];
  const evalData = selectedStory?.evaluation_data ?? null;
  const auditData = selectedStory?.script_audit_data ?? null;
  const isRewriting = selectedStory && !["completed", "failed"].includes(selectedStory.status);
  const scriptVersions = selectedStory?.script_versions ?? [];

  return (
    <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 18 }}>

      {/* Story selector */}
      <div className="card" style={{ padding: "18px 20px" }}>
        <div className="section-rule"><span>Select script to benchmark</span></div>
        {storiesQuery.isLoading ? (
          <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--color-text-secondary)" }}>
            <Loader2 size={14} className="animate-spin" />Loading stories…
          </div>
        ) : completedStories.length === 0 ? (
          <div style={{ border: "0.5px dashed var(--color-border-primary)", borderRadius: 12, padding: "28px 22px", textAlign: "center", color: "var(--color-text-secondary)" }}>
            <Database size={18} style={{ margin: "0 auto 10px", color: "var(--color-text-tertiary)" }} />
            <p style={{ fontSize: 13 }}>No completed stories yet.</p>
            <p style={{ fontSize: 12, marginTop: 4 }}>Generate a script first, then return here to see its benchmark scores.</p>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {completedStories.map(story => (
              <div
                key={story.id}
                onClick={() => handleSelectStory(story.id)}
                style={{
                  padding: "12px 14px",
                  borderRadius: 10,
                  border: selectedStory?.id === story.id
                    ? "1px solid rgba(28, 38, 168, 0.28)"
                    : "0.5px solid var(--color-border-tertiary)",
                  background: selectedStory?.id === story.id
                    ? "rgba(28, 38, 168, 0.05)"
                    : "var(--color-background-primary)",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {story.title}
                  </p>
                  <p style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2 }}>
                    {formatDistanceToNow(new Date(story.created_at), { addSuffix: true })}
                  </p>
                </div>
                {story.benchmark_data?.grade && (
                  <span className="badge badge-neutral" style={{ fontWeight: 600 }}>
                    {story.benchmark_data.grade}
                  </span>
                )}
                {story.benchmark_data?.bi_similarity_score != null && (
                  <span style={{ fontSize: 12, color: "var(--color-text-secondary)", flexShrink: 0 }}>
                    {Math.round(story.benchmark_data.bi_similarity_score * 100)}%
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* No benchmark data yet */}
      {selectedStory && !bm && (
        <div style={{ border: "0.5px dashed var(--color-border-primary)", borderRadius: 12, padding: "28px 22px", textAlign: "center", color: "var(--color-text-secondary)" }}>
          <Gauge size={18} style={{ margin: "0 auto 10px", color: "var(--color-text-tertiary)" }} />
          <p style={{ fontSize: 13 }}>No benchmark scores for this script yet.</p>
          <p style={{ fontSize: 12, marginTop: 4 }}>Benchmark data is generated during the pipeline run. Try regenerating the script.</p>
        </div>
      )}

      {/* Benchmark results */}
      {selectedStory && bm && (
        <>
          {/* Overview */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
            {[
              { label: "Overall grade", value: bm.grade, sub: `Similarity score ${Math.round(bm.bi_similarity_score * 100)}%` },
              { label: "Strengths", value: bm.strengths.length, sub: bm.strengths[0] ?? "—" },
              { label: "Gaps", value: bm.gaps.length, sub: bm.gaps[0] ?? "—" },
            ].map(({ label, value, sub }) => (
              <div key={label} className="card" style={{ padding: "14px 16px" }}>
                <p className="section-label" style={{ marginBottom: 6 }}>{label}</p>
                <p style={{ fontSize: 18, fontWeight: 500 }}>{String(value)}</p>
                <p style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sub}</p>
              </div>
            ))}
          </div>
          <div className="card" style={{ padding: "12px 16px" }}>
            <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
              {BENCHMARK_GRADE_HELP}
            </p>
            <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 6 }}>
              {GRADE_SCALE_HELP}
            </p>
          </div>

          {/* Rewriting notice */}
          {isRewriting && (
            <div className="card" style={{ padding: "14px 16px", display: "flex", alignItems: "center", gap: 10, borderColor: "rgba(28, 38, 168, 0.2)", background: "rgba(28, 38, 168, 0.04)" }}>
              <Loader2 size={14} className="animate-spin" style={{ color: "var(--color-action)" }} />
              <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
                Script improvement in progress… Results will update when complete.
              </p>
            </div>
          )}

          {/* Implement bar */}
          {selectedRecs.size > 0 && (
            <div
              className="card"
              style={{
                padding: "12px 16px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                background: "rgba(28, 38, 168, 0.06)",
                borderColor: "rgba(28, 38, 168, 0.24)",
                position: "sticky",
                top: 12,
                zIndex: 10,
              }}
            >
              <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
                <strong style={{ color: "var(--color-text-primary)" }}>{selectedRecs.size}</strong> recommendation{selectedRecs.size !== 1 ? "s" : ""} selected
              </p>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  onClick={() => setSelectedRecs(new Set())}
                  className="btn-ghost"
                  style={{ fontSize: 12 }}
                >
                  Clear
                </button>
                <button
                  onClick={() => implementMutation.mutate({ storyId: selectedStory.id, recs: Array.from(selectedRecs) })}
                  disabled={implementMutation.isPending}
                  className="btn-primary"
                  style={{ fontSize: 12 }}
                >
                  {implementMutation.isPending
                    ? <><Loader2 size={12} className="animate-spin" />Implementing…</>
                    : <><Sparkles size={12} />Implement selected ({selectedRecs.size})</>}
                </button>
              </div>
            </div>
          )}

          {/* All heuristics — same 3 groups as Script Evaluation tab */}

          {/* Content quality (from evaluation_data) */}
          {evalData && (
            <div className="card" style={{ padding: "16px 18px" }}>
              <div className="section-rule"><span>Content quality</span></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 8 }}>
                {EVAL_CRITERIA.map(({ key, label }) => (
                  <HeuristicRow key={key} label={label} score={evalData.criteria[key] ?? 0} />
                ))}
              </div>
            </div>
          )}

          {/* Script craft (from script_audit_data) */}
          {auditData && (
            <div className="card" style={{ padding: "16px 18px" }}>
              <div className="section-rule"><span>Script craft</span></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 8 }}>
                {AUDIT_CRITERIA.map(({ key, label }) => (
                  <HeuristicRow key={key} label={label} score={auditData.criteria[key] ?? 0} />
                ))}
              </div>
            </div>
          )}

          {/* Benchmark metrics — with checkboxes */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div className="section-rule" style={{ flex: 1 }}><span>Benchmark metrics</span></div>
              <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginLeft: 12, flexShrink: 0 }}>
                Check to implement
              </p>
            </div>
            {criteria.length > 0 ? criteria.map(c => (
              <CriterionCard
                key={c.criterion}
                criterion={c}
                checked={selectedRecs.has(c.improvement || c.assessment)}
                onCheck={handleCheck}
              />
            )) : (
              /* Fallback when criterion_details not populated */
              [
                { key: "hook_potency",              label: "Hook Potency",           score: bm.hook_potency },
                { key: "title_formula_fit",          label: "Title Formula Fit",      score: bm.title_formula_fit },
                { key: "act_architecture",           label: "Act Architecture",       score: bm.act_architecture },
                { key: "data_density",               label: "Data Density",           score: bm.data_density },
                { key: "human_narrative_placement",  label: "Human Narrative",        score: bm.human_narrative_placement },
                { key: "tension_release_rhythm",     label: "Tension / Release",      score: bm.tension_release_rhythm },
                { key: "closing_device",             label: "Closing Device",         score: bm.closing_device },
              ].map(({ key, label, score }) => (
                <div key={key} className="card" style={{ padding: "14px 16px" }}>
                  <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 8 }}>{label}</p>
                  <ScoreBar score={score} />
                </div>
              ))
            )}
          </div>

          {implementMutation.isError && (
            <div className="card" style={{ padding: "12px 14px", background: "var(--color-danger-bg)", borderColor: "#fecaca" }}>
              <p style={{ fontSize: 12, color: "var(--color-danger)" }}>
                {(implementMutation.error as Error).message}
              </p>
            </div>
          )}
        </>
      )}

      {/* Script version history */}
      {selectedStory && scriptVersions.length > 0 && (
        <ScriptVersionHistory versions={scriptVersions} />
      )}
    </div>
  );
}

const EMPTY_LIBRARIES: BenchmarkLibraryStatus[] = [];

function AdminBenchmarkView() {
  const qc = useQueryClient();
  const [selectedLibraryKey, setSelectedLibraryKey] = useState("combined");

  const statusQuery = useQuery<BenchmarkAdminStatus>({
    queryKey: ["benchmark-status"],
    queryFn: () => apiClient.getBenchmarkStatus(),
    refetchInterval: 10_000,
  });

  const referencesQuery = useQuery<BenchmarkReferenceDoc[]>({
    queryKey: ["benchmark-references", selectedLibraryKey],
    queryFn: () => apiClient.listBenchmarkReferences(25, 0, selectedLibraryKey),
    refetchInterval: statusQuery.data?.build_in_progress ? 10_000 : false,
  });

  const rebuildMutation = useMutation({
    mutationFn: () => apiClient.rebuildBenchmarkLibrary("combined"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["benchmark-status"] }),
  });

  const status = statusQuery.data;
  const libraries = status?.libraries ?? EMPTY_LIBRARIES;
  const combinedLibrary = libraries.find((l) => l.key === "combined");
  const scoringReady = Boolean(combinedLibrary?.ready_for_scoring);
  const activeLibrary = useMemo(
    () => libraries.find((l) => l.key === selectedLibraryKey) ?? libraries[0] ?? null,
    [libraries, selectedLibraryKey]
  );

  const isBusy = statusQuery.isLoading || referencesQuery.isLoading;
  const buildBusy = status?.build_in_progress || rebuildMutation.isPending;

  return (
    <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 18 }}>

      {/* System status */}
      <div className="card" style={{ padding: "18px 20px" }}>
        <div className="section-rule"><span>System status</span></div>
        {statusQuery.isLoading ? (
          <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--color-text-secondary)" }}>
            <Loader2 size={16} className="animate-spin" />
            Loading benchmark health…
          </div>
        ) : statusQuery.error ? (
          <div style={{ display: "flex", alignItems: "flex-start", gap: 10, color: "var(--color-danger)" }}>
            <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 2 }} />
            <p style={{ fontSize: 13 }}>{(statusQuery.error as Error).message}</p>
          </div>
        ) : (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
              <span className={`badge ${status?.build_in_progress || !scoringReady ? "badge-warning" : "badge-success"}`}>
                <Gauge size={11} />
                {status?.build_in_progress ? "Rebuild in progress" : scoringReady ? "Scoring service ready" : "Scoring paused"}
              </span>
              {activeLibrary && libraryHealthBadge(activeLibrary)}
            </div>
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.7, marginBottom: 0 }}>
              {status?.recommended_action}
            </p>
          </>
        )}
      </div>

      {/* Stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 12 }}>
        {[
          {
            label: "Selected corpus",
            value: activeLibrary?.label ?? "Not configured",
            sub: activeLibrary?.version != null ? `Version ${activeLibrary.version}` : "No version built yet",
          },
          {
            label: "Reference docs",
            value: activeLibrary?.doc_count ?? 0,
            sub: `Recommended minimum ${activeLibrary?.minimum_doc_count ?? 20}`,
          },
          {
            label: "Freshness",
            value: activeLibrary?.stale ? "Stale" : activeLibrary?.available ? "Fresh" : "Missing",
            sub: formatTimestamp(activeLibrary?.built_at ?? null),
          },
          {
            label: "Last build",
            value: status?.build_in_progress ? "Running" : status?.last_build_finished_at ? "Completed" : "None yet",
            sub: formatTimestamp(status?.last_build_finished_at ?? status?.last_build_started_at ?? null),
          },
        ].map(({ label, value, sub }) => (
          <div key={label} className="card" style={{ padding: "14px 16px" }}>
            <p className="section-label" style={{ marginBottom: 6 }}>{label}</p>
            <p style={{ fontSize: 18, fontWeight: 500 }}>{String(value)}</p>
            <p style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 4 }}>{sub}</p>
          </div>
        ))}
      </div>

      {/* Corpus rebuild */}
      <div className="card" style={{ padding: "18px 20px" }}>
        <div className="section-rule"><span>Corpus rebuild</span></div>
        <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.7, marginBottom: 14 }}>
          Refresh up to 25% of each healthy corpus with the newest usable videos from Business Insider, CNBC Make It, Vox, and Johnny Harris. Missing corpora still run a full build.
        </p>
        <button
          onClick={() => rebuildMutation.mutate()}
          className="btn-primary"
          disabled={buildBusy}
        >
          {buildBusy
            ? <><Loader2 size={13} className="animate-spin" />{status?.build_in_progress ? "Refresh running…" : "Starting…"}</>
            : <><RefreshCw size={13} />Refresh benchmark corpus</>}
        </button>
        {rebuildMutation.isError && (
          <p style={{ fontSize: 12, color: "var(--color-danger)", marginTop: 10 }}>
            {(rebuildMutation.error as Error).message}
          </p>
        )}
        {status?.last_build_error && (
          <div style={{ marginTop: 14, padding: "12px 14px", borderRadius: 10, background: "var(--color-danger-bg)", color: "var(--color-danger)" }}>
            <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 4 }}>Last rebuild failed</p>
            <p style={{ fontSize: 12, lineHeight: 1.6 }}>{status.last_build_error}</p>
          </div>
        )}
      </div>

      {/* Library catalog */}
      <div className="card" style={{ padding: "18px 20px" }}>
        <div className="section-rule"><span>Corpus catalog</span></div>
        <div style={{ display: "grid", gap: 12 }}>
          {libraries.map((library) => (
            <div
              key={library.key}
              onClick={() => setSelectedLibraryKey(library.key)}
              style={{
                padding: "14px 16px",
                borderRadius: 12,
                border: selectedLibraryKey === library.key
                  ? "1px solid rgba(28, 38, 168, 0.28)"
                  : "0.5px solid var(--color-border-tertiary)",
                background: selectedLibraryKey === library.key
                  ? "rgba(28, 38, 168, 0.05)"
                  : "var(--color-background-primary)",
                cursor: "pointer",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 8 }}>
                <div>
                  <p style={{ fontSize: 13, fontWeight: 500 }}>{library.label}</p>
                  <p style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 3 }}>{library.description}</p>
                </div>
                {libraryHealthBadge(library)}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: library.notes.length ? 8 : 0 }}>
                {library.version != null && <span className="badge badge-neutral">v{library.version}</span>}
                {library.doc_count > 0 && <span className="badge badge-neutral">{library.doc_count} refs</span>}
                {!library.cache_exists && library.implemented && library.available && (
                  <span className="badge badge-warning">Cache missing</span>
                )}
              </div>
              {library.notes.length > 0 && (
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {library.notes.map((note, i) => (
                    <li key={i} style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>{note}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Reference docs table */}
      <div className="card" style={{ padding: "18px 20px" }}>
        <div className="section-rule">
          <span>Reference docs — {activeLibrary?.label ?? selectedLibraryKey}</span>
        </div>
        {isBusy ? (
          <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--color-text-secondary)" }}>
            <Loader2 size={16} className="animate-spin" />Loading…
          </div>
        ) : referencesQuery.error ? (
          <p style={{ fontSize: 12, color: "var(--color-danger)" }}>{(referencesQuery.error as Error).message}</p>
        ) : (referencesQuery.data?.length ?? 0) === 0 ? (
          <div style={{ border: "0.5px dashed var(--color-border-primary)", borderRadius: 12, padding: "28px 22px", textAlign: "center", color: "var(--color-text-secondary)" }}>
            <Database size={18} style={{ margin: "0 auto 10px", color: "var(--color-text-tertiary)" }} />
            <p style={{ fontSize: 13, marginBottom: 4 }}>No benchmark references stored yet.</p>
            <p style={{ fontSize: 12 }}>Trigger a corpus rebuild from the Admin Console.</p>
          </div>
        ) : (
          <div className="card" style={{ overflow: "hidden", borderRadius: 10 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 110px 110px 90px 160px", gap: 8, padding: "10px 14px", background: "var(--color-background-secondary)", borderBottom: "0.5px solid var(--color-border-tertiary)", fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              <span>Reference</span>
              <span style={{ textAlign: "right" }}>Views</span>
              <span style={{ textAlign: "right" }}>Likes</span>
              <span style={{ textAlign: "right" }}>Transcript</span>
              <span style={{ textAlign: "right" }}>Imported</span>
            </div>
            {referencesQuery.data?.map((doc, index) => {
              const isLast = index === (referencesQuery.data?.length ?? 0) - 1;
              return (
                <div key={doc.id} className="table-row" style={{ display: "grid", gridTemplateColumns: "1fr 110px 110px 90px 160px", gap: 8, padding: "12px 14px", alignItems: "center", borderBottom: isLast ? "none" : "0.5px solid var(--color-border-tertiary)" }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <p style={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 0 }}>{doc.title}</p>
                      <a href={`https://www.youtube.com/watch?v=${doc.youtube_id}`} target="_blank" rel="noopener noreferrer" className="btn-ghost" style={{ padding: 0 }}>
                        <ExternalLink size={13} />
                      </a>
                    </div>
                    <p style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 4 }}>{Math.round(doc.duration_seconds / 60)} min documentary</p>
                  </div>
                  <span style={{ fontSize: 12, textAlign: "right" }}>{doc.view_count.toLocaleString()}</span>
                  <span style={{ fontSize: 12, textAlign: "right" }}>{doc.like_count.toLocaleString()}</span>
                  <span style={{ textAlign: "right" }}>
                    <span className={`badge ${doc.has_transcript ? "badge-success" : "badge-warning"}`}>{doc.has_transcript ? "Yes" : "Missing"}</span>
                  </span>
                  <span style={{ fontSize: 12, color: "var(--color-text-secondary)", textAlign: "right" }}>{formatTimestamp(doc.created_at)}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="card" style={{ padding: "16px 18px", display: "flex", alignItems: "flex-start", gap: 10, background: "rgba(28, 38, 168, 0.04)", borderColor: "rgba(28, 38, 168, 0.14)" }}>
        <Wrench size={16} style={{ color: "var(--color-action)", flexShrink: 0, marginTop: 1 }} />
        <div>
          <p style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>What this unlocks</p>
          <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.7, marginBottom: 0 }}>
            Each library provides a distinct benchmark lens — Business Insider for data-driven BI style, CNBC Make It for personality-led storytelling, Vox for explanatory depth, and Johnny Harris for immersive investigative narrative.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function BenchmarkingPage() {
  const [isAdmin, setIsAdmin] = useState(false);
  useEffect(() => {
    setIsAdmin(getUserInfo()?.is_admin ?? false);
  }, []);

  return (
    <div style={{ minHeight: "100%", background: "var(--color-background-tertiary)" }}>
      <div
        style={{
          height: 52,
          display: "flex",
          alignItems: "center",
          padding: "0 28px",
          background: "var(--color-background-primary)",
          borderBottom: "0.5px solid var(--color-border-tertiary)",
          gap: 10,
        }}
      >
        <Gauge size={16} style={{ color: "var(--color-action)" }} />
        <span style={{ fontSize: 18, fontWeight: 500 }}>Benchmarking</span>
        <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
          {isAdmin ? "Corpus status and reference library." : "Script quality scores and heuristic improvements."}
        </span>
      </div>

      {isAdmin ? <AdminBenchmarkView /> : <UserBenchmarkView />}
    </div>
  );
}

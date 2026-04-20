"use client";

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format, formatDistanceToNow } from "date-fns";
import {
  AlertTriangle,
  Database,
  ExternalLink,
  Gauge,
  Loader2,
  RefreshCw,
  Wrench,
} from "lucide-react";
import {
  apiClient,
  type BenchmarkAdminStatus,
  type BenchmarkLibraryStatus,
  type BenchmarkReferenceDoc,
} from "@/lib/api";
import { getUserInfo } from "@/lib/auth";

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

export default function BenchmarkingPage() {
  const user = getUserInfo();
  const isAdmin = user?.is_admin ?? false;
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
  const libraries = status?.libraries ?? [];
  const combinedLibrary = libraries.find((l) => l.key === "combined");
  const scoringReady = Boolean(combinedLibrary?.ready_for_scoring);
  const activeLibrary = useMemo(
    () => libraries.find((l) => l.key === selectedLibraryKey) ?? libraries[0] ?? null,
    [libraries, selectedLibraryKey]
  );

  const isBusy = statusQuery.isLoading || referencesQuery.isLoading;
  const buildBusy = status?.build_in_progress || rebuildMutation.isPending;

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
          Corpus status and reference library.
        </span>
      </div>

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

        {/* Corpus rebuild — admin only */}
        {isAdmin && (
          <div className="card" style={{ padding: "18px 20px" }}>
            <div className="section-rule"><span>Corpus rebuild</span></div>
            <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.7, marginBottom: 14 }}>
              Rebuild the complete benchmark corpus from Business Insider, CNBC Make It, Vox, and Johnny Harris reference documentaries.
            </p>
            <button
              onClick={() => rebuildMutation.mutate()}
              className="btn-primary"
              disabled={buildBusy}
            >
              {buildBusy
                ? <><Loader2 size={13} className="animate-spin" />{status?.build_in_progress ? "Rebuild running…" : "Starting…"}</>
                : <><RefreshCw size={13} />Rebuild complete benchmark corpus</>}
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
        )}

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
    </div>
  );
}

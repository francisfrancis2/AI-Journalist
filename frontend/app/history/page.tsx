"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search, Download, ChevronRight, CheckCircle2, XCircle } from "lucide-react";
import Link from "next/link";
import { format } from "date-fns";
import { apiClient, type Story, type FinalScript, type StoryStatus } from "@/lib/api";

const STATUS_FILTERS: { value: StoryStatus | "all"; label: string }[] = [
  { value: "all",         label: "All" },
  { value: "completed",   label: "Completed" },
  { value: "researching", label: "In progress" },
  { value: "failed",      label: "Failed" },
];

function ToneBadge({ tone }: { tone: string }) {
  return (
    <span
      className={`badge tone-${tone}`}
      style={{ fontSize: 11, padding: "2px 8px", borderRadius: 20, border: "none" }}
    >
      {tone}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "completed") return <span className="badge badge-success" style={{ fontSize: 11 }}><CheckCircle2 size={10} /> Completed</span>;
  if (status === "failed")    return <span className="badge badge-danger"  style={{ fontSize: 11 }}><XCircle size={10} /> Failed</span>;
  return <span className="badge badge-active" style={{ fontSize: 11 }}><Loader2 size={10} className="animate-spin" /> {status.replace(/_/g, " ")}</span>;
}

export default function HistoryPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StoryStatus | "all">("all");
  const [downloading, setDownloading] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const { data: stories, isLoading } = useQuery<Story[]>({
    queryKey: ["stories", "history"],
    queryFn: () => apiClient.listStories(100),
    refetchInterval: 15_000,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteStory(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stories"] });
      setDeleteConfirm(null);
    },
  });

  const handleDownload = async (story: Story) => {
    if (story.status !== "completed") return;
    setDownloading(story.id);
    try {
      const script = await apiClient.getScript(story.id);
      downloadScriptFile(script);
    } catch { /* silent */ } finally { setDownloading(null); }
  };

  const filtered = (stories ?? []).filter(s => {
    const matchStatus = statusFilter === "all" ? true
      : statusFilter === "researching" ? !["completed", "failed"].includes(s.status)
      : s.status === statusFilter;
    const q = search.trim().toLowerCase();
    const matchSearch = !q || s.title.toLowerCase().includes(q) || s.topic.toLowerCase().includes(q);
    return matchStatus && matchSearch;
  });

  const completed = stories?.filter(s => s.status === "completed") ?? [];

  return (
    <div style={{ minHeight: "100%", background: "var(--color-background-tertiary)" }}>
      {/* Topbar */}
      <div
        style={{
          height: 52,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 28px",
          background: "var(--color-background-primary)",
          borderBottom: "0.5px solid var(--color-border-tertiary)",
        }}
      >
        <span style={{ fontSize: 18, fontWeight: 500 }}>History</span>
        <Link href="/" className="btn-primary" style={{ textDecoration: "none" }}>
          New story
        </Link>
      </div>

      <div style={{ padding: "28px" }}>

        {/* Stats row */}
        {stories && stories.length > 0 && (
          <div style={{ display: "flex", gap: 12, marginBottom: 24 }}>
            {[
              { label: "Total",     value: stories.length },
              { label: "Completed", value: completed.length },
              { label: "Failed",    value: stories.filter(s => s.status === "failed").length },
            ].map(({ label, value }) => (
              <div
                key={label}
                className="card"
                style={{ padding: "12px 16px", minWidth: 100 }}
              >
                <p style={{ fontSize: 11, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                  {label}
                </p>
                <p style={{ fontSize: 20, fontWeight: 500, color: "var(--color-text-primary)" }}>{value}</p>
              </div>
            ))}
          </div>
        )}

        {/* Filter bar */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
          {/* Search */}
          <div style={{ position: "relative", flex: "0 0 260px" }}>
            <Search size={13} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-tertiary)" }} />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search stories…"
              className="input"
              style={{ paddingLeft: 30, fontSize: 13 }}
            />
          </div>

          {/* Status filter chips */}
          <div style={{ display: "flex", gap: 4 }}>
            {STATUS_FILTERS.map(opt => (
              <button
                key={opt.value}
                onClick={() => setStatusFilter(opt.value)}
                className={`chip ${statusFilter === opt.value ? "selected" : ""}`}
                style={{ padding: "5px 12px", fontSize: 12 }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Table */}
        {isLoading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: "60px 0" }}>
            <Loader2 size={20} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
          </div>
        ) : filtered.length === 0 ? (
          <div
            className="card"
            style={{
              padding: "48px 24px",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 8,
              textAlign: "center",
            }}
          >
            <div
              style={{
                width: 36,
                height: 36,
                background: "var(--color-background-secondary)",
                borderRadius: 8,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                marginBottom: 4,
              }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <rect x="2" y="2" width="5" height="12" rx="1" fill="var(--color-border-primary)" />
                <rect x="9" y="2" width="5" height="6" rx="1" fill="var(--color-border-primary)" />
                <rect x="9" y="10" width="5" height="4" rx="1" fill="var(--color-border-primary)" />
              </svg>
            </div>
            <p style={{ fontSize: 14, fontWeight: 500 }}>
              {stories?.length === 0 ? "No stories yet" : "No matches found"}
            </p>
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
              {stories?.length === 0 ? "Create your first story to see it here." : "Try a different search or filter."}
            </p>
          </div>
        ) : (
          <div className="card" style={{ overflow: "hidden" }}>
            {/* Table header */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 110px 120px 70px 70px 80px",
                gap: 8,
                padding: "10px 16px",
                background: "var(--color-background-secondary)",
                borderBottom: "0.5px solid var(--color-border-tertiary)",
                fontSize: 11,
                fontWeight: 500,
                color: "var(--color-text-secondary)",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}
            >
              <span>Title</span>
              <span>Tone</span>
              <span>Status</span>
              <span style={{ textAlign: "right" }}>Quality</span>
              <span style={{ textAlign: "right" }}>Grade</span>
              <span style={{ textAlign: "right" }}>Actions</span>
            </div>

            {/* Rows */}
            {filtered.map((story, idx) => {
              const isLast = idx === filtered.length - 1;
              const isComplete = story.status === "completed";
              return (
                <div
                  key={story.id}
                  className="table-row"
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 110px 120px 70px 70px 80px",
                    gap: 8,
                    padding: "12px 16px",
                    alignItems: "center",
                    borderBottom: isLast ? "none" : "0.5px solid var(--color-border-tertiary)",
                  }}
                >
                  {/* Title */}
                  <div style={{ minWidth: 0 }}>
                    <Link
                      href={`/results/${story.id}`}
                      style={{
                        fontSize: 13,
                        color: "var(--color-text-primary)",
                        textDecoration: "none",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        display: "block",
                      }}
                    >
                      {story.title}
                    </Link>
                    <p
                      style={{
                        fontSize: 12,
                        color: "var(--color-text-tertiary)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        marginTop: 2,
                      }}
                    >
                      {format(new Date(story.created_at), "MMM d, yyyy")}
                    </p>
                  </div>

                  {/* Tone */}
                  <div><ToneBadge tone={story.tone} /></div>

                  {/* Status */}
                  <div><StatusBadge status={story.status} /></div>

                  {/* Quality */}
                  <div style={{ textAlign: "right" }}>
                    {story.quality_score != null
                      ? <span style={{ fontSize: 13, color: "var(--color-text-primary)" }}>{(story.quality_score * 100).toFixed(0)}%</span>
                      : <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>—</span>
                    }
                  </div>

                  {/* Grade */}
                  <div style={{ textAlign: "right" }}>
                    {story.benchmark_data
                      ? <span style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text-primary)" }}>{story.benchmark_data.grade}</span>
                      : <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>—</span>
                    }
                  </div>

                  {/* Actions — visible on row hover via opacity trick */}
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 4 }}>
                    <Link href={`/results/${story.id}`} className="btn-ghost" style={{ padding: "5px 8px" }} title="Open">
                      <ChevronRight size={13} />
                    </Link>
                    {isComplete && (
                      <button
                        onClick={() => handleDownload(story)}
                        disabled={downloading === story.id}
                        className="btn-ghost"
                        style={{ padding: "5px 8px" }}
                        title="Download"
                      >
                        {downloading === story.id
                          ? <Loader2 size={13} className="animate-spin" />
                          : <Download size={13} />
                        }
                      </button>
                    )}
                    <button
                      onClick={() => setDeleteConfirm(story.id)}
                      className="btn-ghost"
                      style={{ padding: "5px 8px", color: "var(--color-text-tertiary)" }}
                      title="Delete"
                      onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.color = "var(--color-danger)"; }}
                      onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.color = "var(--color-text-tertiary)"; }}
                    >
                      <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                        <path d="M2 3.5h10M5.5 3.5V2.5a.5.5 0 0 1 .5-.5h2a.5.5 0 0 1 .5.5v1M12 3.5l-.7 8a1 1 0 0 1-1 .9H3.7a1 1 0 0 1-1-.9L2 3.5" />
                      </svg>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Delete modal */}
      {deleteConfirm && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 50,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "rgba(0,0,0,0.25)",
            padding: 24,
          }}
        >
          <div className="card" style={{ width: "100%", maxWidth: 360, padding: 24 }}>
            <h3 style={{ fontSize: 15, fontWeight: 500, marginBottom: 8 }}>Delete this story?</h3>
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 20 }}>
              This will permanently remove the story and all associated data. This cannot be undone.
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={() => setDeleteConfirm(null)} className="btn-secondary" style={{ flex: 1 }}>
                Cancel
              </button>
              <button
                onClick={() => deleteMutation.mutate(deleteConfirm!)}
                disabled={deleteMutation.isPending}
                style={{
                  flex: 1,
                  padding: "9px 20px",
                  background: "var(--color-danger)",
                  color: "#fff",
                  border: "none",
                  borderRadius: "var(--border-radius-md)",
                  fontSize: 13,
                  fontWeight: 500,
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 6,
                  fontFamily: "var(--font-sans)",
                }}
              >
                {deleteMutation.isPending && <Loader2 size={13} className="animate-spin" />}
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
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

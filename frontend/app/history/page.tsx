"use client";

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Download,
  FileText,
  Loader2,
  Search,
  Trash2,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { format } from "date-fns";
import {
  apiClient,
  type ResearchSessionStatus,
  type ResearchSessionSummary,
  type Story,
  type StoryStatus,
} from "@/lib/api";
import { getUserInfo } from "@/lib/auth";
import { downloadScriptPdf } from "@/lib/script-export";
import { isTerminalStoryStatus, storyStatusLabel } from "@/lib/story-status";

type HistoryFilter =
  | "all"
  | "story"
  | "research"
  | "drafts"
  | "completed"
  | "in_progress"
  | "stopped"
  | "failed";

type StoryHistoryItem = {
  kind: "story";
  id: string;
  title: string;
  subtitle: string;
  createdAt: string;
  updatedAt: string;
  ownerEmail: string | null | undefined;
  status: StoryStatus;
  href: string;
  searchText: string;
  story: Story;
};

type ResearchHistoryItem = {
  kind: "research";
  id: string;
  title: string;
  subtitle: string;
  createdAt: string;
  updatedAt: string;
  ownerEmail: string | null | undefined;
  status: ResearchSessionStatus;
  href: string;
  searchText: string;
  research: ResearchSessionSummary;
};

type HistoryItem = StoryHistoryItem | ResearchHistoryItem;

const HISTORY_FILTERS: { value: HistoryFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "story", label: "New Stories" },
  { value: "research", label: "Researches" },
  { value: "drafts", label: "Drafts" },
  { value: "completed", label: "Completed" },
  { value: "in_progress", label: "In progress" },
  { value: "stopped", label: "Stopped" },
  { value: "failed", label: "Failed" },
];

function StoryStatusBadge({ status }: { status: StoryStatus }) {
  if (status === "ideating") return <span className="badge badge-neutral" style={{ fontSize: 11 }}>Ideating</span>;
  if (status === "completed") return <span className="badge badge-success" style={{ fontSize: 11 }}><CheckCircle2 size={10} /> Completed</span>;
  if (status === "failed") return <span className="badge badge-danger" style={{ fontSize: 11 }}><XCircle size={10} /> Failed</span>;
  if (status === "angle_selection_expired") {
    return <span className="badge badge-warning" style={{ fontSize: 11 }}><AlertTriangle size={10} /> Script writing stopped</span>;
  }
  return <span className="badge badge-active" style={{ fontSize: 11 }}><Loader2 size={10} className="animate-spin" /> {storyStatusLabel(status)}</span>;
}

function ResearchStatusBadge({ status }: { status: ResearchSessionStatus }) {
  if (status === "completed") return <span className="badge badge-success" style={{ fontSize: 11 }}><CheckCircle2 size={10} /> Completed</span>;
  if (status === "failed") return <span className="badge badge-danger" style={{ fontSize: 11 }}><XCircle size={10} /> Failed</span>;
  if (status === "running") return <span className="badge badge-active" style={{ fontSize: 11 }}><Loader2 size={10} className="animate-spin" /> Running</span>;
  return <span className="badge badge-neutral" style={{ fontSize: 11 }}>Pending</span>;
}

function TypeBadge({ kind }: { kind: HistoryItem["kind"] }) {
  const isStory = kind === "story";
  return (
    <span
      className={isStory ? "badge badge-neutral" : "badge badge-active"}
      style={{ fontSize: 11, whiteSpace: "nowrap" }}
    >
      {isStory ? <FileText size={10} /> : <Search size={10} />}
      {isStory ? "New Story" : "Research"}
    </span>
  );
}

function HistoryStatusBadge({ item }: { item: HistoryItem }) {
  if (item.kind === "story") return <StoryStatusBadge status={item.status} />;
  return <ResearchStatusBadge status={item.status} />;
}

function storyHref(story: Story): string {
  const scriptGenerationRunning = story.ideation_operation_data?.type === "script_generation"
    && story.ideation_operation_data.status === "running";
  if (story.status === "completed") return `/ideation/${story.id}/script`;
  if (scriptGenerationRunning) return `/ideation/${story.id}/script`;
  if (story.status !== "ideating") return `/results/${story.id}`;
  if (story.ideation_stage === "hook") return `/ideation/${story.id}/hook`;
  if (story.ideation_stage === "chapters" || story.ideation_stage === "ready_for_script") {
    return `/ideation/${story.id}/chapters`;
  }
  return `/ideation/${story.id}/angles`;
}

function researchHref(session: ResearchSessionSummary): string {
  return `/research?id=${encodeURIComponent(session.id)}`;
}

function researchStatusLabel(status: ResearchSessionStatus): string {
  if (status === "running") return "Running";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function isItemInProgress(item: HistoryItem): boolean {
  if (item.kind === "story") return !isTerminalStoryStatus(item.status);
  return item.status === "pending" || item.status === "running";
}

function matchesHistoryFilter(item: HistoryItem, filter: HistoryFilter): boolean {
  if (filter === "all") return true;
  if (filter === "story") return item.kind === "story";
  if (filter === "research") return item.kind === "research";
  if (filter === "drafts") return item.kind === "story" && item.status === "ideating";
  if (filter === "completed") return item.status === "completed";
  if (filter === "in_progress") return isItemInProgress(item);
  if (filter === "stopped") return item.kind === "story" && item.status === "angle_selection_expired";
  if (filter === "failed") return item.status === "failed";
  return true;
}

function storyToHistoryItem(story: Story): StoryHistoryItem {
  return {
    kind: "story",
    id: story.id,
    title: story.title,
    subtitle: story.topic,
    createdAt: story.created_at,
    updatedAt: story.updated_at,
    ownerEmail: story.owner_email,
    status: story.status,
    href: storyHref(story),
    searchText: [story.title, story.topic, story.owner_email].filter(Boolean).join(" ").toLowerCase(),
    story,
  };
}

function researchToHistoryItem(session: ResearchSessionSummary): ResearchHistoryItem {
  const statusText = researchStatusLabel(session.status);
  return {
    kind: "research",
    id: session.id,
    title: session.title,
    subtitle: session.pending_prompt || `${statusText} research session`,
    createdAt: session.created_at,
    updatedAt: session.updated_at,
    ownerEmail: session.owner_email,
    status: session.status,
    href: researchHref(session),
    searchText: [session.title, session.pending_prompt, session.owner_email, statusText].filter(Boolean).join(" ").toLowerCase(),
    research: session,
  };
}

export default function HistoryPage() {
  const queryClient = useQueryClient();
  const currentUser = getUserInfo();
  const isAdmin = currentUser?.is_admin ?? false;
  const [search, setSearch] = useState("");
  const [historyFilter, setHistoryFilter] = useState<HistoryFilter>("all");
  const [downloading, setDownloading] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const {
    data: stories,
    isLoading: storiesLoading,
    error: storiesError,
    refetch: refetchStories,
  } = useQuery<Story[]>({
    queryKey: ["stories", "history"],
    queryFn: () => apiClient.listStories(100),
    refetchInterval: 15_000,
  });

  const {
    data: researchSessions,
    isLoading: researchLoading,
    error: researchError,
    refetch: refetchResearch,
  } = useQuery<ResearchSessionSummary[]>({
    queryKey: ["research-sessions"],
    queryFn: () => apiClient.listResearchSessions(),
    refetchInterval: (query) => {
      const sessions = query.state.data ?? [];
      return sessions.some((session) => session.status === "running") ? 3000 : false;
    },
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
      downloadScriptPdf(script);
    } catch {
      /* silent */
    } finally {
      setDownloading(null);
    }
  };

  const historyItems = useMemo<HistoryItem[]>(() => {
    return [
      ...(stories ?? []).map(storyToHistoryItem),
      ...(researchSessions ?? []).map(researchToHistoryItem),
    ].sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
  }, [researchSessions, stories]);

  const filtered = historyItems.filter((item) => {
    const q = search.trim().toLowerCase();
    return matchesHistoryFilter(item, historyFilter) && (!q || item.searchText.includes(q));
  });

  const completedCount = historyItems.filter((item) => item.status === "completed").length;
  const inProgressCount = historyItems.filter(isItemInProgress).length;
  const failedCount = historyItems.filter((item) => item.status === "failed").length;
  const tableColumns = isAdmin
    ? "minmax(0, 1fr) 170px 112px 136px 84px"
    : "minmax(0, 1fr) 112px 136px 84px";
  const isLoading = storiesLoading || researchLoading;
  const historyError = storiesError ?? researchError;

  const refetchHistory = () => {
    void refetchStories();
    void refetchResearch();
  };

  return (
    <div style={{ minHeight: "100%", background: "var(--color-background-tertiary)" }}>
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
        <div style={{ display: "flex", gap: 8 }}>
          <Link href="/research" className="btn-secondary" style={{ textDecoration: "none" }}>
            <Search size={13} /> Research
          </Link>
          <Link href="/" className="btn-primary" style={{ textDecoration: "none" }}>
            New story
          </Link>
        </div>
      </div>

      <div style={{ padding: "28px" }}>
        {historyItems.length > 0 && (
          <div style={{ display: "flex", gap: 12, marginBottom: 24, flexWrap: "wrap" }}>
            {[
              { label: "Total", value: historyItems.length },
              { label: "New Stories", value: stories?.length ?? 0 },
              { label: "Researches", value: researchSessions?.length ?? 0 },
              { label: "Completed", value: completedCount },
              { label: "In progress", value: inProgressCount },
              { label: "Failed", value: failedCount },
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

        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
          <div style={{ position: "relative", flex: "0 0 280px" }}>
            <Search size={13} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-tertiary)" }} />
            <input
              type="text"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search history..."
              className="input"
              style={{ paddingLeft: 30, fontSize: 13 }}
            />
          </div>

          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {HISTORY_FILTERS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setHistoryFilter(opt.value)}
                className={`chip ${historyFilter === opt.value ? "selected" : ""}`}
                style={{ padding: "5px 12px", fontSize: 12 }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: "60px 0" }}>
            <Loader2 size={20} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
          </div>
        ) : historyError ? (
          <div
            className="card"
            role="alert"
            style={{
              padding: "32px 24px",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 10,
              textAlign: "center",
            }}
          >
            <XCircle size={20} style={{ color: "var(--color-danger, #b42318)" }} />
            <p style={{ fontSize: 14, fontWeight: 500 }}>Could not load history</p>
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)", maxWidth: 420 }}>
              {historyError instanceof Error ? historyError.message : "Unknown error"}.
              {" "}If this keeps happening, try signing out and back in.
            </p>
            <button
              type="button"
              onClick={refetchHistory}
              className="btn-secondary"
              style={{ marginTop: 4 }}
            >
              Try again
            </button>
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
              <FileText size={16} style={{ color: "var(--color-text-tertiary)" }} />
            </div>
            <p style={{ fontSize: 14, fontWeight: 500 }}>
              {historyItems.length === 0 ? "No history yet" : "No matches found"}
            </p>
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
              {historyItems.length === 0 ? "Create a story or research session to see it here." : "Try a different search or filter."}
            </p>
          </div>
        ) : (
          <div className="card" style={{ overflow: "hidden" }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: tableColumns,
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
              {isAdmin && <span>User</span>}
              <span>Type</span>
              <span>Status</span>
              <span style={{ textAlign: "right" }}>Actions</span>
            </div>

            {filtered.map((item, idx) => {
              const isLast = idx === filtered.length - 1;
              const isCompleteStory = item.kind === "story" && item.status === "completed";
              return (
                <div
                  key={`${item.kind}-${item.id}`}
                  className="table-row"
                  style={{
                    display: "grid",
                    gridTemplateColumns: tableColumns,
                    gap: 8,
                    padding: "12px 16px",
                    alignItems: "center",
                    borderBottom: isLast ? "none" : "0.5px solid var(--color-border-tertiary)",
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <Link
                      href={item.href}
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
                      {item.title}
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
                      {format(new Date(item.updatedAt), "MMM d, yyyy")} · {item.subtitle}
                    </p>
                  </div>

                  {isAdmin && (
                    <div style={{ minWidth: 0 }}>
                      <span
                        style={{
                          fontSize: 12,
                          color: "var(--color-text-secondary)",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          display: "block",
                        }}
                      >
                        {item.ownerEmail ?? "Unassigned"}
                      </span>
                    </div>
                  )}

                  <div><TypeBadge kind={item.kind} /></div>
                  <div><HistoryStatusBadge item={item} /></div>

                  <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 4 }}>
                    <Link href={item.href} className="btn-ghost" style={{ padding: "5px 8px" }} title="Open">
                      <ChevronRight size={13} />
                    </Link>
                    {isCompleteStory && (
                      <button
                        type="button"
                        onClick={() => handleDownload(item.story)}
                        disabled={downloading === item.id}
                        className="btn-ghost"
                        style={{ padding: "5px 8px" }}
                        title="Download PDF"
                      >
                        {downloading === item.id
                          ? <Loader2 size={13} className="animate-spin" />
                          : <Download size={13} />
                        }
                      </button>
                    )}
                    {item.kind === "story" && (
                      <button
                        type="button"
                        onClick={() => setDeleteConfirm(item.id)}
                        className="btn-ghost"
                        style={{ padding: "5px 8px", color: "var(--color-text-tertiary)" }}
                        title="Delete"
                        onMouseEnter={(event) => { event.currentTarget.style.color = "var(--color-danger)"; }}
                        onMouseLeave={(event) => { event.currentTarget.style.color = "var(--color-text-tertiary)"; }}
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

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
                onClick={() => deleteMutation.mutate(deleteConfirm)}
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

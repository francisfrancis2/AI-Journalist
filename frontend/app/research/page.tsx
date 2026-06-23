"use client";

import { Suspense, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import {
  Download,
  ExternalLink,
  Loader2,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import {
  apiClient,
  type ResearchSession,
  type ResearchSessionSummary,
} from "@/lib/api";
import { downloadResearchSessionReport } from "@/lib/research-report-export";
import { downloadSourceListPdf } from "@/lib/script-export";

const RESEARCH_ESTIMATE_SECONDS = 150;
const ACTIVE_SESSION_STORAGE_KEY = "ai-journalist:active-research-session";
const RESEARCH_STAGES = [
  { at: 0, label: "Framing the research request" },
  { at: 14, label: "Launching web research" },
  { at: 36, label: "Collecting source leads and citations" },
  { at: 60, label: "Cross-checking findings" },
  { at: 80, label: "Drafting the consolidated report" },
  { at: 92, label: "Finalizing report and citation index" },
];

type LinkExportNotice = {
  tone: "success" | "error";
  text: string;
};

function formatResearchDuration(totalSeconds: number): string {
  const safeSeconds = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(safeSeconds / 60);
  const seconds = safeSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

function getStage(percent: number): string {
  return RESEARCH_STAGES.filter((stage) => percent >= stage.at).at(-1)?.label ?? RESEARCH_STAGES[0].label;
}

// ── Minimal markdown renderer for the report (headings, bullets, paragraphs, inline links) ──

function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const linkRe = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = linkRe.exec(text)) !== null) {
    if (match.index > lastIndex) {
      out.push(<span key={`t-${key++}`}>{text.slice(lastIndex, match.index)}</span>);
    }
    out.push(
      <a
        key={`a-${key++}`}
        href={match[2]}
        target="_blank"
        rel="noopener noreferrer"
        style={{ color: "var(--color-action)", textDecoration: "underline", overflowWrap: "anywhere" }}
      >
        {match[1]}
      </a>
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    out.push(<span key={`t-${key++}`}>{text.slice(lastIndex)}</span>);
  }
  return out;
}

function ReportMarkdown({ markdown }: { markdown: string }) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let listBuf: string[] = [];
  let paraBuf: string[] = [];

  const flushList = () => {
    if (listBuf.length === 0) return;
    blocks.push(
      <ul key={`ul-${blocks.length}`} style={{ paddingLeft: 20, margin: "8px 0", display: "flex", flexDirection: "column", gap: 4 }}>
        {listBuf.map((item, idx) => (
          <li key={idx} style={{ fontSize: 13, lineHeight: 1.7, color: "var(--color-text-primary)" }}>
            {renderInline(item)}
          </li>
        ))}
      </ul>
    );
    listBuf = [];
  };

  const flushPara = () => {
    if (paraBuf.length === 0) return;
    const text = paraBuf.join(" ");
    blocks.push(
      <p
        key={`p-${blocks.length}`}
        style={{ fontSize: 13, lineHeight: 1.75, margin: "6px 0", color: "var(--color-text-primary)" }}
      >
        {renderInline(text)}
      </p>
    );
    paraBuf = [];
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flushList();
      flushPara();
      continue;
    }
    if (line.startsWith("# ")) {
      flushList();
      flushPara();
      blocks.push(
        <h1 key={`h1-${blocks.length}`} style={{ fontSize: 20, fontWeight: 600, margin: "16px 0 8px" }}>
          {renderInline(line.slice(2))}
        </h1>
      );
      continue;
    }
    if (line.startsWith("## ")) {
      flushList();
      flushPara();
      blocks.push(
        <h2 key={`h2-${blocks.length}`} style={{ fontSize: 15, fontWeight: 600, margin: "14px 0 6px", color: "var(--color-text-primary)" }}>
          {renderInline(line.slice(3))}
        </h2>
      );
      continue;
    }
    if (line.startsWith("### ")) {
      flushList();
      flushPara();
      blocks.push(
        <h3 key={`h3-${blocks.length}`} style={{ fontSize: 13, fontWeight: 600, margin: "10px 0 4px", color: "var(--color-text-primary)" }}>
          {renderInline(line.slice(4))}
        </h3>
      );
      continue;
    }
    if (line.startsWith("- ") || line.startsWith("* ")) {
      flushPara();
      listBuf.push(line.slice(2));
      continue;
    }
    flushList();
    paraBuf.push(line);
  }
  flushList();
  flushPara();

  return <>{blocks}</>;
}

function TurnStatusLabel({ status }: { status: ResearchSession["turns"][number]["status"] }) {
  if (status === "running") {
    return (
      <span style={{ color: "var(--color-action)", display: "inline-flex", alignItems: "center", gap: 4 }}>
        <Loader2 size={10} className="animate-spin" /> Running
      </span>
    );
  }
  if (status === "failed") {
    return <span style={{ color: "var(--color-danger)" }}>Failed</span>;
  }
  return <span style={{ color: "var(--color-success)" }}>Completed</span>;
}

function TurnResearchOutput({
  turns,
  fallbackReportMarkdown = "",
  fallbackCitations = [],
}: {
  turns: ResearchSession["turns"];
  fallbackReportMarkdown?: string;
  fallbackCitations?: ResearchSession["citations"];
}) {
  if (turns.length === 0) return null;

  return (
    <section
      style={{
        border: "0.5px solid var(--color-border-tertiary)",
        borderRadius: 10,
        padding: "16px 18px",
        background: "var(--color-background-primary)",
      }}
    >
      <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 12 }}>Output by query</p>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {turns.map((turn, index) => {
          const canUseLegacyFallback = turns.length === 1 && index === 0;
          const turnReportMarkdown = turn.report_markdown?.trim()
            ? turn.report_markdown
            : canUseLegacyFallback
              ? fallbackReportMarkdown
              : "";
          const turnCitations = turn.citations.length > 0
            ? turn.citations
            : canUseLegacyFallback
              ? fallbackCitations
              : [];
          const hasTurnReport = Boolean(turnReportMarkdown.trim());
          const hasTurnCitations = turnCitations.length > 0;
          return (
            <article
              key={`${turn.created_at}-${index}`}
              style={{
                border: "0.5px solid var(--color-border-tertiary)",
                borderRadius: 8,
                overflow: "hidden",
                background: "var(--color-background-secondary)",
              }}
            >
              <div style={{ padding: "12px 14px", borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline", marginBottom: 6 }}>
                  <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Query {index + 1}
                  </p>
                  <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                    <TurnStatusLabel status={turn.status} />
                    {turn.completed_at && <span>{formatDistanceToNow(new Date(turn.completed_at), { addSuffix: true })}</span>}
                    {turn.web_search_requests > 0 && (
                      <span>{turn.web_search_requests} web {turn.web_search_requests === 1 ? "search" : "searches"}</span>
                    )}
                  </p>
                </div>
                <p style={{ fontSize: 13, color: "var(--color-text-primary)", lineHeight: 1.55, whiteSpace: "pre-wrap" }}>
                  {turn.prompt}
                </p>
                {turn.error_message && (
                  <p style={{ fontSize: 12, color: "var(--color-danger)", marginTop: 8 }}>
                    {turn.error_message}
                  </p>
                )}
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(180px, 260px)", gap: 0 }}>
                <div
                  style={{
                    padding: "14px 16px",
                    maxHeight: 320,
                    overflowY: "auto",
                    background: "#fff",
                    borderRight: "0.5px solid var(--color-border-tertiary)",
                  }}
                >
                  {hasTurnReport ? (
                    <ReportMarkdown markdown={turnReportMarkdown} />
                  ) : (
                    <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
                      {turn.status === "running"
                        ? "This query is still running. Its report output will appear here when complete."
                        : "No separate report output was captured for this query."}
                    </p>
                  )}
                </div>
                <div style={{ padding: "14px 14px", maxHeight: 320, overflowY: "auto", background: "var(--color-background-primary)" }}>
                  <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 9 }}>Links for this query</p>
                  {hasTurnCitations ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                      {turnCitations.map((citation, citationIndex) => (
                        <a
                          key={`${citation.url}-${citationIndex}`}
                          href={citation.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{
                            fontSize: 12,
                            color: "var(--color-action)",
                            display: "flex",
                            gap: 6,
                            alignItems: "baseline",
                            overflowWrap: "anywhere",
                            textDecoration: "none",
                            lineHeight: 1.45,
                          }}
                        >
                          <span style={{ color: "var(--color-text-tertiary)", flexShrink: 0 }}>{citationIndex + 1}.</span>
                          <span style={{ textDecoration: "underline", flex: 1 }}>{citation.title}</span>
                          <ExternalLink size={11} style={{ flexShrink: 0 }} />
                        </a>
                      ))}
                    </div>
                  ) : (
                    <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
                      Links will appear here when this query returns citations.
                    </p>
                  )}
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function ResearchPage() {
  return (
    <Suspense
      fallback={
        <div style={{ display: "flex", justifyContent: "center", padding: "60px 0" }}>
          <Loader2 size={20} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
        </div>
      }
    >
      <ResearchPageInner />
    </Suspense>
  );
}

function ResearchPageInner() {
  const queryClient = useQueryClient();
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
  });
  const [promptText, setPromptText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [statusNotice, setStatusNotice] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [tick, setTick] = useState(0);

  const sessionsQuery = useQuery<ResearchSessionSummary[]>({
    queryKey: ["research-sessions"],
    queryFn: () => apiClient.listResearchSessions(),
    refetchOnWindowFocus: true,
    refetchInterval: (query) => {
      const sessions = query.state.data ?? [];
      return sessions.some((session) => session.status === "running") ? 3000 : false;
    },
  });

  const sessionQuery = useQuery<ResearchSession>({
    queryKey: ["research-session", activeSessionId],
    queryFn: () => apiClient.getResearchSession(activeSessionId as string),
    enabled: !!activeSessionId,
    refetchOnWindowFocus: true,
    refetchInterval: (query) => {
      return query.state.data?.status === "running" ? 3000 : false;
    },
  });

  const createSession = useMutation({
    mutationFn: (prompt: string) => apiClient.createResearchSession(prompt),
    onMutate: () => {
      setError(null);
      setStatusNotice(null);
      setStartedAt(Date.now());
      setTick(0);
    },
    onSuccess: (session) => {
      setActiveSessionId(session.id);
      setPromptText("");
      setStatusNotice("Research accepted. The first report will appear in this session when it finishes.");
      queryClient.setQueryData(["research-session", session.id], session);
      queryClient.invalidateQueries({ queryKey: ["research-sessions"] });
    },
    onError: (err: Error) => {
      setError(err.message || "Research could not start.");
    },
    onSettled: () => {
      setStartedAt(null);
    },
  });

  const addTurn = useMutation({
    mutationFn: ({ sessionId, prompt }: { sessionId: string; prompt: string }) =>
      apiClient.addResearchSessionTurn(sessionId, prompt),
    onMutate: () => {
      setError(null);
      setStatusNotice(null);
      setStartedAt(Date.now());
      setTick(0);
    },
    onSuccess: (session) => {
      setPromptText("");
      setStatusNotice("Follow-up accepted. New findings will merge into the report and appear under Output by query when the update finishes.");
      queryClient.setQueryData(["research-session", session.id], session);
      queryClient.invalidateQueries({ queryKey: ["research-sessions"] });
    },
    onError: (err: Error) => {
      if (err.message.includes("already running")) {
        setPromptText("");
        setError(null);
        setStatusNotice("A research update is already in progress. The updated report will appear here, with its links grouped under Output by query when it finishes.");
        queryClient.invalidateQueries({ queryKey: ["research-session", activeSessionId] });
        queryClient.invalidateQueries({ queryKey: ["research-sessions"] });
        return;
      }
      setError(err.message || "Follow-up research could not complete.");
    },
    onSettled: () => {
      setStartedAt(null);
    },
  });

  const deleteSession = useMutation({
    mutationFn: (sessionId: string) => apiClient.deleteResearchSession(sessionId),
    onSuccess: (_, sessionId) => {
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
      }
      queryClient.invalidateQueries({ queryKey: ["research-sessions"] });
    },
  });

  const activeSession = sessionQuery.data ?? null;
  const isPersistedWorking = activeSession?.status === "running";
  const isWorking = createSession.isPending || addTurn.isPending || isPersistedWorking;

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (activeSessionId) {
      window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, activeSessionId);
    } else {
      window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
    }
  }, [activeSessionId]);

  useEffect(() => {
    if (activeSessionId || !sessionsQuery.data?.length) return;
    const running = sessionsQuery.data.find((session) => session.status === "running");
    if (running) setActiveSessionId(running.id);
  }, [activeSessionId, sessionsQuery.data]);

  useEffect(() => {
    if (!isWorking) return;
    const timer = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(timer);
  }, [isWorking]);

  useEffect(() => {
    setPromptText("");
    setError(null);
    setStatusNotice(null);
  }, [activeSessionId]);

  const progress = useMemo(() => {
    void tick;
    const persistedStartedAt = activeSession?.status === "running" && activeSession.operation_started_at
      ? new Date(activeSession.operation_started_at).getTime()
      : null;
    const effectiveStartedAt = persistedStartedAt || startedAt;
    if (!effectiveStartedAt) {
      return {
        elapsedSeconds: 0,
        remainingSeconds: RESEARCH_ESTIMATE_SECONDS,
        percent: 0,
        stage: RESEARCH_STAGES[0].label,
      };
    }
    const elapsedSeconds = Math.max(0, Math.round((Date.now() - effectiveStartedAt) / 1000));
    const ratio = Math.min(elapsedSeconds / RESEARCH_ESTIMATE_SECONDS, 1);
    const percent = Math.min(94, Math.max(7, Math.round(ratio * 90)));
    return {
      elapsedSeconds,
      remainingSeconds: Math.max(0, RESEARCH_ESTIMATE_SECONDS - elapsedSeconds),
      percent,
      stage: getStage(percent),
    };
  }, [activeSession?.operation_started_at, activeSession?.status, startedAt, tick]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const prompt = promptText.trim();
    if (!prompt || isWorking) return;
    if (activeSession) {
      addTurn.mutate({ sessionId: activeSession.id, prompt });
    } else {
      createSession.mutate(prompt);
    }
  };

  const handleDelete = (sessionId: string) => {
    if (!window.confirm("Delete this research session? This cannot be undone.")) return;
    deleteSession.mutate(sessionId);
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
        <div>
          <span style={{ fontSize: 18, fontWeight: 500 }}>Research Hub</span>
          <span style={{ fontSize: 12, color: "var(--color-text-secondary)", marginLeft: 10 }}>
            Run research on any topic. Follow up to extend, refine, or remove content.
          </span>
        </div>
      </div>

      <div style={{ padding: 28, display: "grid", gridTemplateColumns: "minmax(260px, 320px) minmax(0, 1fr)", gap: 18 }}>
        {/* Sessions sidebar */}
        <div className="card" style={{ padding: "16px 18px", height: "fit-content" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <span style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-secondary)" }}>
              Sessions
            </span>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setActiveSessionId(null)}
              style={{ padding: "4px 10px", fontSize: 12 }}
            >
              <Plus size={12} /> New
            </button>
          </div>
          {sessionsQuery.isLoading ? (
            <div style={{ display: "flex", justifyContent: "center", padding: "20px 0" }}>
              <Loader2 size={16} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
            </div>
          ) : (sessionsQuery.data?.length ?? 0) === 0 ? (
            <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
              No saved research yet. Start one on the right.
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {(sessionsQuery.data ?? []).map((session) => {
                const isActive = session.id === activeSessionId;
                return (
                  <div
                    key={session.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 8,
                      padding: "8px 10px",
                      borderRadius: 8,
                      border: isActive ? "0.5px solid var(--color-action)" : "0.5px solid var(--color-border-tertiary)",
                      background: isActive ? "var(--color-background-secondary)" : "transparent",
                      cursor: "pointer",
                    }}
                    onClick={() => setActiveSessionId(session.id)}
                  >
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <p
                        style={{
                          fontSize: 12,
                          fontWeight: isActive ? 500 : 400,
                          color: "var(--color-text-primary)",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {session.title}
                      </p>
                      <p style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 2, display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                        {session.status === "running" && (
                          <span style={{ color: "var(--color-action)", display: "inline-flex", alignItems: "center", gap: 3 }}>
                            <Loader2 size={9} className="animate-spin" /> Running
                          </span>
                        )}
                        {session.status === "failed" && <span style={{ color: "var(--color-danger)" }}>Failed</span>}
                        <span>{formatDistanceToNow(new Date(session.updated_at), { addSuffix: true })}</span>
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        handleDelete(session.id);
                      }}
                      className="btn-ghost"
                      style={{ padding: 4, color: "var(--color-text-tertiary)" }}
                      aria-label="Delete session"
                      disabled={session.status === "running"}
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Main pane */}
        <div className="card" style={{ padding: "20px 24px", minHeight: 480 }}>
          {!activeSessionId ? (
            <EmptyStatePrompt
              promptText={promptText}
              setPromptText={setPromptText}
              isWorking={isWorking}
              progress={progress}
              error={error}
              statusNotice={statusNotice}
              onSubmit={handleSubmit}
            />
          ) : sessionQuery.isLoading || !activeSession ? (
            <div style={{ display: "flex", justifyContent: "center", padding: "60px 0" }}>
              <Loader2 size={20} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
            </div>
          ) : (
            <ActiveSessionView
              session={activeSession}
              promptText={promptText}
              setPromptText={setPromptText}
              isWorking={isWorking}
              progress={progress}
              error={error}
              statusNotice={statusNotice}
              onSubmit={handleSubmit}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Sub-views ─────────────────────────────────────────────────────────────────

type ProgressState = {
  elapsedSeconds: number;
  remainingSeconds: number;
  percent: number;
  stage: string;
};

function ProgressIndicator({
  progress,
  label,
  description,
}: {
  progress: ProgressState;
  label: string;
  description: string;
}) {
  return (
    <div
      style={{
        border: "0.5px solid var(--color-border-tertiary)",
        borderRadius: 8,
        padding: "16px 18px",
        display: "flex",
        gap: 12,
        alignItems: "flex-start",
        color: "var(--color-text-secondary)",
        background: "var(--color-background-secondary)",
      }}
    >
      <Loader2 size={16} className="animate-spin" style={{ color: "var(--color-action)", flexShrink: 0, marginTop: 2 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline", marginBottom: 6 }}>
          <p style={{ fontSize: 12, color: "var(--color-text-primary)", fontWeight: 500 }}>{label}</p>
          <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", whiteSpace: "nowrap" }}>{progress.percent}%</p>
        </div>
        <p style={{ fontSize: 12, lineHeight: 1.6, marginBottom: 8, color: "var(--color-text-secondary)" }}>
          {description}
        </p>
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress.percent}
          style={{
            height: 6,
            borderRadius: 999,
            background: "var(--color-background-tertiary)",
            overflow: "hidden",
            border: "0.5px solid var(--color-border-tertiary)",
            marginBottom: 8,
          }}
        >
          <div
            style={{
              width: `${progress.percent}%`,
              height: "100%",
              background: "var(--color-action)",
              transition: "width 0.5s ease",
            }}
          />
        </div>
        <p style={{ fontSize: 12, lineHeight: 1.6, marginBottom: 6 }}>{progress.stage}</p>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            Estimated total {formatResearchDuration(RESEARCH_ESTIMATE_SECONDS)}
          </span>
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            Elapsed {formatResearchDuration(progress.elapsedSeconds)}
          </span>
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {progress.remainingSeconds > 0
              ? `About ${formatResearchDuration(progress.remainingSeconds)} remaining`
              : "Finalizing now"}
          </span>
        </div>
      </div>
    </div>
  );
}

function EmptyStatePrompt({
  promptText,
  setPromptText,
  isWorking,
  progress,
  error,
  statusNotice,
  onSubmit,
}: {
  promptText: string;
  setPromptText: (value: string) => void;
  isWorking: boolean;
  progress: ProgressState;
  error: string | null;
  statusNotice: string | null;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "32px 0", display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ textAlign: "center" }}>
        <p style={{ fontSize: 18, fontWeight: 500, marginBottom: 6 }}>Start a new research session</p>
        <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
          Ask anything. You can follow up to extend the research, refine it, or remove parts you don&apos;t need.
        </p>
      </div>

      {isWorking && (
        <ProgressIndicator
          progress={progress}
          label="Research accepted"
          description="The first report will appear here in this new session when the background research finishes. You can switch tabs and come back."
        />
      )}

      {statusNotice && !isWorking && (
        <p role="status" style={{ fontSize: 12, color: "var(--color-success)" }}>
          {statusNotice}
        </p>
      )}

      {error && (
        <p role="alert" style={{ fontSize: 12, color: "var(--color-danger)" }}>
          {error}
        </p>
      )}

      <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <textarea
          value={promptText}
          onChange={(event) => setPromptText(event.target.value)}
          className="input"
          rows={5}
          placeholder="e.g., Latest trends in EV battery recycling in Europe — who's leading, what's the regulatory landscape, and what's still unresolved."
          style={{ resize: "vertical", minHeight: 140, lineHeight: 1.6, fontSize: 13 }}
          disabled={isWorking}
        />
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
          <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", lineHeight: 1.5 }}>
            Be specific about geography, time window, and angle for sharper sources.
          </p>
          <button type="submit" className="btn-primary" disabled={!promptText.trim() || isWorking}>
            {isWorking ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
            Start research
          </button>
        </div>
      </form>
    </div>
  );
}

function ActiveSessionView({
  session,
  promptText,
  setPromptText,
  isWorking,
  progress,
  error,
  statusNotice,
  onSubmit,
}: {
  session: ResearchSession;
  promptText: string;
  setPromptText: (value: string) => void;
  isWorking: boolean;
  progress: ProgressState;
  error: string | null;
  statusNotice: string | null;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const [linkExportNotice, setLinkExportNotice] = useState<LinkExportNotice | null>(null);
  const isRunning = session.status === "running";
  const isFailed = session.status === "failed";
  const hasReport = Boolean(session.report_markdown.trim());
  const hasAnyTurnCitations = session.turns.some((turn) => turn.citations.length > 0);
  const shouldShowUngroupedCitationsFallback =
    session.citations.length > 0 && !hasAnyTurnCitations && session.turns.length !== 1;
  const citationExportSources = useMemo(() => {
    const seen = new Set<string>();
    return session.citations
      .filter((citation) => {
        const key = (citation.url || citation.title).trim().toLowerCase();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .map((citation) => ({
        title: citation.title,
        url: citation.url,
        type: "research citation",
        preview: citation.cited_text,
      }));
  }, [session.citations]);

  useEffect(() => {
    if (!linkExportNotice) return;
    const timer = window.setTimeout(() => setLinkExportNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [linkExportNotice]);

  const handleDownloadLinks = () => {
    if (citationExportSources.length === 0) return;
    const opened = downloadSourceListPdf(`${session.title} — Research Links`, citationExportSources);
    setLinkExportNotice(
      opened
        ? { tone: "success", text: "Opened a print-ready link list in a new tab." }
        : { tone: "error", text: "Browser blocked the export window. Please allow pop-ups and try again." }
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <p style={{ fontSize: 18, fontWeight: 500, marginBottom: 4 }}>{session.title}</p>
          <p style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {session.turns.length} {session.turns.length === 1 ? "prompt" : "prompts"} ·{" "}
            {session.citations.length} {session.citations.length === 1 ? "citation" : "citations"} ·{" "}
            {session.web_search_requests} web searches
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end", flexShrink: 0 }}>
          <button
            type="button"
            className="btn-secondary"
            onClick={handleDownloadLinks}
            disabled={citationExportSources.length === 0}
          >
            <Download size={13} /> Download all links
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => downloadResearchSessionReport(session)}
            disabled={!hasReport || isRunning}
          >
            <Download size={13} /> Download report PDF
          </button>
        </div>
      </div>

      {linkExportNotice && (
        <p
          role="status"
          style={{
            fontSize: 11,
            lineHeight: 1.5,
            color: linkExportNotice.tone === "success" ? "var(--color-success)" : "var(--color-danger)",
          }}
        >
          {linkExportNotice.text}
        </p>
      )}

      {isRunning && (
        <ProgressIndicator
          progress={progress}
          label={session.active_operation === "initial" ? "Research accepted" : "Follow-up accepted"}
          description={
            session.active_operation === "initial"
              ? "The first report will appear in this session when the background research finishes. You can switch tabs and come back."
              : "The update is running in the background. New findings will merge into the report below and appear under Output by query when complete."
          }
        />
      )}

      {statusNotice && !isRunning && (
        <p role="status" style={{ fontSize: 12, color: "var(--color-success)" }}>
          {statusNotice}
        </p>
      )}

      {hasReport ? (
        <div
          style={{
            background: "var(--color-background-primary)",
            border: "0.5px solid var(--color-border-tertiary)",
            borderRadius: 10,
            padding: "20px 24px",
            maxHeight: "min(58vh, 640px)",
            overflowY: "auto",
          }}
        >
          <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 10 }}>Consolidated report</p>
          <ReportMarkdown markdown={session.report_markdown} />
        </div>
      ) : !isRunning ? (
        <div
          style={{
            background: "var(--color-background-primary)",
            border: "0.5px solid var(--color-border-tertiary)",
            borderRadius: 10,
            padding: "20px 24px",
            color: "var(--color-text-secondary)",
            fontSize: 13,
            lineHeight: 1.6,
          }}
        >
          No report is available for this session yet.
        </div>
      ) : null}

      <TurnResearchOutput
        turns={session.turns}
        fallbackReportMarkdown={session.report_markdown}
        fallbackCitations={session.citations}
      />

      {(error || (isFailed && session.error_message)) && (
        <p role="alert" style={{ fontSize: 12, color: "var(--color-danger)" }}>
          {error || session.error_message}
        </p>
      )}

      <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <textarea
          value={promptText}
          onChange={(event) => setPromptText(event.target.value)}
          className="input"
          rows={4}
          placeholder="Refine, extend, or remove. Try 'extend to cover Asia', 'add 2025 data', or 'remove the regulatory section'."
          style={{ resize: "vertical", minHeight: 100, lineHeight: 1.6, fontSize: 13 }}
          disabled={isWorking}
        />
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
          <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", lineHeight: 1.5 }}>
            Follow-ups merge into the consolidated report — no need to repeat the original prompt.
          </p>
          <button type="submit" className="btn-primary" disabled={!promptText.trim() || isWorking}>
            {isWorking ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
            Run follow-up
          </button>
        </div>
      </form>

      {shouldShowUngroupedCitationsFallback && (
        <div
          style={{
            border: "0.5px solid var(--color-border-tertiary)",
            borderRadius: 10,
            padding: "16px 18px",
            maxHeight: 320,
            overflowY: "auto",
          }}
        >
          <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 10 }}>Ungrouped links from older saved output</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {session.citations.map((citation, index) => (
              <a
                key={`${citation.url}-${index}`}
                href={citation.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  fontSize: 12,
                  color: "var(--color-action)",
                  display: "flex",
                  gap: 6,
                  alignItems: "baseline",
                  overflowWrap: "anywhere",
                  textDecoration: "none",
                  lineHeight: 1.5,
                }}
              >
                <span style={{ color: "var(--color-text-tertiary)", flexShrink: 0 }}>{index + 1}.</span>
                <span style={{ textDecoration: "underline", flex: 1 }}>{citation.title}</span>
                <ExternalLink size={11} style={{ flexShrink: 0 }} />
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

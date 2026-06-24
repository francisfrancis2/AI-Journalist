"use client";

import { Suspense, useEffect, useMemo, useState, type FormEvent } from "react";
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
import { ReportMarkdown } from "@/components/ReportMarkdown";

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

type ResearchCitation = ResearchSession["citations"][number];
type ResearchTurn = ResearchSession["turns"][number];

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

function dedupeCitations(citations: ResearchCitation[]): ResearchCitation[] {
  const seen = new Set<string>();
  return citations.filter((citation) => {
    const key = (citation.url || citation.title).trim().toLowerCase();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function collectSessionCitations(session: ResearchSession): ResearchCitation[] {
  return dedupeCitations([
    ...session.citations,
    ...session.turns.flatMap((turn) => turn.citations),
  ]);
}

function reportForTurn(
  turn: ResearchTurn,
  index: number,
  turns: ResearchTurn[],
  fallbackReportMarkdown: string
): string {
  if (turn.report_markdown.trim()) return turn.report_markdown;

  const isLatestTurn = index === turns.length - 1;
  const fallback = fallbackReportMarkdown.trim();
  if (isLatestTurn && fallback && turn.status !== "running") {
    return fallbackReportMarkdown;
  }

  return "";
}

function ResearchReportThread({ session }: { session: ResearchSession }) {
  const hasAnyReport = Boolean(session.report_markdown.trim()) || session.turns.some((turn) => turn.report_markdown.trim());
  if (session.turns.length === 0 && !hasAnyReport) return null;

  return (
    <section
      style={{
        border: "0.5px solid var(--color-border-tertiary)",
        borderRadius: 10,
        background: "var(--color-background-primary)",
        maxHeight: "min(62vh, 720px)",
        overflowY: "auto",
      }}
    >
      <div
        style={{
          position: "sticky",
          top: 0,
          zIndex: 1,
          padding: "14px 18px 12px",
          borderBottom: "0.5px solid var(--color-border-tertiary)",
          background: "var(--color-background-primary)",
        }}
      >
        <p style={{ fontSize: 12, fontWeight: 500 }}>Report</p>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 18, padding: "18px 18px 20px" }}>
        {session.turns.map((turn, index) => {
          const turnReportMarkdown = reportForTurn(turn, index, session.turns, session.report_markdown);
          const hasTurnReport = Boolean(turnReportMarkdown.trim());
          return (
            <article
              key={`${turn.created_at}-${index}`}
              style={{ display: "flex", flexDirection: "column", gap: 10 }}
            >
              <div style={{ alignSelf: "flex-end", maxWidth: "min(82%, 720px)" }}>
                <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
                  <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: 0 }}>
                    Query {index + 1}
                  </span>
                  <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
                    <TurnStatusLabel status={turn.status} />
                  </span>
                  {turn.completed_at && (
                    <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
                      {formatDistanceToNow(new Date(turn.completed_at), { addSuffix: true })}
                    </span>
                  )}
                  {turn.web_search_requests > 0 && (
                    <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
                      {turn.web_search_requests} web {turn.web_search_requests === 1 ? "search" : "searches"}
                    </span>
                  )}
                </div>
                <p
                  style={{
                    fontSize: 13,
                    color: "var(--color-text-primary)",
                    lineHeight: 1.55,
                    whiteSpace: "pre-wrap",
                    background: "var(--color-background-secondary)",
                    border: "0.5px solid var(--color-border-tertiary)",
                    borderRadius: 8,
                    padding: "10px 12px",
                  }}
                >
                  {turn.prompt}
                </p>
                {turn.error_message && (
                  <p style={{ fontSize: 12, color: "var(--color-danger)", marginTop: 6 }}>
                    {turn.error_message}
                  </p>
                )}
              </div>

              {hasTurnReport ? (
                <div
                  style={{
                    alignSelf: "flex-start",
                    width: "100%",
                    background: "#fff",
                    border: "0.5px solid var(--color-border-tertiary)",
                    borderRadius: 8,
                    padding: "16px 18px",
                  }}
                >
                  <ReportMarkdown markdown={turnReportMarkdown} />
                </div>
              ) : turn.status === "running" ? (
                <div
                  style={{
                    alignSelf: "flex-start",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                    color: "var(--color-text-secondary)",
                    fontSize: 12,
                    background: "#fff",
                    border: "0.5px solid var(--color-border-tertiary)",
                    borderRadius: 8,
                    padding: "10px 12px",
                  }}
                >
                  <Loader2 size={13} className="animate-spin" /> Research update running
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function ResearchLinksList({ citations }: { citations: ResearchCitation[] }) {
  return (
    <section
      style={{
        border: "0.5px solid var(--color-border-tertiary)",
        borderRadius: 10,
        padding: "16px 18px",
        background: "var(--color-background-primary)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline", marginBottom: 10 }}>
        <p style={{ fontSize: 12, fontWeight: 500 }}>Research links</p>
        <p style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
          {citations.length} {citations.length === 1 ? "link" : "links"}
        </p>
      </div>
      {citations.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 7, maxHeight: 320, overflowY: "auto" }}>
          {citations.map((citation, index) => (
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
      ) : (
        <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
          Links will appear here when research returns citations.
        </p>
      )}
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
      setStatusNotice("Follow-up accepted. New findings will appear in the report thread and links list when the update finishes.");
      queryClient.setQueryData(["research-session", session.id], session);
      queryClient.invalidateQueries({ queryKey: ["research-sessions"] });
    },
    onError: (err: Error) => {
      if (err.message.includes("already running")) {
        setPromptText("");
        setError(null);
        setStatusNotice("A research update is already in progress. The next report entry and links will appear here when it finishes.");
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
  const dedupedCitations = useMemo(() => collectSessionCitations(session), [session]);
  const citationExportSources = useMemo(() => {
    return dedupedCitations
      .map((citation) => ({
        title: citation.title,
        url: citation.url,
        type: "research citation",
        preview: citation.cited_text,
      }));
  }, [dedupedCitations]);

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
            {dedupedCitations.length} {dedupedCitations.length === 1 ? "citation" : "citations"} ·{" "}
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
              : "The update is running in the background. The next report entry and links will appear here when complete."
          }
        />
      )}

      {statusNotice && !isRunning && (
        <p role="status" style={{ fontSize: 12, color: "var(--color-success)" }}>
          {statusNotice}
        </p>
      )}

      {hasReport || session.turns.length > 0 ? (
        <ResearchReportThread session={session} />
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

      <ResearchLinksList citations={dedupedCitations} />

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

    </div>
  );
}

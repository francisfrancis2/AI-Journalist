"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Bookmark,
  CheckCircle2,
  ChevronDown,
  ExternalLink,
  Lightbulb,
  Loader2,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import {
  apiClient,
  type GeneratedIdea,
  type IdeaFormat,
  type IdeaGenerationRun,
  type IdeaGenerationRunSummary,
  type IdeaState,
} from "@/lib/api";

const FORMAT_LABEL: Record<IdeaFormat, string> = {
  documentary: "Documentary",
  expert_interview: "Expert Interview Video",
};

function titleCase(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatClock(totalSeconds: number): string {
  const safe = Math.max(0, Math.round(totalSeconds));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

/**
 * Time estimate and countdown for a generation run.
 *
 * Generation is a polled background job, so the server only reports progress
 * every few seconds. Ticking locally between polls keeps the countdown moving
 * and stops the bar from looking stalled while a long phase is still working.
 * The budget shown is the server's own ceiling, so the bar filling completely
 * means the run is about to be abandoned rather than merely running late.
 */
function RunClock({ run, active }: { run: IdeaGenerationRun; active: boolean }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);

  const startedAt = run.started_at ? new Date(run.started_at).getTime() : null;
  const budget = run.estimated_total_seconds;
  if (startedAt === null || !budget) return null;

  // A finished run freezes at its real duration; only a live one tracks the clock.
  const endedAt = run.completed_at ? new Date(run.completed_at).getTime() : null;
  const elapsed = Math.max(0, ((active || endedAt === null ? now : endedAt) - startedAt) / 1000);
  const remaining = Math.max(0, budget - elapsed);
  const usedPct = Math.min(100, (elapsed / budget) * 100);

  const barColor = !active
    ? run.status === "completed"
      ? "var(--color-success)"
      : "var(--color-danger)"
    : usedPct >= 85
      ? "var(--color-warning)"
      : "var(--color-action)";

  return (
    <div style={{ marginTop: 10 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 10,
          fontSize: "var(--text-xs)",
          lineHeight: "var(--text-xs-lh)",
          color: "var(--color-text-tertiary)",
        }}
      >
        <span>
          {active ? "Elapsed" : "Took"} {formatClock(elapsed)} of {formatClock(budget)} budget
        </span>
        {active && (
          <span style={{ color: usedPct >= 85 ? "var(--color-warning)" : "var(--color-text-secondary)", fontVariantNumeric: "tabular-nums" }}>
            {remaining > 0 ? `${formatClock(remaining)} left` : "finishing\u2026"}
          </span>
        )}
      </div>
      <div
        role="progressbar"
        aria-label="Time used of the generation budget"
        aria-valuemin={0}
        aria-valuemax={Math.round(budget)}
        aria-valuenow={Math.round(Math.min(elapsed, budget))}
        aria-valuetext={`${formatClock(elapsed)} of ${formatClock(budget)} used`}
        style={{ height: 3, background: "var(--color-background-tertiary)", borderRadius: 3, marginTop: 5, overflow: "hidden" }}
      >
        <div style={{ height: "100%", width: `${usedPct}%`, background: barColor, transition: "width 1s linear" }} />
      </div>
    </div>
  );
}

// vidIQ rows carry plumbing alongside the useful numbers. Thumbnail URLs, raw
// ids and etags were being printed verbatim, which is what made the signal
// block unreadable; the title is already shown above as the signal's heading.
const SIGNAL_NOISE_KEY =
  /thumbnail|etag|kind|^id$|videoid|channelid|playlistid|url$|^videotitle$|^title$/i;

// Human labels for the keys worth showing. Anything not listed falls back to
// title-casing, so a new vidIQ field still renders sensibly.
const SIGNAL_LABEL: Record<string, string> = {
  countryvolume: "UAE searches/mo",
  estimated_monthly_search: "Searches/mo",
  viewcount: "Views",
  viewspeed: "Views/hour",
  viewsperhour: "Views/hour",
  growth: "Growth",
  competition: "Competition",
  overall: "Score",
  channeltitle: "Channel",
  channelcountry: "Channel country",
  videopublishedat: "Published",
  publishedat: "Published",
  duration: "Length",
};

function formatSignalValue(key: string, value: string | number | boolean): string {
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") {
    // vidIQ returns publish dates as unix seconds, which printed as "1790684203".
    if (/publish|date/i.test(key) && value > 1_000_000_000) {
      return new Date(value * 1000).toLocaleDateString(undefined, {
        day: "numeric",
        month: "short",
        year: "numeric",
      });
    }
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(1);
  }
  return String(value);
}

function SignalSummary({ values }: { values: Record<string, unknown> }) {
  const entries = Object.entries(values)
    .filter(([key, value]) =>
      !SIGNAL_NOISE_KEY.test(key) && ["string", "number", "boolean"].includes(typeof value))
    .slice(0, 4) as [string, string | number | boolean][];
  if (!entries.length) return null;
  return (
    <span style={{ color: "var(--color-text-tertiary)" }}>
      {entries
        .map(([key, value]) =>
          `${SIGNAL_LABEL[key.toLowerCase()] ?? titleCase(key)} ${formatSignalValue(key, value)}`)
        .join(" · ")}
    </span>
  );
}

function IdeaCard({
  idea,
  onState,
  onDelete,
}: {
  idea: GeneratedIdea;
  onState: (ideaId: string, state: IdeaState) => void;
  onDelete: (ideaId: string) => void;
}) {
  const router = useRouter();
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const details = Object.entries(idea.format_details ?? {});
  const isDismissed = idea.state === "dismissed";

  return (
    <article className="card" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 15 }}>
      <div style={{ display: "flex", gap: 14, justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 7, alignItems: "center", marginBottom: 7 }}>
            <span style={{ fontSize: "var(--text-xs)", lineHeight: "var(--text-xs-lh)", color: "var(--color-text-tertiary)" }}>#{idea.rank}</span>
            <span className="chip" style={{ padding: "3px 9px", cursor: "default" }}>{idea.sector}</span>
            <span style={{ fontSize: "var(--text-xs)", lineHeight: "var(--text-xs-lh)", color: "var(--color-success)" }}>{idea.strength}</span>
          </div>
          <h2 style={{ fontSize: "var(--text-lg)", lineHeight: "var(--text-lg-lh)", margin: 0 }}>{idea.title}</h2>
        </div>
        <div style={{ minWidth: 54, textAlign: "right" }}>
          <strong style={{ fontSize: "var(--text-xl)", lineHeight: "var(--text-xl-lh)", fontWeight: 500 }}>{Math.round(idea.score)}</strong>
          <div style={{ fontSize: "var(--text-xs)", lineHeight: "var(--text-xs-lh)", color: "var(--color-text-tertiary)" }}>/100</div>
        </div>
      </div>

      <p style={{ margin: 0, fontSize: "var(--text-sm)", lineHeight: 1.65 }}>{idea.premise}</p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
        {[
          ["Why now", idea.why_now],
          ["UAE relevance", idea.uae_relevance],
          ["Central tension", idea.central_tension],
          ["Business significance", idea.business_significance],
        ].map(([label, value]) => (
          <div key={label} style={{ padding: 11, borderRadius: 8, background: "var(--color-background-secondary)" }}>
            <div style={{ fontSize: "var(--text-xs)", lineHeight: "var(--text-xs-lh)", color: "var(--color-text-tertiary)", textTransform: "uppercase", marginBottom: 4 }}>{label}</div>
            <div style={{ fontSize: "var(--text-xs)", lineHeight: 1.55 }}>{value}</div>
          </div>
        ))}
      </div>

      {details.length > 0 && (
        <div>
          <div className="section-label" style={{ marginBottom: 7 }}>Format treatment</div>
          <div style={{ display: "grid", gap: 7 }}>
            {details.map(([label, value]) => (
              <div key={label} style={{ fontSize: "var(--text-xs)", lineHeight: "var(--text-xs-lh)" }}>
                <strong style={{ fontWeight: 500 }}>{titleCase(label)}:</strong>{" "}
                {Array.isArray(value) ? value.join(" · ") : typeof value === "object" ? JSON.stringify(value) : String(value)}
              </div>
            ))}
          </div>
        </div>
      )}

      <button
        type="button"
        className="btn-secondary"
        onClick={() => setEvidenceOpen((open) => !open)}
        style={{ alignSelf: "flex-start" }}
      >
        <ChevronDown size={13} style={{ transform: evidenceOpen ? "rotate(180deg)" : undefined }} />
        Evidence & trend signals ({idea.sources.length + idea.signals.length})
      </button>

      {evidenceOpen && (
        <div style={{ borderTop: "0.5px solid var(--color-border-tertiary)", paddingTop: 13, display: "grid", gap: 14 }}>
          <div>
            <div className="section-label" style={{ marginBottom: 7 }}>Factual sources</div>
            <div style={{ display: "grid", gap: 8 }}>
              {idea.sources.map((source) => (
                <div key={source.id} style={{ fontSize: "var(--text-xs)", lineHeight: 1.5 }}>
                  {source.url ? (
                    <a href={source.url} target="_blank" rel="noreferrer" style={{ color: "var(--color-action)" }}>
                      {source.title} <ExternalLink size={10} style={{ display: "inline" }} />
                    </a>
                  ) : <span>{source.title}</span>}
                  <div style={{ color: "var(--color-text-tertiary)" }}>
                    {source.domain ?? source.source_type}
                    {source.published_at ? ` · ${new Date(source.published_at).toLocaleDateString()}` : ""}
                    {source.is_uae_relevant ? " · UAE-relevant" : ""}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="section-label" style={{ marginBottom: 7 }}>vidIQ opportunity signals</div>
            {idea.signals.length ? (
              <div style={{ display: "grid", gap: 8 }}>
                {idea.signals.map((signal) => (
                  <div key={signal.id} style={{ fontSize: "var(--text-xs)", lineHeight: 1.5 }}>
                    <strong style={{ fontWeight: 500 }}>{signal.topic}</strong>
                    <div><SignalSummary values={signal.values} /></div>
                    {signal.geography_meaning && (
                      <div style={{ color: "var(--color-text-tertiary)" }}>{signal.geography_meaning}</div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p style={{ margin: 0, color: "var(--color-text-tertiary)", fontSize: "var(--text-xs)", lineHeight: "var(--text-xs-lh)" }}>No vidIQ signal was selected for this idea.</p>
            )}
          </div>
          {idea.verification_gaps.length > 0 && (
            // Each gap is a full sentence, so joining them with a separator
            // produced one unreadable run-on line. One claim per row instead.
            <div style={{ fontSize: "var(--text-xs)", lineHeight: "var(--text-xs-lh)" }}>
              <div className="section-label" style={{ marginBottom: 6, color: "var(--color-warning)" }}>
                Verify before broadcast ({idea.verification_gaps.length})
              </div>
              <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 4 }}>
                {idea.verification_gaps.map((gap, index) => (
                  <li key={index} style={{ color: "var(--color-text-secondary)" }}>{gap}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        {idea.format === "documentary" && (
          <button className="btn-primary" type="button" onClick={() => router.push(`/?idea=${idea.id}`)}>
            Develop in New Story
          </button>
        )}
        <button className={idea.format === "documentary" ? "btn-secondary" : "btn-primary"} type="button" onClick={() => router.push(`/research?idea=${idea.id}`)}>
          <Search size={13} /> Open in Research
        </button>
        {isDismissed ? (
          <button className="btn-ghost" type="button" onClick={() => onState(idea.id, "active")}><Undo2 size={13} /> Undo dismiss</button>
        ) : (
          <>
            <button className="btn-ghost" type="button" onClick={() => onState(idea.id, idea.state === "saved" ? "active" : "saved")}>
              <Bookmark size={13} fill={idea.state === "saved" ? "currentColor" : "none"} /> {idea.state === "saved" ? "Saved" : "Save"}
            </button>
            <button className="btn-ghost" type="button" onClick={() => onState(idea.id, "dismissed")}><X size={13} /> Dismiss</button>
            {confirmDelete ? (
              <>
                <button
                  className="btn-ghost"
                  type="button"
                  style={{ color: "var(--color-danger)" }}
                  onClick={() => onDelete(idea.id)}
                >
                  <Trash2 size={13} /> Delete permanently
                </button>
                <button className="btn-ghost" type="button" onClick={() => setConfirmDelete(false)}>Cancel</button>
              </>
            ) : (
              // Two-step: Dismiss is reversible, this is not.
              <button className="btn-ghost" type="button" onClick={() => setConfirmDelete(true)}><Trash2 size={13} /> Delete</button>
            )}
          </>
        )}
      </div>
    </article>
  );
}

export default function IdeaGeneratorPage() {
  const queryClient = useQueryClient();
  const [format, setFormat] = useState<IdeaFormat>("documentary");
  const searchParams = useSearchParams();
  // /history links here with ?run=<id>, so a run opened from the unified
  // history view is the one shown rather than whichever is newest.
  const runIdFromUrl = searchParams.get("run");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(runIdFromUrl);
  const [showDismissed, setShowDismissed] = useState(false);
  // Delete can be refused -- a run with a live worker returns 409 -- and the
  // reason has to be visible or the button looks broken.
  const [actionError, setActionError] = useState<string | null>(null);

  const runsQuery = useQuery<IdeaGenerationRunSummary[]>({
    queryKey: ["idea-generations"],
    // Own runs only: the sidebar must list exactly the runs this user can
    // open, delete and retry. Listing an admin's view of everyone's runs here
    // meant clicking delete on someone else's produced "run not found".
    queryFn: () => apiClient.listIdeaGenerations(20, true),
    refetchInterval: (query) => query.state.data?.some((run) => ["queued", "running"].includes(run.status)) ? 3000 : false,
  });
  const runQuery = useQuery<IdeaGenerationRun>({
    queryKey: ["idea-generation", selectedRunId],
    queryFn: () => apiClient.getIdeaGeneration(selectedRunId as string),
    enabled: !!selectedRunId,
    refetchInterval: (query) => ["queued", "running"].includes(query.state.data?.status ?? "") ? 3000 : false,
  });

  useEffect(() => {
    if (runIdFromUrl && runIdFromUrl !== selectedRunId) {
      setSelectedRunId(runIdFromUrl);
      return;
    }
    if (!selectedRunId && runsQuery.data?.length) setSelectedRunId(runsQuery.data[0].id);
  }, [runIdFromUrl, runsQuery.data, selectedRunId]);

  const generate = useMutation({
    mutationFn: ({ requestedFormat, previousRunId }: { requestedFormat: IdeaFormat; previousRunId?: string }) =>
      apiClient.createIdeaGeneration(requestedFormat, previousRunId, crypto.randomUUID()),
    onSuccess: (run) => {
      setSelectedRunId(run.id);
      setFormat(run.format);
      queryClient.setQueryData(["idea-generation", run.id], run);
      queryClient.invalidateQueries({ queryKey: ["idea-generations"] });
    },
  });
  const retry = useMutation({
    mutationFn: (runId: string) => apiClient.retryIdeaGeneration(runId),
    onSuccess: (run) => {
      setSelectedRunId(run.id);
      queryClient.setQueryData(["idea-generation", run.id], run);
      queryClient.invalidateQueries({ queryKey: ["idea-generations"] });
    },
  });
  const removeIdea = useMutation({
    mutationFn: (ideaId: string) => apiClient.deleteGeneratedIdea(ideaId),
    onSuccess: (_void, ideaId) => {
      setActionError(null);
      // Drop it from the cached run so the card goes immediately rather than
      // after the next poll.
      queryClient.setQueryData<IdeaGenerationRun>(["idea-generation", selectedRunId], (current) =>
        current ? { ...current, ideas: current.ideas.filter((idea) => idea.id !== ideaId) } : current);
      queryClient.invalidateQueries({ queryKey: ["idea-generations"] });
    },
    onError: (err: Error) => setActionError(err.message || "Could not delete that idea."),
  });
  const updateState = useMutation({
    mutationFn: ({ ideaId, state }: { ideaId: string; state: IdeaState }) => apiClient.updateIdeaState(ideaId, state),
    onSuccess: (idea) => {
      queryClient.setQueryData<IdeaGenerationRun>(["idea-generation", selectedRunId], (current) => current ? {
        ...current,
        ideas: current.ideas.map((item) => item.id === idea.id ? idea : item),
      } : current);
    },
  });
  const removeRun = useMutation({
    mutationFn: (runId: string) => apiClient.deleteIdeaGeneration(runId),
    onError: (err: Error) => setActionError(err.message || "Could not delete that run."),
    onSuccess: (_, runId) => {
      if (selectedRunId === runId) setSelectedRunId(null);
      queryClient.removeQueries({ queryKey: ["idea-generation", runId] });
      queryClient.invalidateQueries({ queryKey: ["idea-generations"] });
    },
  });

  const run = runQuery.data;
  const ideas = useMemo(
    () => (run?.ideas ?? []).filter((idea) => showDismissed || idea.state !== "dismissed"),
    [run?.ideas, showDismissed]
  );
  const isActive = run && ["queued", "running"].includes(run.status);
  // Google Trends is deliberately unimplemented in V2 (enable_google_trends is
  // false), so surfacing a permanent "Not Configured" chip is noise rather than
  // signal. The backend still reports it in coverage_reasons, so coverage level
  // stays honest.
  const providers = Object.entries(run?.provider_statuses ?? {}).filter(
    ([name]) => name !== "google_trends"
  );

  return (
    <div style={{ minHeight: "100%", background: "var(--color-background-tertiary)" }}>
      <header style={{ height: 52, display: "flex", alignItems: "center", padding: "0 28px", background: "var(--color-background-primary)", borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
        <Lightbulb size={17} style={{ marginRight: 8, color: "var(--color-action)" }} />
        <span style={{ fontSize: "var(--text-lg)", lineHeight: "var(--text-lg-lh)", fontWeight: 500 }}>Idea Generator</span>
        <span style={{ fontSize: "var(--text-xs)", lineHeight: "var(--text-xs-lh)", color: "var(--color-text-tertiary)", marginLeft: 9 }}>V2 · UAE business</span>
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "240px minmax(0, 1fr)", minHeight: "calc(100vh - 52px)" }}>
        <aside style={{ borderRight: "0.5px solid var(--color-border-tertiary)", background: "var(--color-background-primary)", padding: 14 }}>
          <div className="section-label">Recent runs</div>
          <div style={{ display: "grid", gap: 6 }}>
            {(runsQuery.data ?? []).map((item) => (
              <div key={item.id} style={{ display: "flex", gap: 4 }}>
                <button
                  type="button"
                  onClick={() => { setSelectedRunId(item.id); setFormat(item.format); }}
                  style={{ flex: 1, textAlign: "left", border: selectedRunId === item.id ? "0.5px solid var(--color-action)" : "0.5px solid var(--color-border-tertiary)", borderRadius: 8, background: selectedRunId === item.id ? "#f4f5ff" : "#fff", padding: "9px 10px", cursor: "pointer" }}
                >
                  <div style={{ fontSize: "var(--text-xs)", lineHeight: "var(--text-xs-lh)" }}>{FORMAT_LABEL[item.format]}</div>
                  <div style={{ fontSize: "var(--text-xs)", lineHeight: "var(--text-xs-lh)", color: "var(--color-text-tertiary)" }}>{titleCase(item.status)} · {formatDistanceToNow(new Date(item.created_at), { addSuffix: true })}</div>
                </button>
                {/* Always offered. Hiding it for queued/running meant a run
                    abandoned by a dead worker -- killed by a deploy, say --
                    could never be cleared, because that is the state it stays
                    in until recovery reaches it. The backend refuses only when
                    a worker lease is genuinely still live, and says so. */}
                <button
                  type="button"
                  className="btn-ghost"
                  aria-label="Delete run"
                  onClick={() => removeRun.mutate(item.id)}
                  style={{ padding: 6 }}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
            {!runsQuery.isLoading && !(runsQuery.data ?? []).length && <p style={{ color: "var(--color-text-tertiary)", fontSize: "var(--text-xs)", lineHeight: "var(--text-xs-lh)" }}>No idea runs yet.</p>}
          </div>
        </aside>

        <main style={{ padding: 28, maxWidth: 1040, width: "100%" }}>
          <section className="card" style={{ padding: 20, marginBottom: 18 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 18, flexWrap: "wrap" }}>
              <div>
                <div className="section-label">Choose a format</div>
                <div style={{ display: "flex", gap: 8 }}>
                  {(["documentary", "expert_interview"] as IdeaFormat[]).map((value) => (
                    <button key={value} type="button" className={`chip ${format === value ? "selected" : ""}`} onClick={() => setFormat(value)} disabled={!!isActive}>
                      {FORMAT_LABEL[value]}
                    </button>
                  ))}
                </div>
              </div>
              <button type="button" className="btn-primary" disabled={generate.isPending || !!isActive} onClick={() => generate.mutate({ requestedFormat: format })} style={{ minWidth: 170 }}>
                {generate.isPending || isActive ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                I am feeling lucky
              </button>
            </div>
            {generate.isError && <p role="alert" style={{ color: "var(--color-danger)", marginBottom: 0 }}>{(generate.error as Error).message}</p>}
            {actionError && (
              <p role="alert" style={{ color: "var(--color-danger)", marginBottom: 0, display: "flex", gap: 8, alignItems: "center" }}>
                {actionError}
                <button className="btn-ghost" type="button" onClick={() => setActionError(null)}>Dismiss</button>
              </p>
            )}
          </section>

          {runQuery.isLoading && <div style={{ padding: 30, textAlign: "center" }}><Loader2 size={20} className="animate-spin" /></div>}

          {run && (
            <>
              <section className="card" style={{ padding: 16, marginBottom: 18 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                      {run.status === "completed" ? <CheckCircle2 size={14} style={{ color: "var(--color-success)" }} /> : isActive ? <Loader2 size={14} className="animate-spin" style={{ color: "var(--color-action)" }} /> : <X size={14} style={{ color: "var(--color-danger)" }} />}
                      <strong style={{ fontWeight: 500 }}>{titleCase(run.stage)}</strong>
                    </div>
                    <div style={{ fontSize: "var(--text-xs)", lineHeight: "var(--text-xs-lh)", color: "var(--color-text-tertiary)", marginTop: 4 }}>
                      Coverage: {titleCase(run.coverage_level)}
                    </div>
                  </div>
                  <span style={{ fontSize: "var(--text-xs)", lineHeight: "var(--text-xs-lh)" }}>{run.stage_progress}%</span>
                </div>
                <div style={{ height: 4, background: "var(--color-background-tertiary)", borderRadius: 4, marginTop: 10, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${run.stage_progress}%`, background: run.status === "failed" ? "var(--color-danger)" : "var(--color-action)", transition: "width 0.4s ease" }} />
                </div>
                <RunClock run={run} active={!!isActive} />
                {providers.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
                    {providers.map(([name, provider]) => (
                      <span key={name} className="chip" title={provider.detail} style={{ padding: "4px 9px", cursor: "help" }}>
                        {titleCase(name)}: {titleCase(provider.status)}{provider.evidence_count ? ` (${provider.evidence_count})` : ""}
                      </span>
                    ))}
                  </div>
                )}
                {run.error_message && <p style={{ color: "var(--color-danger)", margin: "10px 0 0" }}>{run.error_message}</p>}
                {run.status === "failed" && (
                  <button type="button" className="btn-secondary" onClick={() => retry.mutate(run.id)} disabled={retry.isPending} style={{ marginTop: 12 }}>
                    <RefreshCw size={13} /> Retry run
                  </button>
                )}
              </section>

              {run.status === "completed" && (
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  <div style={{ fontSize: "var(--text-xs)", lineHeight: "var(--text-xs-lh)", color: "var(--color-text-secondary)" }}>{ideas.length} visible ideas</div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button type="button" className="btn-ghost" onClick={() => setShowDismissed((value) => !value)}>{showDismissed ? "Hide dismissed" : "Show dismissed"}</button>
                    <button type="button" className="btn-secondary" onClick={() => generate.mutate({ requestedFormat: run.format, previousRunId: run.id })} disabled={generate.isPending}>
                      <RefreshCw size={13} /> Generate fresh set
                    </button>
                  </div>
                </div>
              )}

              <div style={{ display: "grid", gap: 14 }}>
                {ideas.map((idea) => (
                  <IdeaCard
                    key={idea.id}
                    idea={idea}
                    onState={(ideaId, state) => updateState.mutate({ ideaId, state })}
                    onDelete={(ideaId) => removeIdea.mutate(ideaId)}
                  />
                ))}
              </div>
            </>
          )}

          {!run && !runQuery.isLoading && (
            <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--color-text-secondary)" }}>
              <Sparkles size={23} style={{ margin: "0 auto 10px", color: "var(--color-action)" }} />
              Pick a format and let the agent research the first set.
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

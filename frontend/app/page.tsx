"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, ChevronRight, CheckCircle2, XCircle } from "lucide-react";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import { apiClient, type Story, type StoryTone } from "@/lib/api";

const TONES: { value: StoryTone; label: string; desc: string; example: string }[] = [
  {
    value:   "investigative",
    label:   "Investigative",
    desc:    "Deep-dive exposé uncovering hidden facts, holding power to account.",
    example: "e.g. How did a state-backed fund lose $4B without public disclosure?",
  },
  {
    value:   "explanatory",
    label:   "Explanatory",
    desc:    "Breaks a complex topic into clear, layered reasoning for a broad audience.",
    example: "e.g. Why is the UAE pegging its currency to the dollar — and what does it cost?",
  },
  {
    value:   "narrative",
    label:   "Narrative",
    desc:    "Story-driven documentary following real people through a turning point.",
    example: "e.g. Three founders who bet everything on Abu Dhabi's startup scene.",
  },
  {
    value:   "profile",
    label:   "Profile",
    desc:    "In-depth portrait of a person, company, or institution — their rise, decisions, and impact.",
    example: "e.g. Inside Emirates Development Bank: the quiet engine behind UAE's industrial push.",
  },
  {
    value:   "trend",
    label:   "Trend",
    desc:    "Maps an emerging shift — economic, cultural, or technological — and what it signals.",
    example: "e.g. Gulf sovereign funds are buying European football clubs. Here's why.",
  },
];

const PIPELINE_STAGES = [
  { label: "Research",          statuses: ["pending", "researching"] },
  { label: "Analysis",          statuses: ["analysing", "writing_storyline"] },
  { label: "Script Writing",    statuses: ["evaluating", "scripting"] },
  { label: "Script Evaluation", statuses: ["completed"] },
];

const STAGE_MESSAGES: Record<string, string[]> = {
  pending:           ["Initialising pipeline", "Preparing research agents", "Setting up context"],
  researching:       ["Scanning news sources", "Querying web for evidence", "Pulling recent articles", "Cross-referencing sources", "Gathering data points"],
  analysing:         ["Synthesising findings", "Extracting key insights", "Scoring source credibility", "Mapping narrative angles"],
  writing_storyline: ["Designing documentary structure", "Drafting act breakdowns", "Shaping the story arc", "Selecting strongest angle"],
  evaluating:        ["Evaluating storyline quality", "Scoring against benchmarks", "Checking narrative coherence", "Running quality checks"],
  scripting:         ["Writing script narration", "Crafting opening hook", "Building act-by-act script", "Polishing final draft"],
  completed:         ["Script complete"],
};

const DEFAULT_TARGET_AUDIENCE =
  "Entrepreneurs, Founders, Documentary Lovers, Investors, YouTube Content Lovers, Senior Executive and Business Professionals";

function stageIndex(status: string): number {
  const idx = PIPELINE_STAGES.findIndex(s => s.statuses.includes(status));
  return idx === -1 ? 0 : idx;
}

function stagePct(status: string): number {
  if (status === "completed") return 100;
  const pcts = [12, 38, 68, 90];
  return pcts[stageIndex(status)] ?? 12;
}

function statusBadgeClass(status: string) {
  if (status === "completed") return "badge-success";
  if (status === "failed")    return "badge-danger";
  return "badge-active";
}

export default function NewStoryPage() {
  const queryClient = useQueryClient();
  const [topic, setTopic] = useState("");
  const [tone, setTone] = useState<StoryTone>("explanatory");
  const [targetDuration, setTargetDuration] = useState(10);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [msgIndex, setMsgIndex] = useState(0);
  const [dots, setDots] = useState(".");

  const { data: stories } = useQuery<Story[]>({
    queryKey: ["stories", "list"],
    queryFn: () => apiClient.listStories(20),
    refetchInterval: 12_000,
  });

  const { data: activeStory } = useQuery<Story>({
    queryKey: ["story", activeId],
    queryFn: () => apiClient.getStory(activeId!),
    enabled: !!activeId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s && ["completed", "failed"].includes(s) ? false : 3000;
    },
  });

  const createMutation = useMutation({
    mutationFn: () => apiClient.createStory({
      topic: topic.trim(),
      tone,
      target_duration_minutes: targetDuration,
      target_audience: DEFAULT_TARGET_AUDIENCE,
    }),
    onSuccess: (story) => {
      // Seed the cache immediately so progress renders without waiting for the first poll
      queryClient.setQueryData(["story", story.id], story);
      setActiveId(story.id);
      setTopic("");
      queryClient.invalidateQueries({ queryKey: ["stories"] });
    },
  });

  useEffect(() => {
    if (!activeId) return;
    return apiClient.streamStoryEvents(
      activeId,
      (story) => {
        queryClient.setQueryData(["story", activeId], story);
        queryClient.invalidateQueries({ queryKey: ["stories"] });
      },
      () => undefined
    );
  }, [activeId, queryClient]);

  const isRunning = activeStory && !["completed", "failed"].includes(activeStory.status);
  const showProgress = activeStory && activeStory.status !== "failed";

  // Cycle through status messages while pipeline is running
  useEffect(() => {
    const status = activeStory?.status ?? "pending";
    const pool = STAGE_MESSAGES[status] ?? ["Working"];
    setMsgIndex(0);
    if (!isRunning) return;
    const t = setInterval(() => setMsgIndex(i => (i + 1) % pool.length), 2800);
    return () => clearInterval(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeStory?.status, isRunning]);

  // Animated ellipsis
  useEffect(() => {
    if (!isRunning) { setDots("."); return; }
    const t = setInterval(() => setDots(d => d.length >= 3 ? "." : d + "."), 500);
    return () => clearInterval(t);
  }, [isRunning]);
  const recent = (stories ?? []).filter(s => s.id !== activeId).slice(0, 6);
  const selectedTone = TONES.find(t => t.value === tone);

  return (
    <div style={{ minHeight: "100%", background: "var(--color-background-tertiary)" }}>
      {/* Topbar */}
      <div
        style={{
          height: 52,
          display: "flex",
          alignItems: "center",
          padding: "0 28px",
          background: "var(--color-background-primary)",
          borderBottom: "0.5px solid var(--color-border-tertiary)",
        }}
      >
        <span style={{ fontSize: 18, fontWeight: 500 }}>New story</span>
      </div>

      <div style={{ padding: "28px", maxWidth: 720 }}>

        {/* Prompt card */}
        <div className="card" style={{ padding: "18px 20px", marginBottom: 24 }}>
          <div style={{ marginBottom: 14 }}>
            <label
              style={{
                display: "block",
                fontSize: 11,
                fontWeight: 500,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: "var(--color-text-secondary)",
                marginBottom: 8,
              }}
            >
              Topic
            </label>
            <textarea
              value={topic}
              onChange={e => setTopic(e.target.value)}
              placeholder="Describe what you want to investigate or explain…"
              rows={4}
              disabled={!!isRunning}
              className="input"
              style={{ resize: "vertical", fontFamily: "var(--font-sans)" }}
            />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label
              style={{
                display: "block",
                fontSize: 11,
                fontWeight: 500,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: "var(--color-text-secondary)",
                marginBottom: 10,
              }}
            >
              Documentary tone
            </label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {TONES.map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => setTone(value)}
                  className={`chip ${tone === value ? "selected" : ""}`}
                >
                  {label}
                </button>
              ))}
            </div>
            {selectedTone && (
              <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 2 }}>
                <p style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                  {selectedTone.desc}
                </p>
                <p style={{ fontSize: 12, color: "var(--color-text-tertiary)", fontStyle: "italic" }}>
                  {selectedTone.example}
                </p>
              </div>
            )}
          </div>

          <div style={{ maxWidth: 180, marginBottom: 16 }}>
            <div>
              <label
                style={{
                  display: "block",
                  fontSize: 11,
                  fontWeight: 500,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  color: "var(--color-text-secondary)",
                  marginBottom: 8,
                }}
              >
                Duration
              </label>
              <select
                value={targetDuration}
                onChange={e => setTargetDuration(Number(e.target.value))}
                disabled={!!isRunning}
                className="input"
              >
                {[5, 10, 15].map((minutes) => (
                  <option key={minutes} value={minutes}>{minutes} minutes</option>
                ))}
              </select>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <button
              onClick={() => createMutation.mutate()}
              disabled={!topic.trim() || !!isRunning || createMutation.isPending}
              className="btn-primary"
            >
              {createMutation.isPending && <Loader2 size={13} className="animate-spin" />}
              Generate script
            </button>
            <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>Live progress appears below</span>
          </div>
        </div>

        {/* Active pipeline */}
        {activeStory && (
          <div className="card" style={{ padding: "18px 20px", marginBottom: 24 }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 16 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <span className={`badge ${statusBadgeClass(activeStory.status)}`}>
                    {activeStory.status === "completed" && <CheckCircle2 size={10} />}
                    {activeStory.status === "failed"    && <XCircle size={10} />}
                    {isRunning                          && <Loader2 size={10} className="animate-spin" />}
                    {activeStory.status.replace(/_/g, " ")}
                  </span>
                </div>
                <p
                  style={{
                    fontSize: 13,
                    fontWeight: 500,
                    color: "var(--color-text-primary)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {activeStory.title}
                </p>
                <p style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 2 }}>
                  {activeStory.topic}
                </p>
              </div>
              {activeStory.status === "completed" && (
                <Link
                  href={`/results/${activeStory.id}`}
                  className="btn-secondary"
                  style={{ marginLeft: 16, flexShrink: 0 }}
                >
                  View results
                </Link>
              )}
            </div>

            {/* Stage progress */}
            {showProgress && (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
                  {PIPELINE_STAGES.map((stage, i) => {
                    const current = stageIndex(activeStory.status);
                    const done = i < current || activeStory.status === "completed";
                    const active = i === current && activeStory.status !== "completed";
                    return (
                      <div key={stage.label} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 5, flex: 1 }}>
                        <div style={{ display: "flex", alignItems: "center", width: "100%" }}>
                          {i > 0 && (
                            <div style={{ flex: 1, height: 1, background: done || active ? "var(--color-action)" : "var(--color-border-primary)", opacity: done ? 1 : 0.4, transition: "background 0.4s" }} />
                          )}
                          {active ? (
                            <Loader2
                              size={12}
                              className="animate-spin"
                              style={{ flexShrink: 0, color: "var(--color-action)" }}
                            />
                          ) : (
                            <div style={{
                              width: 10, height: 10, borderRadius: "50%", flexShrink: 0,
                              background: done ? "var(--color-action)" : "var(--color-border-primary)",
                              transition: "background 0.4s",
                            }} />
                          )}
                          {i < PIPELINE_STAGES.length - 1 && (
                            <div style={{ flex: 1, height: 1, background: done ? "var(--color-action)" : "var(--color-border-primary)", opacity: done ? 1 : 0.4, transition: "background 0.4s" }} />
                          )}
                        </div>
                        <span style={{
                          fontSize: 10,
                          textAlign: "center",
                          color: active ? "var(--color-text-primary)" : done ? "var(--color-action)" : "var(--color-text-tertiary)",
                          fontWeight: active ? 600 : done ? 500 : 400,
                          letterSpacing: "0.02em",
                          transition: "color 0.3s",
                        }}>
                          {stage.label}
                        </span>
                      </div>
                    );
                  })}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4 }}>
                  <div className="progress-track" style={{ flex: 1 }}>
                    <div
                      className="progress-fill"
                      style={{ width: `${stagePct(activeStory.status)}%`, transition: "width 0.6s ease" }}
                    />
                  </div>
                  <span style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)", minWidth: 32, textAlign: "right" }}>
                    {stagePct(activeStory.status)}%
                  </span>
                </div>

                {isRunning && (
                  <div style={{ display: "flex", alignItems: "center", gap: 7, marginTop: 10 }}>
                    <Loader2 size={12} className="animate-spin" style={{ color: "var(--color-action)", flexShrink: 0 }} />
                    <span style={{ fontSize: 12, color: "var(--color-text-secondary)", fontStyle: "italic" }}>
                      {(STAGE_MESSAGES[activeStory.status] ?? ["Working"])[msgIndex]}{dots}
                    </span>
                  </div>
                )}
              </div>
            )}

            {activeStory.status === "failed" && activeStory.error_message && (
              <div
                style={{
                  marginTop: 10,
                  padding: "10px 12px",
                  background: "var(--color-danger-bg)",
                  border: "0.5px solid #fecaca",
                  borderRadius: "var(--border-radius-md)",
                  fontSize: 12,
                  color: "var(--color-danger)",
                }}
              >
                {activeStory.error_message}
              </div>
            )}
          </div>
        )}

        {/* Recent stories */}
        {recent.length > 0 && (
          <div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
              <p className="section-label" style={{ margin: 0 }}>Recent stories</p>
              <Link
                href="/history"
                style={{ fontSize: 12, color: "var(--color-text-secondary)", textDecoration: "none" }}
              >
                View all
              </Link>
            </div>

            <div className="card" style={{ overflow: "hidden" }}>
              {recent.map((story, idx) => {
                const isLast = idx === recent.length - 1;
                const isComplete = story.status === "completed";
                const isFailed   = story.status === "failed";
                const isActive   = !isComplete && !isFailed;
                return (
                  <Link
                    key={story.id}
                    href={`/results/${story.id}`}
                    className="table-row"
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 12,
                      padding: "12px 16px",
                      textDecoration: "none",
                      borderBottom: isLast ? "none" : "0.5px solid var(--color-border-tertiary)",
                    }}
                  >
                    {/* Status dot */}
                    <div style={{ flexShrink: 0 }}>
                      {isComplete && <CheckCircle2 size={14} style={{ color: "var(--color-success)" }} />}
                      {isFailed   && <XCircle size={14} style={{ color: "var(--color-danger)" }} />}
                      {isActive   && <Loader2 size={14} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />}
                    </div>

                    {/* Title + topic */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p
                        style={{
                          fontSize: 13,
                          color: "var(--color-text-primary)",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          marginBottom: 2,
                        }}
                      >
                        {story.title}
                      </p>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span
                          className={`badge tone-${story.tone}`}
                          style={{ fontSize: 11, padding: "1px 6px" }}
                        >
                          {story.tone}
                        </span>
                        <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>
                          {formatDistanceToNow(new Date(story.created_at), { addSuffix: true })}
                        </span>
                      </div>
                    </div>

                    {/* Quality */}
                    {story.quality_score != null && (
                      <span style={{ fontSize: 12, color: "var(--color-text-secondary)", flexShrink: 0 }}>
                        {(story.quality_score * 100).toFixed(0)}%
                      </span>
                    )}

                    <ChevronRight size={14} style={{ color: "var(--color-text-tertiary)", flexShrink: 0 }} />
                  </Link>
                );
              })}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!activeStory && recent.length === 0 && (
          <div
            className="card"
            style={{
              padding: "40px 20px",
              textAlign: "center",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 8,
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
            <p style={{ fontSize: 14, fontWeight: 500 }}>No stories yet</p>
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
              Enter a topic above to generate your first documentary script.
            </p>
          </div>
        )}

      </div>
    </div>
  );
}

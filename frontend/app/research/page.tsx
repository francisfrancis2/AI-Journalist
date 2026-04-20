"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import {
  CheckCircle2,
  ExternalLink,
  Loader2,
  Newspaper,
  Radar,
  Search,
  Send,
  Sparkles,
} from "lucide-react";
import {
  apiClient,
  type ChatMessage,
  type FocusedResearchRun,
  type RawSource,
  type ResearchSource,
  type Story,
  type YouTubeVideo,
} from "@/lib/api";

type WorkspaceMessage = ChatMessage & {
  youtube_results?: YouTubeVideo[];
};

function credibilityStyle(level: string) {
  if (level === "high") return { background: "var(--color-success-bg)", color: "var(--color-success)", borderColor: "#bbf7d0" };
  if (level === "medium") return { background: "var(--color-warning-bg)", color: "var(--color-warning)", borderColor: "#fed7aa" };
  return { background: "var(--color-background-secondary)", color: "var(--color-text-secondary)", borderColor: "var(--color-border-tertiary)" };
}

function scorePercent(value?: number | null) {
  if (value == null) return "N/A";
  return `${(value * 100).toFixed(0)}%`;
}

function SourceCard({
  source,
}: {
  source: Pick<RawSource, "title" | "url" | "content" | "source_type" | "credibility" | "published_at" | "author"> | Pick<ResearchSource, "title" | "url" | "content_preview" | "source_type" | "credibility" | "published_at" | "author">;
}) {
  const preview = "content" in source ? source.content : source.content_preview;
  return (
    <div className="card" style={{ padding: "14px 16px" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 8 }}>
        <div style={{ minWidth: 0 }}>
          <p style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text-primary)" }}>{source.title}</p>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 5 }}>
            <span
              className="badge"
              style={{
                ...credibilityStyle(source.credibility),
                border: "0.5px solid",
                fontSize: 10,
                textTransform: "uppercase",
              }}
            >
              {source.credibility}
            </span>
            <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
              {source.source_type.replace(/_/g, " ")}
            </span>
            {source.author && (
              <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{source.author}</span>
            )}
            {source.published_at && (
              <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
                {formatDistanceToNow(new Date(source.published_at), { addSuffix: true })}
              </span>
            )}
          </div>
        </div>
        {source.url && (
          <a href={source.url} target="_blank" rel="noopener noreferrer" className="btn-ghost" style={{ padding: 0, flexShrink: 0 }}>
            <ExternalLink size={14} />
          </a>
        )}
      </div>
      <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
        {preview.slice(0, 320)}
        {preview.length > 320 ? "..." : ""}
      </p>
    </div>
  );
}

function ResearchRunPanel({ run }: { run: FocusedResearchRun }) {
  const plan = run.plan;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div
        style={{
          padding: "14px 16px",
          borderRadius: 12,
          background: "rgba(28, 38, 168, 0.04)",
          border: "0.5px solid rgba(28, 38, 168, 0.14)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <Sparkles size={14} style={{ color: "var(--color-action)" }} />
          <p style={{ fontSize: 13, fontWeight: 500 }}>Research plan generated</p>
        </div>
        <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.7 }}>{run.summary}</p>
      </div>

      <div className="card" style={{ padding: "16px 18px" }}>
        <div className="section-rule"><span>Agent plan</span></div>
        <p style={{ fontSize: 13, fontWeight: 500, marginBottom: 6 }}>{plan.objective}</p>
        <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.7, marginBottom: 12 }}>
          {plan.source_strategy_reasoning}
        </p>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
          {plan.source_strategy.map((source) => (
            <span key={source} className="badge badge-neutral" style={{ textTransform: "uppercase" }}>
              {source}
            </span>
          ))}
        </div>
        {plan.evaluation_focus.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <p className="section-label" style={{ marginBottom: 6 }}>Evaluation focus</p>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {plan.evaluation_focus.map((item, index) => (
                <li key={index} style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>{item}</li>
              ))}
            </ul>
          </div>
        )}
        {plan.expected_improvements.length > 0 && (
          <div>
            <p className="section-label" style={{ marginBottom: 6 }}>Expected improvements</p>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {plan.expected_improvements.map((item, index) => (
                <li key={index} style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>{item}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="card" style={{ padding: "16px 18px" }}>
        <div className="section-rule"><span>Queries issued</span></div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div>
            <p className="section-label" style={{ marginBottom: 6 }}>Primary</p>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {plan.primary_queries.map((query, index) => (
                <li key={index} style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>{query}</li>
              ))}
            </ul>
          </div>
          <div>
            <p className="section-label" style={{ marginBottom: 6 }}>Deep dive</p>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {plan.deep_dive_queries.map((query, index) => (
                <li key={index} style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>{query}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <div>
        <div className="section-rule"><span>New sources ({run.sources.length})</span></div>
        {run.sources.length === 0 ? (
          <div
            style={{
              border: "0.5px dashed var(--color-border-primary)",
              borderRadius: 12,
              padding: "28px 22px",
              textAlign: "center",
              color: "var(--color-text-secondary)",
            }}
          >
            <Radar size={18} style={{ margin: "0 auto 10px", color: "var(--color-text-tertiary)" }} />
            <p style={{ fontSize: 13 }}>No new sources were returned by this research pass.</p>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {run.sources.map((source, index) => (
              <SourceCard key={`${source.title}-${index}`} source={source} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

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
  const searchParams = useSearchParams();
  const [selectedStoryId, setSelectedStoryId] = useState<string>("");
  const [messages, setMessages] = useState<WorkspaceMessage[]>([]);
  const [messageInput, setMessageInput] = useState("");
  const [researchObjective, setResearchObjective] = useState("");
  const [researchRun, setResearchRun] = useState<FocusedResearchRun | null>(null);
  const storyParam = searchParams.get("story");
  const objectiveParam = searchParams.get("objective");

  const { data: stories, isLoading: storiesLoading } = useQuery<Story[]>({
    queryKey: ["stories", "research-workspace"],
    queryFn: () => apiClient.listStories(100),
    refetchInterval: 15_000,
  });

  const selectedStory = useMemo(
    () => stories?.find((story) => story.id === selectedStoryId) ?? null,
    [stories, selectedStoryId]
  );

  useEffect(() => {
    if (storyParam && storyParam !== selectedStoryId) {
      setSelectedStoryId(storyParam);
    }
    if (objectiveParam && !researchObjective) {
      setResearchObjective(objectiveParam);
    }
  }, [storyParam, objectiveParam, selectedStoryId, researchObjective]);

  const { data: storySources, isLoading: sourcesLoading } = useQuery<ResearchSource[]>({
    queryKey: ["story-sources", selectedStoryId],
    queryFn: () => apiClient.getResearchSources(selectedStoryId),
    enabled: !!selectedStoryId,
  });

  useEffect(() => {
    setMessages([]);
    setMessageInput("");
    setResearchRun(null);
  }, [selectedStoryId]);

  const focusedResearchMutation = useMutation({
    mutationFn: async () => {
      if (!selectedStoryId) {
        throw new Error("Choose a story before starting research.");
      }
      return apiClient.startFocusedResearch(selectedStoryId, researchObjective.trim());
    },
    onSuccess: async (response) => {
      setResearchRun(response);
      await queryClient.invalidateQueries({ queryKey: ["story-sources", selectedStoryId] });
      await queryClient.invalidateQueries({ queryKey: ["stories"] });
    },
  });

  const chatMutation = useMutation({
    mutationFn: async (outgoing: string) => {
      if (!selectedStoryId) {
        throw new Error("Choose a story before opening the story assistant.");
      }
      const history: ChatMessage[] = messages.map((message) => ({
        role: message.role,
        content: message.content,
      }));
      return apiClient.chat(selectedStoryId, outgoing, history);
    },
    onSuccess: (response) => {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: response.content,
          youtube_results: response.youtube_results,
        },
      ]);
    },
    onError: (error) => {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: (error as Error).message,
        },
      ]);
    },
  });

  const rewriteMutation = useMutation({
    mutationFn: async () => {
      if (!selectedStoryId) {
        throw new Error("Choose a story before rewriting.");
      }
      return apiClient.rewriteStory(selectedStoryId);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["stories"] });
    },
  });

  const handleStartResearch = () => {
    if (!selectedStoryId || researchObjective.trim().length < 3 || focusedResearchMutation.isPending) return;
    focusedResearchMutation.mutate();
  };

  const handleSendMessage = () => {
    const outgoing = messageInput.trim();
    if (!outgoing || !selectedStoryId || chatMutation.isPending) return;
    setMessages((prev) => [...prev, { role: "user", content: outgoing }]);
    setMessageInput("");
    chatMutation.mutate(outgoing);
  };

  const highCredSources = (storySources ?? []).filter((source) => source.credibility === "high").length;
  const evaluation = selectedStory?.evaluation_data;
  const scriptAudit = selectedStory?.script_audit_data;

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
          <span style={{ fontSize: 18, fontWeight: 500 }}>Research Workspace</span>
          <span style={{ fontSize: 12, color: "var(--color-text-secondary)", marginLeft: 10 }}>
            Start a story-aware research pass that targets evaluation and script weaknesses.
          </span>
        </div>
        {selectedStory && (
          <Link href={`/results/${selectedStory.id}`} className="btn-secondary" style={{ textDecoration: "none" }}>
            Open story
          </Link>
        )}
      </div>

      <div style={{ padding: 28, display: "grid", gridTemplateColumns: "minmax(320px, 420px) minmax(0, 1fr)", gap: 18 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="card" style={{ padding: "18px 20px" }}>
            <div className="section-rule"><span>Story workspace</span></div>
            {storiesLoading ? (
              <div style={{ display: "flex", justifyContent: "center", padding: "20px 0" }}>
                <Loader2 size={18} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
              </div>
            ) : (
              <>
                <label style={{ display: "block", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-secondary)", marginBottom: 8 }}>
                  Choose story
                </label>
                <select
                  value={selectedStoryId}
                  onChange={(event) => setSelectedStoryId(event.target.value)}
                  className="input"
                  style={{ marginBottom: 12 }}
                >
                  <option value="">Select a story</option>
                  {(stories ?? []).map((story) => (
                    <option key={story.id} value={story.id}>
                      {story.title}
                    </option>
                  ))}
                </select>

                {selectedStory ? (
                  <div>
                    <p style={{ fontSize: 13, fontWeight: 500 }}>{selectedStory.title}</p>
                    <p style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 4, lineHeight: 1.6 }}>
                      {selectedStory.topic}
                    </p>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 12 }}>
                      <div className="card" style={{ padding: "10px 12px" }}>
                        <p style={{ fontSize: 11, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Sources</p>
                        <p style={{ fontSize: 18, fontWeight: 500 }}>{storySources?.length ?? 0}</p>
                      </div>
                      <div className="card" style={{ padding: "10px 12px" }}>
                        <p style={{ fontSize: 11, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>High cred.</p>
                        <p style={{ fontSize: 18, fontWeight: 500 }}>{highCredSources}</p>
                      </div>
                      <div className="card" style={{ padding: "10px 12px" }}>
                        <p style={{ fontSize: 11, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Evaluation</p>
                        <p style={{ fontSize: 18, fontWeight: 500 }}>{scorePercent(evaluation?.overall_score)}</p>
                      </div>
                      <div className="card" style={{ padding: "10px 12px" }}>
                        <p style={{ fontSize: 11, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Script audit</p>
                        <p style={{ fontSize: 18, fontWeight: 500 }}>{scriptAudit?.grade ?? "N/A"}</p>
                      </div>
                    </div>
                  </div>
                ) : (
                  <p style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                    Pick a story to inspect the source pack and run targeted follow-up research.
                  </p>
                )}
              </>
            )}
          </div>

          <div className="card" style={{ padding: "18px 20px" }}>
            <div className="section-rule"><span>Story sources</span></div>
            {!selectedStoryId ? (
              <p style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>No story selected yet.</p>
            ) : sourcesLoading ? (
              <div style={{ display: "flex", justifyContent: "center", padding: "20px 0" }}>
                <Loader2 size={18} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
              </div>
            ) : (storySources?.length ?? 0) === 0 ? (
              <p style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                This story does not have persisted research sources yet.
              </p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10, maxHeight: 380, overflow: "auto" }}>
                {storySources?.map((source, index) => (
                  <SourceCard key={`${source.title}-${index}`} source={source} />
                ))}
              </div>
            )}
          </div>

          <div className="card" style={{ padding: "18px 20px" }}>
            <div className="section-rule"><span>Story assistant</span></div>
            {!selectedStoryId ? (
              <p style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                Choose a story to ask for more sources, YouTube references, or rewrite ideas.
              </p>
            ) : (
              <>
                <div style={{ display: "flex", flexDirection: "column", gap: 10, maxHeight: 280, overflow: "auto", marginBottom: 12 }}>
                  {messages.length === 0 && (
                    <div style={{ padding: "12px 14px", borderRadius: 10, background: "var(--color-background-secondary)" }}>
                      <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
                        Ask follow-up questions, request source interpretation, or ask how to use new research in the script.
                      </p>
                    </div>
                  )}
                  {messages.map((message, index) => (
                    <div
                      key={index}
                      style={{
                        alignSelf: message.role === "user" ? "flex-end" : "stretch",
                        background: message.role === "user" ? "var(--color-action)" : "var(--color-background-secondary)",
                        color: message.role === "user" ? "#fff" : "var(--color-text-primary)",
                        padding: "12px 14px",
                        borderRadius: 12,
                      }}
                    >
                      <p style={{ fontSize: 12, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{message.content}</p>
                      {message.youtube_results && message.youtube_results.length > 0 && (
                        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
                          {message.youtube_results.map((video) => (
                            <a
                              key={video.url}
                              href={video.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{
                                textDecoration: "none",
                                padding: "10px 12px",
                                borderRadius: 10,
                                background: "rgba(255,255,255,0.08)",
                                color: message.role === "user" ? "#fff" : "var(--color-text-primary)",
                              }}
                            >
                              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                                <Newspaper size={13} />
                                <span style={{ fontSize: 12, fontWeight: 500 }}>{video.title}</span>
                              </div>
                              <p style={{ fontSize: 11, opacity: 0.8 }}>{video.channel}</p>
                            </a>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                  {chatMutation.isPending && (
                    <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--color-text-secondary)" }}>
                      <Loader2 size={14} className="animate-spin" />
                      <span style={{ fontSize: 12 }}>Assistant is thinking...</span>
                    </div>
                  )}
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    value={messageInput}
                    onChange={(event) => setMessageInput(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        handleSendMessage();
                      }
                    }}
                    placeholder="Ask about sources, data gaps, or script improvements..."
                    className="input"
                  />
                  <button onClick={handleSendMessage} className="btn-primary" disabled={!messageInput.trim() || chatMutation.isPending}>
                    {chatMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
                    Send
                  </button>
                </div>
              </>
            )}
          </div>
        </div>

        <div className="card" style={{ padding: "18px 20px" }}>
          <div className="section-rule"><span>Focused research</span></div>
          <div style={{ marginBottom: 16 }}>
            <p style={{ fontSize: 13, fontWeight: 500, marginBottom: 6 }}>
              Tell the agent what the next research pass should improve.
            </p>
            <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.7 }}>
              The backend will use the story, evaluation feedback, benchmark gaps, script audit, and existing source pack to choose the right data sources automatically.
            </p>
          </div>

          <textarea
            value={researchObjective}
            onChange={(event) => setResearchObjective(event.target.value)}
            className="input"
            rows={5}
            placeholder="Example: Find stronger market data, expert sources, and counterpoints that would improve factual accuracy and source diversity for the weakest sections."
            disabled={!selectedStoryId || focusedResearchMutation.isPending}
            style={{ resize: "vertical", marginBottom: 12 }}
          />

          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
            <button
              onClick={handleStartResearch}
              className="btn-primary"
              disabled={!selectedStoryId || researchObjective.trim().length < 3 || focusedResearchMutation.isPending}
            >
              {focusedResearchMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
              Start research
            </button>
            {!selectedStoryId && (
              <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                Choose a story first.
              </span>
            )}
          </div>

          {focusedResearchMutation.error && (
            <div className="card" style={{ padding: "12px 14px", background: "var(--color-danger-bg)", marginBottom: 14 }}>
              <p style={{ fontSize: 12, color: "var(--color-danger)", lineHeight: 1.6 }}>
                {(focusedResearchMutation.error as Error).message}
              </p>
            </div>
          )}

          {researchRun ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <ResearchRunPanel run={researchRun} />
              {selectedStory?.status === "completed" && (
                <div className="card" style={{ padding: "14px 16px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
                  <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                    Use the expanded source pack to run one audit-guided rewrite pass.
                  </p>
                  <button
                    onClick={() => rewriteMutation.mutate()}
                    className="btn-secondary"
                    disabled={rewriteMutation.isPending}
                  >
                    {rewriteMutation.isPending && <Loader2 size={13} className="animate-spin" />}
                    Rewrite script
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div
              style={{
                border: "0.5px dashed var(--color-border-primary)",
                borderRadius: 12,
                padding: "32px 24px",
                textAlign: "center",
                color: "var(--color-text-secondary)",
              }}
            >
              <CheckCircle2 size={18} style={{ margin: "0 auto 10px", color: "var(--color-text-tertiary)" }} />
              <p style={{ fontSize: 13, marginBottom: 4 }}>No focused research run yet.</p>
              <p style={{ fontSize: 12 }}>
                Enter a research objective and use the single Start research button. Source routing happens in the backend.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

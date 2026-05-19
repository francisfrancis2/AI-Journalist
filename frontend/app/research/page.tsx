"use client";

import { Suspense, useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import {
  Download,
  ExternalLink,
  Loader2,
  Search,
} from "lucide-react";
import {
  apiClient,
  type DeepResearchReport,
  type RawSource,
  type ResearchSource,
  type Story,
} from "@/lib/api";
import { getUserInfo } from "@/lib/auth";
import { downloadDeepResearchReport } from "@/lib/research-report-export";

function credibilityStyle(level: string) {
  if (level === "high") return { background: "var(--color-success-bg)", color: "var(--color-success)", borderColor: "#bbf7d0" };
  if (level === "medium") return { background: "var(--color-warning-bg)", color: "var(--color-warning)", borderColor: "#fed7aa" };
  return { background: "var(--color-background-secondary)", color: "var(--color-text-secondary)", borderColor: "var(--color-border-tertiary)" };
}

const CREDIBILITY_TOOLTIP: Record<string, string> = {
  high:   "Authoritative source — academic, government, official report or major publication",
  medium: "Generally reliable — news article, industry report or trade publication",
  low:    "Uncertain reliability — verify before citing in the script",
};

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
              title={CREDIBILITY_TOOLTIP[source.credibility] ?? source.credibility}
              style={{
                ...credibilityStyle(source.credibility),
                border: "0.5px solid",
                fontSize: 10,
                textTransform: "uppercase",
                cursor: "help",
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
  const currentUser = getUserInfo();
  const isAdmin = currentUser?.is_admin ?? false;
  const searchParams = useSearchParams();
  const [selectedStoryId, setSelectedStoryId] = useState<string>("");
  const [deepResearchPrompt, setDeepResearchPrompt] = useState("");
  const [deepResearchReport, setDeepResearchReport] = useState<DeepResearchReport | null>(null);
  const [deepResearchError, setDeepResearchError] = useState<string | null>(null);
  const storyParam = searchParams.get("story");

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
  }, [storyParam, selectedStoryId]);

  useEffect(() => {
    setDeepResearchPrompt("");
    setDeepResearchReport(null);
    setDeepResearchError(null);
  }, [selectedStoryId]);

  const { data: storySources, isLoading: sourcesLoading } = useQuery<ResearchSource[]>({
    queryKey: ["story-sources", selectedStoryId],
    queryFn: () => apiClient.getResearchSources(selectedStoryId),
    enabled: !!selectedStoryId,
  });

  const deepResearchMutation = useMutation({
    mutationFn: ({
      storyId,
      prompt,
    }: {
      storyId: string;
      prompt: string;
    }) => apiClient.generateDeepResearchReport(storyId, prompt),
    onMutate: () => {
      setDeepResearchError(null);
    },
    onSuccess: (response, variables) => {
      if (variables.storyId !== selectedStoryId) return;
      setDeepResearchReport(response);
      setDeepResearchPrompt("");
    },
    onError: (error: Error) => {
      setDeepResearchError(error.message || "Anthropic deep research failed.");
    },
  });

  const handleDeepResearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const prompt = deepResearchPrompt.trim();
    if (!selectedStoryId || !prompt || deepResearchMutation.isPending) return;

    deepResearchMutation.mutate({
      storyId: selectedStoryId,
      prompt,
    });
  };

  const highCredSources = (storySources ?? []).filter((source) => source.credibility === "high").length;

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
            Review the source pack and editorial signals for each story.
          </span>
        </div>
        {selectedStory && (
          <Link href={`/results/${selectedStory.id}`} className="btn-secondary" style={{ textDecoration: "none" }}>
            Open story
          </Link>
        )}
      </div>

      <div style={{ padding: 28, display: "grid", gridTemplateColumns: "minmax(320px, 420px) minmax(0, 1fr)", gap: 18 }}>
        {/* Left panel */}
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
                      {isAdmin && story.owner_email
                        ? `${story.title} — ${story.owner_email}`
                        : story.title}
                    </option>
                  ))}
                </select>

                {selectedStory ? (
                  <div>
                    <p style={{ fontSize: 13, fontWeight: 500 }}>{selectedStory.title}</p>
                    {isAdmin && selectedStory.owner_email && (
                      <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 4 }}>
                        Created by {selectedStory.owner_email}
                      </p>
                    )}
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
                    </div>
                  </div>
                ) : (
                  <p style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                    Pick a story to inspect its source pack and research details.
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
        </div>

        {/* Right panel */}
        <div className="card" style={{ padding: "18px 20px" }}>
          <div className="section-rule"><span>Editorial snapshot</span></div>
          {!selectedStory ? (
            <div
              style={{
                border: "0.5px dashed var(--color-border-primary)",
                borderRadius: 12,
                padding: "32px 24px",
                textAlign: "center",
                color: "var(--color-text-secondary)",
              }}
            >
              <p style={{ fontSize: 13, marginBottom: 4 }}>No story selected.</p>
              <p style={{ fontSize: 12 }}>Choose a story to review its research details.</p>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div>
                <p style={{ fontSize: 13, fontWeight: 500, marginBottom: 6 }}>{selectedStory.title}</p>
                <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.7 }}>
                  {selectedStory.topic}
                </p>
              </div>

              <div className="card" style={{ padding: "14px 16px" }}>
                <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 8 }}>Source pack</p>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <div>
                    <p style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>Total sources</p>
                    <p style={{ fontSize: 18, fontWeight: 500 }}>{storySources?.length ?? 0}</p>
                  </div>
                  <div>
                    <p style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>High credibility</p>
                    <p style={{ fontSize: 18, fontWeight: 500 }}>{highCredSources}</p>
                  </div>
                </div>
              </div>

              <div className="card" style={{ padding: "14px 16px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", marginBottom: 12 }}>
                  <div>
                    <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 4 }}>Anthropic Deep Research</p>
                    <p style={{ fontSize: 11, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                      Produces a separate report from Anthropic web research. The script stays unchanged.
                    </p>
                  </div>
                  {selectedStory.status === "completed" && (
                    <span className="badge badge-success" style={{ fontSize: 10, border: "none", flexShrink: 0 }}>
                      Script-aware
                    </span>
                  )}
                </div>

                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 10,
                    maxHeight: 360,
                    overflow: "auto",
                    paddingRight: 4,
                    marginBottom: 12,
                  }}
                >
                  {deepResearchMutation.isPending ? (
                    <div
                      style={{
                        border: "0.5px solid var(--color-border-tertiary)",
                        borderRadius: 8,
                        padding: "18px 16px",
                        display: "flex",
                        gap: 10,
                        alignItems: "flex-start",
                        color: "var(--color-text-secondary)",
                      }}
                    >
                      <Loader2 size={16} className="animate-spin" style={{ color: "var(--color-action)", flexShrink: 0, marginTop: 2 }} />
                      <div>
                        <p style={{ fontSize: 12, color: "var(--color-text-primary)", marginBottom: 4 }}>
                          Running Anthropic Deep Research
                        </p>
                        <p style={{ fontSize: 12, lineHeight: 1.6 }}>
                          Searching, cross-checking, and drafting a downloadable report.
                        </p>
                      </div>
                    </div>
                  ) : !deepResearchReport ? (
                    <div
                      style={{
                        border: "0.5px dashed var(--color-border-primary)",
                        borderRadius: 8,
                        padding: "18px 16px",
                        color: "var(--color-text-secondary)",
                      }}
                    >
                      <p style={{ fontSize: 12, lineHeight: 1.6 }}>
                        Ask for missing evidence, fresher numbers, experts, counter-evidence, or source leads.
                      </p>
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          gap: 12,
                          alignItems: "center",
                          border: "0.5px solid var(--color-border-tertiary)",
                          borderRadius: 8,
                          padding: "10px 12px",
                        }}
                      >
                        <div>
                          <p style={{ fontSize: 12, fontWeight: 500 }}>Additional research report ready</p>
                          <p style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 3 }}>
                            {deepResearchReport.web_search_requests} Anthropic web searches · {deepResearchReport.citations.length} citations
                          </p>
                        </div>
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => downloadDeepResearchReport(deepResearchReport)}
                        >
                          <Download size={13} />
                          Download
                        </button>
                      </div>

                      <div
                        style={{
                          background: "var(--color-background-secondary)",
                          border: "0.5px solid var(--color-border-tertiary)",
                          borderRadius: 8,
                          padding: "12px 14px",
                        }}
                      >
                        <p
                          style={{
                            fontSize: 12,
                            color: "var(--color-text-primary)",
                            lineHeight: 1.7,
                            whiteSpace: "pre-wrap",
                          }}
                        >
                          {deepResearchReport.report_markdown}
                        </p>
                      </div>

                      {deepResearchReport.citations.length > 0 && (
                        <div
                          style={{
                            border: "0.5px solid var(--color-border-tertiary)",
                            borderRadius: 8,
                            padding: "10px 12px",
                          }}
                        >
                          <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 8 }}>Citations</p>
                          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                            {deepResearchReport.citations.map((citation, index) => (
                              <a
                                key={`${citation.url}-${index}`}
                                href={citation.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                style={{
                                  color: "var(--color-action)",
                                  fontSize: 12,
                                  lineHeight: 1.5,
                                  overflowWrap: "anywhere",
                                }}
                              >
                                {citation.title}
                              </a>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {deepResearchError && (
                  <p role="alert" style={{ fontSize: 12, color: "var(--color-danger)", marginBottom: 10 }}>
                    {deepResearchError}
                  </p>
                )}

                <form onSubmit={handleDeepResearch} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <textarea
                    value={deepResearchPrompt}
                    onChange={(event) => setDeepResearchPrompt(event.target.value)}
                    className="input"
                    rows={4}
                    placeholder="Ask Anthropic Deep Research for missing evidence, updated data, expert sources, or verification gaps."
                    style={{ resize: "vertical", minHeight: 96, lineHeight: 1.5 }}
                    disabled={deepResearchMutation.isPending}
                  />
                  <div style={{ display: "flex", justifyContent: "flex-end" }}>
                    <button
                      type="submit"
                      className="btn-primary"
                      disabled={!selectedStoryId || !deepResearchPrompt.trim() || deepResearchMutation.isPending}
                    >
                      {deepResearchMutation.isPending ? (
                        <Loader2 size={13} className="animate-spin" />
                      ) : (
                        <Search size={13} />
                      )}
                      Run Deep Research
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

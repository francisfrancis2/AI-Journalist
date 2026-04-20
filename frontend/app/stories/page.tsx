"use client";

import { Suspense } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams, useRouter } from "next/navigation";
import { Loader2, ArrowLeft } from "lucide-react";
import { StoryCard } from "@/components/StoryCard";
import { ScriptViewer } from "@/components/ScriptViewer";
import { apiClient, type Story, type FinalScript } from "@/lib/api";

export default function StoriesPage() {
  return (
    <Suspense
      fallback={
        <div style={{ display: "flex", justifyContent: "center", padding: "60px 0" }}>
          <Loader2 size={20} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
        </div>
      }
    >
      <StoriesPageInner />
    </Suspense>
  );
}

function StoriesPageInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const storyId = searchParams.get("id");

  if (storyId) {
    return <StoryDetailView storyId={storyId} onBack={() => router.push("/stories")} />;
  }

  return <StoriesListView />;
}

// ── Stories List ──────────────────────────────────────────────────────────────

function StoriesListView() {
  const { data: stories, isLoading, error } = useQuery<Story[]>({
    queryKey: ["stories", "all"],
    queryFn: () => apiClient.listStories(100),
    refetchInterval: 10_000,
  });

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
        <span style={{ fontSize: 18, fontWeight: 500 }}>Stories</span>
        <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>
          {stories?.length ?? 0} total
        </span>
      </div>

      <div style={{ padding: 28 }}>
        {isLoading && (
          <div style={{ display: "flex", justifyContent: "center", padding: "60px 0" }}>
            <Loader2 size={20} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
          </div>
        )}

        {error && (
          <div
            style={{
              padding: "12px 16px",
              background: "var(--color-danger-bg)",
              border: "0.5px solid #fecaca",
              borderRadius: "var(--border-radius-md)",
              fontSize: 13,
              color: "var(--color-danger)",
            }}
          >
            Failed to load stories: {(error as Error).message}
          </div>
        )}

        {stories && stories.length === 0 && (
          <div style={{ textAlign: "center", padding: "60px 0", fontSize: 13, color: "var(--color-text-secondary)" }}>
            No stories found. Go to the dashboard to create one.
          </div>
        )}

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
            gap: 16,
          }}
        >
          {stories?.map((story) => (
            <StoryCard key={story.id} story={story} showLink />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Story Detail View ─────────────────────────────────────────────────────────

function StoryDetailView({
  storyId,
  onBack,
}: {
  storyId: string;
  onBack: () => void;
}) {
  const { data: story, isLoading: storyLoading } = useQuery<Story>({
    queryKey: ["story", storyId],
    queryFn: () => apiClient.getStory(storyId),
    refetchInterval: (query) => {
      const s = query.state.data as Story | undefined;
      const active = ["pending", "researching", "analysing", "writing_storyline", "evaluating", "scripting"];
      return s?.status && active.includes(s.status) ? 4_000 : false;
    },
  });

  const { data: script } = useQuery<FinalScript>({
    queryKey: ["script", storyId],
    queryFn: () => apiClient.getScript(storyId),
    enabled: story?.status === "completed",
  });

  if (storyLoading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: "60px 0" }}>
        <Loader2 size={20} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
      </div>
    );
  }

  if (!story) {
    return (
      <div style={{ textAlign: "center", padding: "60px 0", fontSize: 13, color: "var(--color-text-secondary)" }}>
        Story not found.
      </div>
    );
  }

  const isComplete = story.status === "completed";
  const isFailed = story.status === "failed";
  const isRunning = !isComplete && !isFailed;

  return (
    <div style={{ minHeight: "100%", background: "var(--color-background-tertiary)" }}>
      <div
        style={{
          background: "var(--color-background-primary)",
          borderBottom: "0.5px solid var(--color-border-tertiary)",
          padding: "14px 28px",
        }}
      >
        <button
          onClick={onBack}
          className="btn-ghost"
          style={{ padding: "4px 0", marginBottom: 10, fontSize: 12, gap: 4 }}
        >
          <ArrowLeft size={13} /> Back to Stories
        </button>
        <h1 style={{ fontSize: 18, fontWeight: 500, marginBottom: 4 }}>{story.title}</h1>
        <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>{story.topic}</p>
      </div>

      <div style={{ padding: 28, maxWidth: 800 }}>
        {isRunning && <PipelineProgress status={story.status} />}

        {isFailed && story.error_message && (
          <div
            style={{
              padding: "12px 16px",
              background: "var(--color-danger-bg)",
              border: "0.5px solid #fecaca",
              borderRadius: "var(--border-radius-md)",
              fontSize: 13,
              color: "var(--color-danger)",
            }}
          >
            {story.error_message}
          </div>
        )}

        {isComplete && script && <ScriptViewer script={script} />}
      </div>
    </div>
  );
}

// ── Pipeline progress ─────────────────────────────────────────────────────────

const PIPELINE_STAGES = [
  { status: "researching",       label: "Researching the web" },
  { status: "analysing",         label: "Analysing findings" },
  { status: "writing_storyline", label: "Crafting storyline" },
  { status: "evaluating",        label: "Evaluating quality" },
  { status: "scripting",         label: "Writing script" },
];

function PipelineProgress({ status }: { status: string }) {
  const currentIdx = PIPELINE_STAGES.findIndex((s) => s.status === status);
  const pct = Math.max(((currentIdx + 1) / PIPELINE_STAGES.length) * 100, 8);

  return (
    <div className="card" style={{ padding: "24px", maxWidth: 480, margin: "0 auto", textAlign: "center" }}>
      <Loader2 size={20} className="animate-spin" style={{ color: "var(--color-text-tertiary)", marginBottom: 14 }} />
      <p style={{ fontSize: 14, fontWeight: 500, marginBottom: 4 }}>
        {status.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}…
      </p>
      <p style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 16 }}>
        Stage {Math.max(currentIdx + 1, 1)} of {PIPELINE_STAGES.length}
      </p>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

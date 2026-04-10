"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams, useRouter } from "next/navigation";
import { Loader2, ArrowLeft } from "lucide-react";
import { StoryCard } from "@/components/StoryCard";
import { ScriptViewer } from "@/components/ScriptViewer";
import { apiClient, type Story, type FinalScript } from "@/lib/api";

export default function StoriesPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const storyId = searchParams.get("id");

  // If a story ID is in the URL, show the detail / script view
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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">All Stories</h1>
        <span className="text-sm text-[color:var(--palette-muted)]">
          {stories?.length ?? 0} total
        </span>
      </div>

      {isLoading && (
        <div className="flex justify-center py-16">
          <Loader2 className="w-8 h-8 animate-spin text-[color:var(--palette-primary)]" />
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-red-700 text-sm">
          Failed to load stories: {(error as Error).message}
        </div>
      )}

      {stories && stories.length === 0 && (
        <div className="text-center py-16 text-[color:var(--palette-muted)]">
          No stories found. Go to the dashboard to create one.
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {stories?.map((story) => (
          <StoryCard key={story.id} story={story} showLink />
        ))}
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
      <div className="flex justify-center py-16">
        <Loader2 className="w-8 h-8 animate-spin text-[color:var(--palette-primary)]" />
      </div>
    );
  }

  if (!story) {
    return (
      <div className="text-center py-16 text-[color:var(--palette-muted)]">Story not found.</div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <button
        onClick={onBack}
        className="flex items-center gap-2 text-sm text-[color:var(--palette-muted)] hover:text-[color:var(--palette-primary)] transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Stories
      </button>

      {/* Story Header */}
      <div className="surface-card p-6">
        <div className="flex items-start justify-between gap-4 mb-3">
          <h1 className="text-2xl font-bold leading-tight">{story.title}</h1>
          <StatusBadge status={story.status} />
        </div>
        <p className="text-[color:var(--palette-muted)] text-sm mb-4">{story.topic}</p>

        {story.quality_score !== null && story.quality_score !== undefined && (
          <div className="flex items-center gap-6 text-sm">
            <Metric
              label="Quality Score"
              value={`${(story.quality_score * 100).toFixed(0)}%`}
            />
            {story.estimated_duration_minutes && (
              <Metric
                label="Duration"
                value={`${story.estimated_duration_minutes} min`}
              />
            )}
            {story.word_count && (
              <Metric label="Words" value={story.word_count.toLocaleString()} />
            )}
          </div>
        )}

        {story.error_message && (
          <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 p-3 text-red-700 text-sm">
            Error: {story.error_message}
          </div>
        )}
      </div>

      {/* Script Viewer */}
      {script ? (
        <ScriptViewer script={script} />
      ) : story.status !== "completed" ? (
        <PipelineProgress status={story.status} />
      ) : null}
    </div>
  );
}

// ── Helper Components ─────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-[rgba(124,237,253,0.1)] text-[color:var(--palette-muted)]",
  researching: "bg-[rgba(124,237,253,0.18)] text-[color:var(--palette-primary)]",
  analysing: "bg-cyan-50 text-cyan-700",
  writing_storyline: "bg-[rgba(28,33,170,0.08)] text-[color:var(--palette-primary)]",
  evaluating: "bg-amber-50 text-amber-700",
  scripting: "bg-emerald-50 text-emerald-700",
  completed: "bg-green-50 text-green-700",
  failed: "bg-red-50 text-red-700",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider whitespace-nowrap ${STATUS_STYLES[status] ?? "bg-[rgba(124,237,253,0.1)] text-[color:var(--palette-muted)]"}`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[color:var(--palette-muted)] text-xs">{label}</p>
      <p className="text-[color:var(--palette-ink)] font-semibold">{value}</p>
    </div>
  );
}

const PIPELINE_STAGES = [
  { status: "researching", label: "Researching the web" },
  { status: "analysing", label: "Analysing findings" },
  { status: "writing_storyline", label: "Crafting storyline" },
  { status: "evaluating", label: "Evaluating quality" },
  { status: "scripting", label: "Writing script" },
];

function PipelineProgress({ status }: { status: string }) {
  const currentIdx = PIPELINE_STAGES.findIndex((s) => s.status === status);

  return (
    <div className="surface-card p-6">
      <h2 className="text-lg font-semibold mb-6">Pipeline Progress</h2>
      <div className="space-y-4">
        {PIPELINE_STAGES.map((stage, idx) => {
          const done = idx < currentIdx;
          const active = idx === currentIdx;
          return (
            <div key={stage.status} className="flex items-center gap-3">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0 ${
                  done
                    ? "bg-green-600 text-white"
                    : active
                    ? "bg-[color:var(--palette-primary)] text-white"
                    : "bg-[rgba(124,237,253,0.14)] text-[color:var(--palette-muted)]"
                }`}
              >
                {done ? "✓" : idx + 1}
              </div>
              <span
                className={`text-sm ${
                  active ? "text-[color:var(--palette-primary)] font-semibold" : done ? "text-[color:var(--palette-muted)]" : "text-[rgba(77,77,79,0.55)]"
                }`}
              >
                {stage.label}
                {active && (
                  <span className="ml-2 inline-flex items-center gap-1 text-[color:var(--palette-primary)]">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    running...
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

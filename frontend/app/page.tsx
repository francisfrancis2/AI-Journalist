"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Sparkles } from "lucide-react";
import { StoryCard } from "@/components/StoryCard";
import { apiClient, type Story, type StoryCreate } from "@/lib/api";

const TONE_OPTIONS = [
  { value: "explanatory", label: "Explanatory" },
  { value: "investigative", label: "Investigative" },
  { value: "narrative", label: "Narrative" },
  { value: "profile", label: "Profile" },
  { value: "trend", label: "Trend" },
] as const;

export default function DashboardPage() {
  const queryClient = useQueryClient();
  const [topic, setTopic] = useState("");
  const [tone, setTone] = useState<StoryCreate["tone"]>("explanatory");
  const [formError, setFormError] = useState<string | null>(null);

  const { data: stories, isLoading } = useQuery<Story[]>({
    queryKey: ["stories"],
    queryFn: () => apiClient.listStories(),
    refetchInterval: 8_000,
  });

  const createMutation = useMutation({
    mutationFn: (payload: StoryCreate) => apiClient.createStory(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stories"] });
      setTopic("");
      setFormError(null);
    },
    onError: (err: Error) => setFormError(err.message),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (topic.trim().length < 10) {
      setFormError("Topic must be at least 10 characters.");
      return;
    }
    createMutation.mutate({ topic: topic.trim(), tone });
  };

  const inProgress = stories?.filter(
    (s) => !["completed", "failed"].includes(s.status)
  );
  const completed = stories?.filter((s) => s.status === "completed");
  const failed = stories?.filter((s) => s.status === "failed");

  return (
    <div className="space-y-10">
      {/* ── Hero ── */}
      <section className="text-center py-8">
        <h1 className="text-4xl font-bold tracking-tight text-gradient mb-3">
          AI Journalist
        </h1>
        <p className="text-gray-400 max-w-xl mx-auto text-lg">
          Give it a topic. It researches the web, finds the story, writes the
          script — ready for a 10–15 minute documentary.
        </p>
      </section>

      {/* ── Create Story Form ── */}
      <section className="max-w-2xl mx-auto">
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-indigo-400" />
            New Story
          </h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="topic"
                className="block text-sm font-medium text-gray-300 mb-1"
              >
                Research Topic
              </label>
              <textarea
                id="topic"
                rows={3}
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="e.g. How NVIDIA became the most valuable company in the world"
                className="w-full rounded-lg bg-gray-800 border border-gray-700 px-4 py-3 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
              />
            </div>

            <div className="flex items-center gap-4">
              <div className="flex-1">
                <label
                  htmlFor="tone"
                  className="block text-sm font-medium text-gray-300 mb-1"
                >
                  Documentary Tone
                </label>
                <select
                  id="tone"
                  value={tone}
                  onChange={(e) =>
                    setTone(e.target.value as StoryCreate["tone"])
                  }
                  className="w-full rounded-lg bg-gray-800 border border-gray-700 px-4 py-2.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  {TONE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              <button
                type="submit"
                disabled={createMutation.isPending || !topic.trim()}
                className="mt-5 flex items-center gap-2 px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-semibold transition-colors"
              >
                {createMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Plus className="w-4 h-4" />
                )}
                Start Research
              </button>
            </div>

            {formError && (
              <p className="text-red-400 text-sm">{formError}</p>
            )}
          </form>
        </div>
      </section>

      {/* ── Story Lists ── */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-indigo-400" />
        </div>
      ) : (
        <div className="space-y-8">
          {inProgress && inProgress.length > 0 && (
            <section>
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
                In Progress ({inProgress.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {inProgress.map((story) => (
                  <StoryCard key={story.id} story={story} />
                ))}
              </div>
            </section>
          )}

          {completed && completed.length > 0 && (
            <section>
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
                Completed ({completed.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {completed.map((story) => (
                  <StoryCard key={story.id} story={story} />
                ))}
              </div>
            </section>
          )}

          {failed && failed.length > 0 && (
            <section>
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
                Failed ({failed.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {failed.map((story) => (
                  <StoryCard key={story.id} story={story} />
                ))}
              </div>
            </section>
          )}

          {!stories?.length && (
            <div className="text-center py-16 text-gray-600">
              No stories yet. Submit your first topic above.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

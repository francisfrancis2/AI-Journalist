"use client";

import { formatDistanceToNow } from "date-fns";
import { Clock, FileText, TrendingUp } from "lucide-react";
import Link from "next/link";
import type { Story } from "@/lib/api";

interface StoryCardProps {
  story: Story;
  showLink?: boolean;
}

const STATUS_CONFIG: Record<
  string,
  { label: string; color: string; pulse: boolean }
> = {
  pending: { label: "Pending", color: "text-[color:var(--palette-muted)]", pulse: false },
  researching: { label: "Researching", color: "text-[color:var(--palette-primary)]", pulse: true },
  analysing: { label: "Analysing", color: "text-cyan-700", pulse: true },
  writing_storyline: {
    label: "Writing Storyline",
    color: "text-[color:var(--palette-primary)]",
    pulse: true,
  },
  evaluating: { label: "Evaluating", color: "text-amber-700", pulse: true },
  scripting: { label: "Scripting", color: "text-emerald-700", pulse: true },
  completed: { label: "Completed", color: "text-green-700", pulse: false },
  failed: { label: "Failed", color: "text-red-700", pulse: false },
};

const TONE_COLORS: Record<string, string> = {
  explanatory: "bg-[rgba(124,237,253,0.14)] text-[color:var(--palette-primary)]",
  investigative: "bg-red-50 text-red-700",
  narrative: "bg-[rgba(28,33,170,0.08)] text-[color:var(--palette-primary)]",
  profile: "bg-amber-50 text-amber-700",
  trend: "bg-cyan-50 text-cyan-700",
};

export function StoryCard({ story, showLink = false }: StoryCardProps) {
  const statusCfg = STATUS_CONFIG[story.status] ?? STATUS_CONFIG.pending;
  const toneColor = TONE_COLORS[story.tone] ?? "bg-[rgba(124,237,253,0.14)] text-[color:var(--palette-muted)]";

  const card = (
    <div className="surface-card flex h-full flex-col gap-3 p-5 transition-colors hover:border-[rgba(28,33,170,0.22)]">
      {/* Title & Tone Badge */}
      <div className="flex items-start justify-between gap-2">
        <h3 className="flex-1 text-sm font-semibold leading-snug text-[color:var(--palette-ink)] line-clamp-2">
          {story.title}
        </h3>
        <span
          className={`flex-shrink-0 rounded-full px-2.5 py-1 text-xs font-medium capitalize ${toneColor}`}
        >
          {story.tone}
        </span>
      </div>

      {/* Topic */}
      <p className="text-xs text-[color:var(--palette-muted)] line-clamp-2">{story.topic}</p>

      {/* Metrics row */}
      <div className="flex items-center gap-4 text-xs text-[color:var(--palette-muted)]">
        {story.estimated_duration_minutes && (
          <span className="flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {story.estimated_duration_minutes} min
          </span>
        )}
        {story.quality_score != null && (
          <span className="flex items-center gap-1">
            <TrendingUp className="w-3 h-3" />
            {(story.quality_score * 100).toFixed(0)}%
          </span>
        )}
        {story.status === "completed" && (
          <span className="flex items-center gap-1 text-green-700">
            <FileText className="w-3 h-3" />
            Script ready
          </span>
        )}
      </div>

      {/* Status + Timestamp */}
      <div className="mt-auto flex items-center justify-between border-t border-[rgba(28,33,170,0.1)] pt-3">
        <span className={`text-xs font-semibold flex items-center gap-1.5 ${statusCfg.color}`}>
          {statusCfg.pulse && (
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-current opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-current" />
            </span>
          )}
          {statusCfg.label}
        </span>
        <span className="text-xs text-[rgba(77,77,79,0.55)]">
          {formatDistanceToNow(new Date(story.created_at), { addSuffix: true })}
        </span>
      </div>
    </div>
  );

  if (showLink) {
    return (
      <Link href={`/stories?id=${story.id}`} className="block h-full">
        {card}
      </Link>
    );
  }

  return card;
}

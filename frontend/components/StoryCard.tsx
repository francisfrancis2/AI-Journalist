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
  pending: { label: "Pending", color: "text-gray-400", pulse: false },
  researching: { label: "Researching", color: "text-blue-400", pulse: true },
  analysing: { label: "Analysing", color: "text-cyan-400", pulse: true },
  writing_storyline: {
    label: "Writing Storyline",
    color: "text-violet-400",
    pulse: true,
  },
  evaluating: { label: "Evaluating", color: "text-amber-400", pulse: true },
  scripting: { label: "Scripting", color: "text-emerald-400", pulse: true },
  completed: { label: "Completed", color: "text-green-400", pulse: false },
  failed: { label: "Failed", color: "text-red-400", pulse: false },
};

const TONE_COLORS: Record<string, string> = {
  explanatory: "bg-blue-900/40 text-blue-300",
  investigative: "bg-red-900/40 text-red-300",
  narrative: "bg-purple-900/40 text-purple-300",
  profile: "bg-amber-900/40 text-amber-300",
  trend: "bg-teal-900/40 text-teal-300",
};

export function StoryCard({ story, showLink = false }: StoryCardProps) {
  const statusCfg = STATUS_CONFIG[story.status] ?? STATUS_CONFIG.pending;
  const toneColor = TONE_COLORS[story.tone] ?? "bg-gray-800 text-gray-400";

  const card = (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-5 flex flex-col gap-3 hover:border-gray-700 transition-colors h-full">
      {/* Title & Tone Badge */}
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold text-sm leading-snug line-clamp-2 flex-1">
          {story.title}
        </h3>
        <span
          className={`px-2 py-0.5 rounded text-xs font-medium flex-shrink-0 capitalize ${toneColor}`}
        >
          {story.tone}
        </span>
      </div>

      {/* Topic */}
      <p className="text-gray-500 text-xs line-clamp-2">{story.topic}</p>

      {/* Metrics row */}
      <div className="flex items-center gap-4 text-xs text-gray-500">
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
          <span className="flex items-center gap-1 text-green-500">
            <FileText className="w-3 h-3" />
            Script ready
          </span>
        )}
      </div>

      {/* Status + Timestamp */}
      <div className="mt-auto flex items-center justify-between pt-2 border-t border-gray-800">
        <span className={`text-xs font-semibold flex items-center gap-1.5 ${statusCfg.color}`}>
          {statusCfg.pulse && (
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-current opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-current" />
            </span>
          )}
          {statusCfg.label}
        </span>
        <span className="text-xs text-gray-600">
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

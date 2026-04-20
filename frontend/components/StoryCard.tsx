"use client";

import { formatDistanceToNow } from "date-fns";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import Link from "next/link";
import type { Story } from "@/lib/api";

interface StoryCardProps {
  story: Story;
  showLink?: boolean;
}

export function StoryCard({ story, showLink = false }: StoryCardProps) {
  const isComplete = story.status === "completed";
  const isFailed   = story.status === "failed";
  const isRunning  = !isComplete && !isFailed;

  const card = (
    <div
      className="card"
      style={{
        padding: "16px 18px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        height: "100%",
        transition: "border-color 0.12s",
      }}
    >
      {/* Title + tone */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
        <p
          style={{
            fontSize: 13,
            fontWeight: 500,
            color: "var(--color-text-primary)",
            lineHeight: 1.4,
            overflow: "hidden",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            flex: 1,
          }}
        >
          {story.title}
        </p>
        <span
          className={`badge tone-${story.tone}`}
          style={{ fontSize: 11, padding: "2px 8px", borderRadius: 20, border: "none", flexShrink: 0 }}
        >
          {story.tone}
        </span>
      </div>

      {/* Topic */}
      <p
        style={{
          fontSize: 12,
          color: "var(--color-text-secondary)",
          overflow: "hidden",
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
        }}
      >
        {story.topic}
      </p>

      {/* Metrics */}
      {(story.estimated_duration_minutes || story.quality_score != null) && (
        <div style={{ display: "flex", gap: 12, fontSize: 12, color: "var(--color-text-tertiary)" }}>
          {story.estimated_duration_minutes && (
            <span>{story.estimated_duration_minutes} min</span>
          )}
          {story.quality_score != null && (
            <span>Quality {(story.quality_score * 100).toFixed(0)}%</span>
          )}
        </div>
      )}

      {/* Status + timestamp */}
      <div
        style={{
          marginTop: "auto",
          paddingTop: 10,
          borderTop: "0.5px solid var(--color-border-tertiary)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        {isComplete && (
          <span className="badge badge-success" style={{ fontSize: 11 }}>
            <CheckCircle2 size={10} /> Completed
          </span>
        )}
        {isFailed && (
          <span className="badge badge-danger" style={{ fontSize: 11 }}>
            <XCircle size={10} /> Failed
          </span>
        )}
        {isRunning && (
          <span className="badge badge-active" style={{ fontSize: 11 }}>
            <Loader2 size={10} className="animate-spin" />
            {story.status.replace(/_/g, " ")}
          </span>
        )}
        <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
          {formatDistanceToNow(new Date(story.created_at), { addSuffix: true })}
        </span>
      </div>
    </div>
  );

  if (showLink) {
    return (
      <Link href={`/stories?id=${story.id}`} style={{ display: "block", height: "100%", textDecoration: "none" }}>
        {card}
      </Link>
    );
  }

  return card;
}

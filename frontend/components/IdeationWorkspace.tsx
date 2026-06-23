"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Download,
  Edit3,
  ExternalLink,
  Loader2,
  MessageSquareText,
  Plus,
  Send,
  Sparkles,
} from "lucide-react";
import {
  apiClient,
  type IdeationOperationData,
  type IdeationChapter,
  type IdeationSourceLink,
  type Story,
  type StoryAngle,
} from "@/lib/api";
import { downloadSourceListPdf } from "@/lib/script-export";
import { storyStatusBadgeClass, storyStatusLabel } from "@/lib/story-status";

type WorkspaceStage = "angles" | "hook" | "chapters";

const STAGE_LINKS: Array<{ stage: WorkspaceStage; label: string }> = [
  { stage: "angles", label: "Angles" },
  { stage: "hook", label: "Story Hook" },
  { stage: "chapters", label: "Chapters" },
];

type ExportNotice = {
  tone: "success" | "error";
  text: string;
};

function stagePath(storyId: string, stage: WorkspaceStage): string {
  return `/ideation/${storyId}/${stage}`;
}

function countWords(value: string): number {
  const trimmed = value.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

function normalizeChapterDrafts(chapters: IdeationChapter[]): IdeationChapter[] {
  return chapters.map((chapter, index) => ({
    chapter_number: index + 1,
    title: chapter.title.trim(),
    purpose: chapter.purpose.trim(),
    key_points: chapter.key_points
      .map((point) => point.trim())
      .filter(Boolean),
  }));
}

function chapterDraftsEqual(left: IdeationChapter[], right: IdeationChapter[]): boolean {
  return JSON.stringify(normalizeChapterDrafts(left)) === JSON.stringify(normalizeChapterDrafts(right));
}

function hookOptionsForStory(story: Story): string[] {
  const seen = new Set<string>();
  return [
    story.story_hook,
    ...(story.hook_options_data ?? []),
  ]
    .map((hook) => (hook ?? "").trim())
    .filter((hook) => {
      const key = hook.toLowerCase();
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function formatElapsed(startedAt: string | undefined): string {
  if (!startedAt) return "";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(startedAt).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
}

function uniqueSignalSources(sources: IdeationSourceLink[]): IdeationSourceLink[] {
  const seen = new Set<string>();
  const unique: IdeationSourceLink[] = [];
  for (const source of sources) {
    const key = (source.url || source.title).trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    unique.push(source);
  }
  return unique;
}

function OperationNotice({ operation }: { operation: IdeationOperationData }) {
  if (operation.status === "failed") {
    return (
      <div
        role="alert"
        style={{
          border: "0.5px solid #fecaca",
          background: "var(--color-danger-bg)",
          color: "var(--color-danger)",
          borderRadius: "var(--border-radius-md)",
          padding: "10px 12px",
          fontSize: 12,
          lineHeight: 1.5,
        }}
      >
        {operation.error_message || "This request could not complete. Try a narrower request."}
      </div>
    );
  }

  return (
    <div
      style={{
        border: "0.5px solid var(--color-border-tertiary)",
        background: "var(--color-background-secondary)",
        borderRadius: "var(--border-radius-md)",
        padding: "11px 12px",
        display: "flex",
        gap: 9,
        alignItems: "flex-start",
      }}
    >
      <Loader2 size={14} className="animate-spin" style={{ color: "var(--color-action)", marginTop: 2, flexShrink: 0 }} />
      <div>
        <p style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-primary)", marginBottom: 2 }}>
          {operation.message || "Working on your request."}
        </p>
        <p style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
          Running in the background{operation.started_at ? ` · elapsed ${formatElapsed(operation.started_at)}` : ""}
        </p>
      </div>
    </div>
  );
}

function ArtifactShell({ title, kicker, children }: { title: string; kicker: string; children: React.ReactNode }) {
  return (
    <section className="card" style={{ padding: 18, minWidth: 0 }}>
      <p className="section-label" style={{ marginBottom: 6 }}>{kicker}</p>
      <h1 style={{ fontSize: 18, margin: "0 0 16px" }}>{title}</h1>
      {children}
    </section>
  );
}

function AngleCard({
  angle,
  selected,
  onSelect,
}: {
  angle: StoryAngle;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      style={{
        textAlign: "left",
        padding: "13px 14px",
        border: `1px solid ${selected ? "var(--color-action)" : "var(--color-border-tertiary)"}`,
        borderRadius: "var(--border-radius-md)",
        background: selected ? "rgba(28, 38, 168, 0.04)" : "#fff",
        cursor: "pointer",
        fontFamily: "var(--font-sans)",
        display: "flex",
        gap: 10,
      }}
    >
      <div
        style={{
          width: 16,
          height: 16,
          borderRadius: "50%",
          border: `1.5px solid ${selected ? "var(--color-action)" : "var(--color-border-primary)"}`,
          marginTop: 2,
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {selected && <div style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--color-action)" }} />}
      </div>
      <div style={{ minWidth: 0 }}>
        <p style={{ fontSize: 13, lineHeight: 1.5, color: "var(--color-text-primary)", marginBottom: 6 }}>
          {angle.angle}
        </p>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <span className="badge badge-neutral" style={{ fontSize: 10 }}>{angle.framing_axis}</span>
          {angle.rationale && (
            <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{angle.rationale}</span>
          )}
        </div>
      </div>
    </button>
  );
}

function HookCard({
  hook,
  selected,
  onSelect,
}: {
  hook: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      style={{
        textAlign: "left",
        padding: "12px 14px",
        border: `1px solid ${selected ? "var(--color-action)" : "var(--color-border-tertiary)"}`,
        borderRadius: "var(--border-radius-md)",
        background: selected ? "rgba(28, 38, 168, 0.04)" : "#fff",
        cursor: "pointer",
        fontFamily: "var(--font-sans)",
        display: "flex",
        gap: 10,
      }}
    >
      <div
        style={{
          width: 16,
          height: 16,
          borderRadius: "50%",
          border: `1.5px solid ${selected ? "var(--color-action)" : "var(--color-border-primary)"}`,
          marginTop: 2,
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {selected && <div style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--color-action)" }} />}
      </div>
      <p style={{ fontSize: 13, lineHeight: 1.55, color: "var(--color-text-primary)" }}>
        {hook}
      </p>
    </button>
  );
}

function ChapterList({ chapters }: { chapters: IdeationChapter[] }) {
  if (!chapters.length) {
    return <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>No chapter outline yet. Ask the chat to draft one.</p>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {chapters.map((chapter) => (
        <div
          key={`${chapter.chapter_number}-${chapter.title}`}
          style={{
            padding: "12px 14px",
            border: "0.5px solid var(--color-border-tertiary)",
            borderRadius: "var(--border-radius-md)",
            background: "#fff",
          }}
        >
          <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginBottom: 3 }}>
            Chapter {chapter.chapter_number}
          </p>
          <h2 style={{ fontSize: 14, margin: "0 0 5px" }}>{chapter.title}</h2>
          <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5, marginBottom: 8 }}>
            {chapter.purpose}
          </p>
          {chapter.key_points.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: 18, color: "var(--color-text-primary)", fontSize: 12, lineHeight: 1.6 }}>
              {chapter.key_points.map((point) => <li key={point}>{point}</li>)}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

function ChapterEditor({
  chapters,
  onChange,
}: {
  chapters: IdeationChapter[];
  onChange: (chapters: IdeationChapter[]) => void;
}) {
  const updateChapter = (index: number, next: Partial<IdeationChapter>) => {
    onChange(chapters.map((chapter, chapterIndex) => (
      chapterIndex === index ? { ...chapter, ...next } : chapter
    )));
  };

  const addChapter = () => {
    onChange([
      ...chapters,
      {
        chapter_number: chapters.length + 1,
        title: "",
        purpose: "",
        key_points: [],
      },
    ]);
  };

  const removeChapter = (index: number) => {
    onChange(normalizeChapterDrafts(chapters.filter((_, chapterIndex) => chapterIndex !== index)));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {chapters.map((chapter, index) => (
        <div
          key={`chapter-editor-${index}`}
          style={{
            padding: "12px 14px",
            border: "0.5px solid var(--color-border-tertiary)",
            borderRadius: "var(--border-radius-md)",
            background: "#fff",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", marginBottom: 9 }}>
            <p style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>Chapter {index + 1}</p>
            {chapters.length > 1 && (
              <button
                type="button"
                className="btn-secondary"
                onClick={() => removeChapter(index)}
                style={{ padding: "4px 8px", fontSize: 11 }}
              >
                Remove
              </button>
            )}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <input
              className="input"
              value={chapter.title}
              onChange={(event) => updateChapter(index, { title: event.target.value })}
              placeholder="Chapter title"
              style={{ background: "#fff", fontFamily: "var(--font-sans)" }}
            />
            <textarea
              className="input"
              rows={3}
              value={chapter.purpose}
              onChange={(event) => updateChapter(index, { purpose: event.target.value })}
              placeholder="Purpose"
              style={{ resize: "vertical", background: "#fff", fontFamily: "var(--font-sans)" }}
            />
            <textarea
              className="input"
              rows={4}
              value={chapter.key_points.join("\n")}
              onChange={(event) => updateChapter(index, { key_points: event.target.value.split(/\r?\n/) })}
              placeholder="Key points, one per line"
              style={{ resize: "vertical", background: "#fff", fontFamily: "var(--font-sans)" }}
            />
          </div>
        </div>
      ))}
      <button
        type="button"
        className="btn-secondary"
        onClick={addChapter}
        style={{ alignSelf: "flex-start" }}
      >
        <Plus size={13} /> Add chapter
      </button>
    </div>
  );
}

function ResearchSignalsPanel({
  title,
  sources,
}: {
  title: string;
  sources: IdeationSourceLink[];
}) {
  const [expanded, setExpanded] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [exportNotice, setExportNotice] = useState<ExportNotice | null>(null);
  const signalSources = useMemo(() => uniqueSignalSources(sources), [sources]);
  const visibleSources = expanded ? signalSources : signalSources.slice(0, 3);

  useEffect(() => {
    if (!exportNotice) return;
    const timer = window.setTimeout(() => setExportNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [exportNotice]);

  const handleDownload = () => {
    if (signalSources.length === 0) return;
    setDownloading(true);
    try {
      const opened = downloadSourceListPdf(
        `${title} — Research Signals`,
        signalSources.map((source) => ({
          title: source.title,
          url: source.url,
          type: source.provider,
          preview: source.preview,
        }))
      );
      setExportNotice(
        opened
          ? { tone: "success", text: "Opened a print-ready link list in a new tab." }
          : { tone: "error", text: "Browser blocked the export window. Please allow pop-ups and try again." }
      );
    } finally {
      setDownloading(false);
    }
  };

  return (
    <section className="card" style={{ padding: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start", marginBottom: 10 }}>
        <div>
          <p className="section-label" style={{ marginBottom: 3 }}>Research signals</p>
          <p style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {signalSources.length} referenced {signalSources.length === 1 ? "link" : "links"}
          </p>
        </div>
        {signalSources.length > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <button
              type="button"
              className="btn-secondary"
              onClick={handleDownload}
              disabled={downloading}
              style={{ padding: "5px 9px", fontSize: 11 }}
            >
              {downloading ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
              Download all links
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setExpanded((value) => !value)}
              aria-expanded={expanded}
              style={{ padding: "5px 8px", fontSize: 11 }}
            >
              <ChevronDown
                size={12}
                style={{
                  transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
                  transition: "transform 0.12s ease",
                }}
              />
              {expanded ? "Collapse" : "Expand"}
            </button>
          </div>
        )}
      </div>

      {signalSources.length === 0 ? (
        <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
          Source links appear here when research is used to guide the direction.
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {visibleSources.map((source, index) => (
            <div
              key={`${source.url ?? source.title}-${index}`}
              style={{ borderBottom: index === visibleSources.length - 1 ? "none" : "0.5px solid var(--color-border-tertiary)", paddingBottom: 8 }}
            >
              <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", flexShrink: 0 }}>{index + 1}.</span>
                {source.url ? (
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ fontSize: 12, fontWeight: 500, lineHeight: 1.4, color: "var(--color-action)", textDecoration: "underline", overflowWrap: "anywhere" }}
                  >
                    {source.title}
                    <ExternalLink size={10} style={{ marginLeft: 4, verticalAlign: "-1px" }} />
                  </a>
                ) : (
                  <p style={{ fontSize: 12, fontWeight: 500, lineHeight: 1.4 }}>{source.title}</p>
                )}
              </div>
              <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 3 }}>{source.provider}</p>
              {source.preview && (
                <p style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 4, lineHeight: 1.45 }}>
                  {source.preview}
                </p>
              )}
            </div>
          ))}
          {!expanded && signalSources.length > visibleSources.length && (
            <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", lineHeight: 1.5 }}>
              {signalSources.length - visibleSources.length} more referenced links and snippets are available when expanded.
            </p>
          )}
        </div>
      )}

      {exportNotice && (
        <p
          style={{
            marginTop: 9,
            fontSize: 11,
            lineHeight: 1.5,
            color: exportNotice.tone === "success" ? "var(--color-success)" : "var(--color-danger)",
          }}
        >
          {exportNotice.text}
        </p>
      )}
    </section>
  );
}

export function IdeationWorkspace({ storyId, stage }: { storyId: string; stage: WorkspaceStage }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");
  const [selectedAngle, setSelectedAngle] = useState<string | null>(null);
  const [angleDraft, setAngleDraft] = useState("");
  const [angleEditMode, setAngleEditMode] = useState(false);
  const [selectedHook, setSelectedHook] = useState<string | null>(null);
  const [hookDraft, setHookDraft] = useState("");
  const [hookEditMode, setHookEditMode] = useState(false);
  const [chaptersDraft, setChaptersDraft] = useState<IdeationChapter[]>([]);
  const [chaptersEditMode, setChaptersEditMode] = useState(false);

  const { data: story, isLoading, error } = useQuery<Story>({
    queryKey: ["story", storyId],
    queryFn: () => apiClient.getStory(storyId),
    refetchInterval: (query) => {
      return query.state.data?.ideation_operation_data?.status === "running" ? 3000 : false;
    },
    refetchOnWindowFocus: true,
  });

  const persistedSelectedAngle = story?.selected_angle ?? null;
  const persistedStoryHook = story?.story_hook ?? null;
  const persistedChapters = useMemo(
    () => normalizeChapterDrafts(story?.chapters_data ?? []),
    [story?.chapters_data]
  );

  useEffect(() => {
    setSelectedAngle(persistedSelectedAngle);
    setAngleDraft(persistedSelectedAngle ?? "");
    setAngleEditMode(false);
  }, [story?.id, persistedSelectedAngle]);

  useEffect(() => {
    setSelectedHook(persistedStoryHook);
    setHookDraft(persistedStoryHook ?? "");
    setHookEditMode(false);
  }, [story?.id, persistedStoryHook]);

  useEffect(() => {
    setChaptersDraft(persistedChapters);
    setChaptersEditMode(false);
  }, [story?.id, persistedChapters]);

  const updateStory = (next: Story) => {
    queryClient.setQueryData(["story", storyId], next);
    queryClient.invalidateQueries({ queryKey: ["stories"] });
  };

  const chatMutation = useMutation({
    mutationFn: () => apiClient.ideationChat(storyId, message.trim()),
    onSuccess: ({ story: nextStory }) => {
      updateStory(nextStory);
      setMessage("");
    },
  });

  const generateAnglesMutation = useMutation({
    mutationFn: () => apiClient.generateIdeationAngles(storyId),
    onSuccess: ({ story: nextStory }) => {
      updateStory(nextStory);
      setSelectedAngle(null);
      setAngleDraft("");
      setAngleEditMode(false);
      router.push(stagePath(storyId, "angles"));
    },
  });

  const generateHooksMutation = useMutation({
    mutationFn: () => apiClient.generateIdeationHooks(storyId),
    onSuccess: ({ story: nextStory }) => {
      updateStory(nextStory);
      setHookEditMode(false);
      router.push(stagePath(storyId, "hook"));
    },
  });

  const approveAngleMutation = useMutation({
    mutationFn: () => apiClient.approveIdeationAngle(storyId, angleDraft.trim()),
    onSuccess: ({ story: nextStory }) => {
      updateStory(nextStory);
      router.push(stagePath(storyId, "hook"));
    },
  });

  const approveHookMutation = useMutation({
    mutationFn: () => apiClient.approveIdeationHook(storyId, hookDraft.trim()),
    onSuccess: ({ story: nextStory }) => {
      updateStory(nextStory);
      router.push(stagePath(storyId, "chapters"));
    },
  });

  const approveChaptersMutation = useMutation({
    mutationFn: () => apiClient.approveIdeationChapters(storyId, normalizeChapterDrafts(chaptersDraft)),
    onSuccess: (nextStory) => {
      updateStory(nextStory);
      setChaptersEditMode(false);
    },
  });

  const generateMutation = useMutation({
    mutationFn: () => apiClient.generateScriptFromIdeation(storyId),
    onSuccess: (nextStory) => {
      updateStory(nextStory);
      router.push(`/results/${storyId}`);
    },
  });

  const messages = useMemo(() => story?.ideation_chat_data ?? [], [story?.ideation_chat_data]);
  const sources = useMemo(() => story?.ideation_research_data ?? [], [story?.ideation_research_data]);
  const hookOptions = useMemo(() => story ? hookOptionsForStory(story) : [], [story]);

  if (isLoading) {
    return (
      <div style={{ minHeight: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Loader2 size={20} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
      </div>
    );
  }

  if (error || !story) {
    return (
      <div style={{ padding: 28 }}>
        <div className="card" style={{ padding: 24 }}>
          <p style={{ fontSize: 14, fontWeight: 500 }}>Could not load this ideation workspace.</p>
          <Link href="/" className="btn-secondary" style={{ marginTop: 12, textDecoration: "none" }}>Back to New Story</Link>
        </div>
      </div>
    );
  }

  const hookWords = countWords(hookDraft);
  const readyForScript = story.ideation_stage === "ready_for_script";
  const canGenerate = Boolean(story.selected_angle && story.story_hook && story.chapters_data?.length);
  const operation = story.ideation_operation_data ?? null;
  const operationRunning = operation?.status === "running";
  const chaptersDirty = !chapterDraftsEqual(chaptersDraft, persistedChapters);
  const chaptersValid = chaptersDraft.length > 0 && normalizeChapterDrafts(chaptersDraft).every((chapter) => chapter.title && chapter.purpose);
  const planDirty = chaptersEditMode || chaptersDirty;

  return (
    <div style={{ minHeight: "100%", background: "var(--color-background-tertiary)" }}>
      <div
        style={{
          minHeight: 52,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 14,
          padding: "10px 28px",
          background: "var(--color-background-primary)",
          borderBottom: "0.5px solid var(--color-border-tertiary)",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          <Link href="/" className="btn-ghost" style={{ textDecoration: "none" }} title="Start a new story">
            <ArrowLeft size={14} />
          </Link>
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: 16, fontWeight: 500, margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {story.title}
            </p>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginTop: 3 }}>
              <span className={`badge ${storyStatusBadgeClass(story.status)}`}>{storyStatusLabel(story.status)}</span>
              <span className={`badge tone-${story.tone}`} style={{ border: "none" }}>{story.tone}</span>
              <span className="badge badge-neutral">{story.target_duration_minutes} min</span>
            </div>
          </div>
        </div>
        <nav style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <Link href="/" className="btn-secondary" style={{ textDecoration: "none" }}>New Story</Link>
          {STAGE_LINKS.map((item) => (
            <Link
              key={item.stage}
              href={stagePath(story.id, item.stage)}
              className={item.stage === stage ? "btn-primary" : "btn-secondary"}
              style={{ textDecoration: "none" }}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>

      <div style={{ padding: 28, display: "flex", gap: 18, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 520px", minWidth: 0 }}>
          {operation && (
            <div style={{ marginBottom: 12 }}>
              <OperationNotice operation={operation} />
            </div>
          )}
          {stage === "angles" && (
            <ArtifactShell title="Choose the story angle" kicker="Stage 1">
              <p style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 14, lineHeight: 1.5 }}>
                Select the framing you want to carry forward. You can return here later, generate more options, edit the selected angle, and restart hook generation.
              </p>
              <button
                type="button"
                className="btn-secondary"
                disabled={generateAnglesMutation.isPending || operationRunning || approveAngleMutation.isPending}
                onClick={() => generateAnglesMutation.mutate()}
                style={{ marginBottom: 12 }}
              >
                {generateAnglesMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
                Generate more angles
              </button>
              <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                {(story.angles_data ?? []).length === 0 && operationRunning ? (
                  <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
                    Angles are being generated. You can leave this page and come back; the draft will keep updating here.
                  </p>
                ) : (story.angles_data ?? []).map((angle) => (
                  <AngleCard
                    key={angle.angle}
                    angle={angle}
                    selected={selectedAngle === angle.angle || angleDraft === angle.angle}
                    onSelect={() => {
                      setSelectedAngle(angle.angle);
                      setAngleDraft(angle.angle);
                      setAngleEditMode(false);
                    }}
                  />
                ))}
              </div>
              {angleDraft && (
                <div
                  style={{
                    marginTop: 14,
                    padding: "12px 14px",
                    border: "0.5px solid var(--color-border-tertiary)",
                    borderRadius: "var(--border-radius-md)",
                    background: "var(--color-background-secondary)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", marginBottom: angleEditMode ? 8 : 0 }}>
                    <p style={{ fontSize: 12, fontWeight: 500 }}>Selected angle</p>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setAngleEditMode((value) => !value)}
                      disabled={operationRunning || approveAngleMutation.isPending}
                      style={{ padding: "5px 9px", fontSize: 11 }}
                    >
                      <Edit3 size={12} /> {angleEditMode ? "Done editing" : "Edit"}
                    </button>
                  </div>
                  {angleEditMode ? (
                    <textarea
                      className="input"
                      rows={4}
                      value={angleDraft}
                      onChange={(event) => setAngleDraft(event.target.value)}
                      style={{ resize: "vertical", background: "#fff", fontFamily: "var(--font-sans)" }}
                      disabled={operationRunning}
                    />
                  ) : (
                    <p style={{ fontSize: 13, color: "var(--color-text-primary)", lineHeight: 1.55 }}>{angleDraft}</p>
                  )}
                </div>
              )}
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
                <button
                  type="button"
                  className="btn-primary"
                  disabled={!angleDraft.trim() || approveAngleMutation.isPending || operationRunning}
                  onClick={() => approveAngleMutation.mutate()}
                >
                  {approveAngleMutation.isPending && <Loader2 size={13} className="animate-spin" />}
                  Approve angle
                  <ChevronRight size={13} />
                </button>
              </div>
            </ArtifactShell>
          )}

          {stage === "hook" && (
            <ArtifactShell title="Shape the story hook" kicker="Stage 2">
              <p style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 12, lineHeight: 1.5 }}>
                Choose one hook example, edit it if needed, then approve it to regenerate the chapter outline.
              </p>
              {story.selected_angle && (
                <div className="stat-callout" style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                  <span><strong>Selected angle:</strong> {story.selected_angle}</span>
                  <Link href={stagePath(storyId, "angles")} className="btn-secondary" style={{ textDecoration: "none", padding: "5px 9px", fontSize: 11 }}>
                    Reselect
                  </Link>
                </div>
              )}
              <button
                type="button"
                className="btn-secondary"
                disabled={!story.selected_angle || generateHooksMutation.isPending || operationRunning || approveHookMutation.isPending}
                onClick={() => generateHooksMutation.mutate()}
                style={{ marginBottom: 12 }}
              >
                {generateHooksMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
                Generate more hooks
              </button>
              <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                {hookOptions.length === 0 && operationRunning ? (
                  <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
                    Hook examples are being generated. You can leave this page and come back to choose one.
                  </p>
                ) : hookOptions.length === 0 ? (
                  <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
                    No hook examples yet. Generate hooks after selecting an angle.
                  </p>
                ) : hookOptions.map((hook, index) => (
                  <HookCard
                    key={`${hook}-${index}`}
                    hook={hook}
                    selected={selectedHook === hook || hookDraft === hook}
                    onSelect={() => {
                      setSelectedHook(hook);
                      setHookDraft(hook);
                      setHookEditMode(false);
                    }}
                  />
                ))}
              </div>
              {hookDraft && (
                <div
                  style={{
                    marginTop: 14,
                    padding: "12px 14px",
                    border: "0.5px solid var(--color-border-tertiary)",
                    borderRadius: "var(--border-radius-md)",
                    background: "var(--color-background-secondary)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", marginBottom: hookEditMode ? 8 : 0 }}>
                    <div>
                      <p style={{ fontSize: 12, fontWeight: 500 }}>Selected hook</p>
                      <p style={{ fontSize: 11, color: hookWords > 100 ? "var(--color-danger)" : "var(--color-text-tertiary)", marginTop: 3 }}>
                        {hookWords}/100 words
                      </p>
                    </div>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setHookEditMode((value) => !value)}
                      disabled={operationRunning || approveHookMutation.isPending}
                      style={{ padding: "5px 9px", fontSize: 11 }}
                    >
                      <Edit3 size={12} /> {hookEditMode ? "Done editing" : "Edit"}
                    </button>
                  </div>
                  {hookEditMode ? (
                    <textarea
                      className="input"
                      rows={7}
                      value={hookDraft}
                      onChange={(event) => setHookDraft(event.target.value)}
                      style={{ resize: "vertical", background: "#fff", fontFamily: "var(--font-sans)" }}
                      disabled={operationRunning}
                    />
                  ) : (
                    <p style={{ fontSize: 13, color: "var(--color-text-primary)", lineHeight: 1.55 }}>{hookDraft}</p>
                  )}
                </div>
              )}
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
                <button
                  type="button"
                  className="btn-primary"
                  disabled={!hookDraft.trim() || hookWords > 100 || approveHookMutation.isPending || operationRunning}
                  onClick={() => approveHookMutation.mutate()}
                >
                  {approveHookMutation.isPending && <Loader2 size={13} className="animate-spin" />}
                  Approve hook
                  <ChevronRight size={13} />
                </button>
              </div>
            </ArtifactShell>
          )}

          {stage === "chapters" && (
            <ArtifactShell title="Build the chapter structure" kicker="Stage 3">
              <p style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 14, lineHeight: 1.5 }}>
                Edit the outline before approving. If you change the angle or hook later, this outline will be regenerated from that new choice.
              </p>
              {story.story_hook && (
                <div className="stat-callout" style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                  <span><strong>Selected hook:</strong> {story.story_hook}</span>
                  <Link href={stagePath(storyId, "hook")} className="btn-secondary" style={{ textDecoration: "none", padding: "5px 9px", fontSize: 11 }}>
                    Reselect
                  </Link>
                </div>
              )}
              {chaptersDraft.length === 0 && operationRunning ? (
                <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
                  The chapter outline is being drafted. You can leave this page and come back to the result.
                </p>
              ) : chaptersEditMode ? (
                <ChapterEditor chapters={chaptersDraft} onChange={setChaptersDraft} />
              ) : (
                <ChapterList chapters={chaptersDraft} />
              )}
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={!chaptersDraft.length || operationRunning || approveChaptersMutation.isPending}
                  onClick={() => setChaptersEditMode((value) => !value)}
                >
                  <Edit3 size={13} /> {chaptersEditMode ? "Preview" : "Edit"}
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={!chaptersValid || approveChaptersMutation.isPending || operationRunning}
                  onClick={() => approveChaptersMutation.mutate()}
                >
                  {approveChaptersMutation.isPending && <Loader2 size={13} className="animate-spin" />}
                  {readyForScript && !chaptersDirty ? "Reapprove chapters" : "Approve chapters"}
                </button>
                <button
                  type="button"
                  className="btn-primary"
                  disabled={!canGenerate || !readyForScript || planDirty || generateMutation.isPending || operationRunning}
                  onClick={() => generateMutation.mutate()}
                >
                  {generateMutation.isPending && <Loader2 size={13} className="animate-spin" />}
                  Generate script
                  <Sparkles size={13} />
                </button>
              </div>
              {planDirty && (
                <p style={{ marginTop: 9, fontSize: 11, color: "var(--color-text-tertiary)", lineHeight: 1.5 }}>
                  Save the edited chapter outline before generating the script.
                </p>
              )}
            </ArtifactShell>
          )}
        </div>

        <aside style={{ flex: "0 1 360px", minWidth: 320, display: "flex", flexDirection: "column", gap: 12 }}>
          <section className="card" style={{ padding: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <MessageSquareText size={15} style={{ color: "var(--color-action)" }} />
              <p style={{ fontSize: 14, fontWeight: 500 }}>Editorial chat</p>
            </div>
            <div style={{ maxHeight: 390, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8, paddingRight: 4 }}>
              {messages.length === 0 ? (
                <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                  Ask for more angles, a sharper hook, reordered chapters, or a specific research datapoint.
                </p>
              ) : (
                messages.map((item, index) => (
                  <div
                    key={`${item.role}-${index}`}
                    style={{
                      padding: "9px 10px",
                      borderRadius: "var(--border-radius-md)",
                      background: item.role === "user" ? "var(--color-background-secondary)" : "#fff",
                      border: "0.5px solid var(--color-border-tertiary)",
                    }}
                  >
                    <p style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-tertiary)", marginBottom: 3 }}>
                      {item.role === "user" ? "You" : "Assistant"}
                      {item.status === "running" ? " · running" : item.status === "failed" ? " · failed" : ""}
                    </p>
                    <p style={{ fontSize: 12, color: "var(--color-text-primary)", whiteSpace: "pre-wrap", lineHeight: 1.5 }}>
                      {item.content}
                    </p>
                    {item.error_message && (
                      <p style={{ fontSize: 11, color: "var(--color-danger)", marginTop: 4 }}>
                        {item.error_message}
                      </p>
                    )}
                  </div>
                ))
              )}
            </div>

            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (message.trim()) chatMutation.mutate();
              }}
              style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "flex-end" }}
            >
              <textarea
                className="input"
                rows={3}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="Ask for refinements, more ideas, or research..."
                disabled={chatMutation.isPending || operationRunning}
                style={{ resize: "vertical", fontFamily: "var(--font-sans)" }}
              />
              <button type="submit" className="btn-primary" disabled={!message.trim() || chatMutation.isPending || operationRunning} title="Send">
                {chatMutation.isPending || operationRunning ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              </button>
            </form>
          </section>

          <ResearchSignalsPanel title={story.title} sources={sources} />

          {readyForScript && (
            <div className="card" style={{ padding: 14, display: "flex", gap: 8, alignItems: "flex-start" }}>
              <CheckCircle2 size={15} style={{ color: "var(--color-success)", marginTop: 2, flexShrink: 0 }} />
              <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                The ideation plan is approved. The script will start only when you click Generate script.
              </p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

export type { WorkspaceStage };

"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  Download,
  Edit3,
  ExternalLink,
  FileText,
  Loader2,
  Plus,
  Save,
  Send,
  Sparkles,
} from "lucide-react";
import {
  apiClient,
  type FinalScript,
  type IdeationOperationData,
  type IdeationChapter,
  type IdeationSourceLink,
  type ScriptSection,
  type Story,
  type StoryAngle,
} from "@/lib/api";
import { downloadScriptPdf, downloadSourceListPdf } from "@/lib/script-export";
import { isTerminalStoryStatus, storyStatusBadgeClass, storyStatusLabel } from "@/lib/story-status";

type WorkspaceStage = "angles" | "hook" | "chapters" | "script";

const STAGE_LINKS: Array<{ stage: WorkspaceStage; label: string }> = [
  { stage: "angles", label: "Angles" },
  { stage: "hook", label: "Story Hook" },
  { stage: "chapters", label: "Chapters" },
  { stage: "script", label: "Script" },
];

type ExportNotice = {
  tone: "success" | "error";
  text: string;
};

const EDIT_BUTTON_STYLE: CSSProperties = {
  background: "#dcfce7",
  borderColor: "#86efac",
  color: "#166534",
};

const SCRIPT_READ_ONLY_STYLE: CSSProperties = {
  border: "0.5px solid var(--color-border-tertiary)",
  borderRadius: "var(--border-radius-md)",
  background: "#fff",
  padding: "10px 12px",
  fontSize: 13,
  lineHeight: 1.6,
  whiteSpace: "pre-wrap",
  color: "var(--color-text-primary)",
};

function stagePath(storyId: string, stage: WorkspaceStage): string {
  return `/ideation/${storyId}/${stage}`;
}

function countWords(value: string): number {
  const trimmed = value.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

function safeDownloadName(value: string, suffix: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return `${slug || "story"}-${suffix}.txt`;
}

function downloadTextFile(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function formatChapterText(chapters: IdeationChapter[]): string {
  return normalizeChapterDrafts(chapters)
    .map((chapter) => {
      const details = chapter.key_points.length
        ? `\nDetails:\n${chapter.key_points.map((point) => `- ${point}`).join("\n")}`
        : "";
      return `Chapter ${chapter.chapter_number}: ${chapter.title}\n\n${chapter.purpose}${details}`;
    })
    .join("\n\n---\n\n");
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
  disabled = false,
}: {
  angle: StoryAngle;
  selected: boolean;
  onSelect: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      style={{
        textAlign: "left",
        padding: "13px 14px",
        border: `1px solid ${selected ? "var(--color-action)" : "var(--color-border-tertiary)"}`,
        borderRadius: "var(--border-radius-md)",
        background: disabled ? "var(--color-background-secondary)" : selected ? "rgba(28, 38, 168, 0.04)" : "#fff",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.72 : 1,
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
  disabled = false,
}: {
  hook: string;
  selected: boolean;
  onSelect: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      style={{
        textAlign: "left",
        padding: "12px 14px",
        border: `1px solid ${selected ? "var(--color-action)" : "var(--color-border-tertiary)"}`,
        borderRadius: "var(--border-radius-md)",
        background: disabled ? "var(--color-background-secondary)" : selected ? "rgba(28, 38, 168, 0.04)" : "#fff",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.72 : 1,
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
            <button
              type="button"
              className="btn-secondary"
              onClick={() => removeChapter(index)}
              style={{ padding: "4px 8px", fontSize: 11 }}
            >
              Delete
            </button>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <input
              className="input"
              value={chapter.title}
              onChange={(event) => updateChapter(index, { title: event.target.value })}
              placeholder="Chapter headline"
              style={{ background: "#fff", fontFamily: "var(--font-sans)" }}
            />
            <textarea
              className="input"
              rows={3}
              value={chapter.purpose}
              onChange={(event) => updateChapter(index, { purpose: event.target.value })}
              placeholder="Chapter body"
              style={{ resize: "vertical", background: "#fff", fontFamily: "var(--font-sans)" }}
            />
            <textarea
              className="input"
              rows={4}
              value={chapter.key_points.join("\n")}
              onChange={(event) => updateChapter(index, { key_points: event.target.value.split(/\r?\n/) })}
              placeholder="Additional details, one per line"
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

const CLIENT_WORDS_PER_MINUTE = 148;

function cloneScriptDraft(script: FinalScript): FinalScript {
  return {
    ...script,
    sections: script.sections.map((section) => ({
      ...section,
      source_ids: [...(section.source_ids ?? [])],
    })),
    sources: script.sources.map((source) => ({ ...source })),
    metadata: { ...script.metadata },
  };
}

function scriptTextWordCount(value: string): number {
  const trimmed = value.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

function normaliseScriptDraft(script: FinalScript): FinalScript {
  const sections = script.sections.map((section, index) => {
    const sectionWords = scriptTextWordCount(section.narration);
    return {
      ...section,
      section_number: index + 1,
      estimated_seconds: sectionWords ? Math.round((sectionWords / CLIENT_WORDS_PER_MINUTE) * 60) : 0,
      source_ids: section.source_ids ?? [],
    };
  });
  const totalWords = (
    scriptTextWordCount(script.logline)
    + scriptTextWordCount(script.opening_hook)
    + sections.reduce((sum, section) => sum + scriptTextWordCount(section.narration), 0)
    + scriptTextWordCount(script.closing_statement)
  );
  return {
    ...script,
    title: script.title.trim(),
    sections,
    total_word_count: totalWords,
    estimated_duration_minutes: totalWords ? Math.round((totalWords / CLIENT_WORDS_PER_MINUTE) * 10) / 10 : 0,
  };
}

function scriptsEqual(left: FinalScript, right: FinalScript): boolean {
  return JSON.stringify(normaliseScriptDraft(left)) === JSON.stringify(normaliseScriptDraft(right));
}

function EditableScriptStep({
  script,
  onSave,
  isSaving,
  saveError,
}: {
  script: FinalScript;
  onSave: (script: FinalScript) => void;
  isSaving: boolean;
  saveError: string | null;
}) {
  const [draft, setDraft] = useState<FinalScript>(() => cloneScriptDraft(script));
  const [editMode, setEditMode] = useState(false);

  useEffect(() => {
    setDraft(cloneScriptDraft(script));
    setEditMode(false);
  }, [script]);

  const normalisedDraft = useMemo(() => normaliseScriptDraft(draft), [draft]);
  const dirty = !scriptsEqual(draft, script);

  const updateSection = (index: number, next: Partial<ScriptSection>) => {
    setDraft((current) => ({
      ...current,
      sections: current.sections.map((section, sectionIndex) => (
        sectionIndex === index ? { ...section, ...next } : section
      )),
    }));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div
        className="stat-callout"
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}
      >
        <span>
          {normalisedDraft.total_word_count.toLocaleString()} words · ~{normalisedDraft.estimated_duration_minutes} min
          {dirty ? " · unsaved edits" : " · saved"}{editMode ? " · editing" : ""}
        </span>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setEditMode(true)}
            disabled={editMode || isSaving}
            style={{ ...EDIT_BUTTON_STYLE, flexShrink: 0 }}
          >
            <Edit3 size={13} />
            Edit
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => downloadScriptPdf(normalisedDraft)}
            disabled={editMode || isSaving}
            style={{ flexShrink: 0 }}
          >
            <Download size={13} />
            Download Script
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => {
              if (dirty) {
                onSave(normalisedDraft);
              } else {
                setEditMode(false);
              }
            }}
            disabled={isSaving || (!editMode && !dirty)}
            style={{ flexShrink: 0 }}
          >
            {isSaving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
            Save script
          </button>
        </div>
      </div>

      {saveError && (
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
          {saveError}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <label style={{ fontSize: 12, fontWeight: 500 }}>Script title</label>
        {editMode ? (
          <input
            className="input"
            value={draft.title}
            onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
            disabled={isSaving}
            style={{ background: "#fff", fontFamily: "var(--font-sans)" }}
          />
        ) : (
          <p style={SCRIPT_READ_ONLY_STYLE}>{draft.title}</p>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <label style={{ fontSize: 12, fontWeight: 500 }}>Logline</label>
        {editMode ? (
          <textarea
            className="input"
            rows={3}
            value={draft.logline}
            onChange={(event) => setDraft((current) => ({ ...current, logline: event.target.value }))}
            disabled={isSaving}
            style={{ resize: "vertical", background: "#fff", fontFamily: "var(--font-sans)" }}
          />
        ) : (
          <p style={SCRIPT_READ_ONLY_STYLE}>{draft.logline}</p>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <label style={{ fontSize: 12, fontWeight: 500 }}>Opening hook</label>
        {editMode ? (
          <textarea
            className="input"
            rows={5}
            value={draft.opening_hook}
            onChange={(event) => setDraft((current) => ({ ...current, opening_hook: event.target.value }))}
            disabled={isSaving}
            style={{ resize: "vertical", background: "#fff", fontFamily: "var(--font-sans)" }}
          />
        ) : (
          <p style={SCRIPT_READ_ONLY_STYLE}>{draft.opening_hook}</p>
        )}
      </div>

      {draft.sections.map((section, index) => (
        <div
          key={`script-section-${index}`}
          style={{
            padding: "12px 14px",
            border: "0.5px solid var(--color-border-tertiary)",
            borderRadius: "var(--border-radius-md)",
            background: "#fff",
          }}
        >
          <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginBottom: 8 }}>
            Section {index + 1} · {scriptTextWordCount(section.narration).toLocaleString()} words
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {editMode ? (
              <>
                <input
                  className="input"
                  value={section.title}
                  onChange={(event) => updateSection(index, { title: event.target.value })}
                  placeholder="Section headline"
                  disabled={isSaving}
                  style={{ background: "#fff", fontFamily: "var(--font-sans)" }}
                />
                <textarea
                  className="input"
                  rows={12}
                  value={section.narration}
                  onChange={(event) => updateSection(index, { narration: event.target.value })}
                  placeholder="Write, revise, or delete script text here..."
                  disabled={isSaving}
                  style={{ resize: "vertical", background: "#fff", fontFamily: "var(--font-sans)", lineHeight: 1.6 }}
                />
              </>
            ) : (
              <>
                <p style={{ fontSize: 15, fontWeight: 500, color: "var(--color-text-primary)" }}>{section.title}</p>
                <p style={SCRIPT_READ_ONLY_STYLE}>{section.narration}</p>
              </>
            )}
          </div>
        </div>
      ))}

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <label style={{ fontSize: 12, fontWeight: 500 }}>Closing statement</label>
        {editMode ? (
          <textarea
            className="input"
            rows={6}
            value={draft.closing_statement}
            onChange={(event) => setDraft((current) => ({ ...current, closing_statement: event.target.value }))}
            disabled={isSaving}
            style={{ resize: "vertical", background: "#fff", fontFamily: "var(--font-sans)" }}
          />
        ) : (
          <p style={SCRIPT_READ_ONLY_STYLE}>{draft.closing_statement}</p>
        )}
      </div>
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
  const [scriptSaveError, setScriptSaveError] = useState<string | null>(null);

  const { data: story, isLoading, error } = useQuery<Story>({
    queryKey: ["story", storyId],
    queryFn: () => apiClient.getStory(storyId),
    refetchInterval: (query) => {
      const current = query.state.data;
      if (current?.ideation_operation_data?.status === "running") return 3000;
      if (stage === "script" && current && !isTerminalStoryStatus(current.status)) return 3000;
      return false;
    },
    refetchOnWindowFocus: true,
  });

  const {
    data: script,
    isLoading: scriptLoading,
    error: scriptError,
  } = useQuery<FinalScript>({
    queryKey: ["script", storyId],
    queryFn: () => apiClient.getScript(storyId),
    enabled: stage === "script" && story?.status === "completed",
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
    mutationFn: () => apiClient.ideationChat(
      storyId,
      message.trim(),
      {
        stage,
        ...(stage === "angles" ? {
          angles: story?.angles_data ?? [],
          selected_angle: angleDraft.trim() || undefined,
        } : {}),
        ...(stage === "hook" ? {
          selected_angle: story?.selected_angle ?? undefined,
          story_hook: hookDraft.trim() || undefined,
        } : {}),
        ...(stage === "chapters" ? {
          story_hook: story?.story_hook ?? undefined,
          chapters: normalizeChapterDrafts(chaptersDraft),
        } : {}),
      }
    ),
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
      queryClient.invalidateQueries({ queryKey: ["script", storyId] });
      router.push(stagePath(storyId, "script"));
    },
  });

  const saveScriptMutation = useMutation({
    mutationFn: (nextScript: FinalScript) => apiClient.updateScript(storyId, nextScript),
    onMutate: () => {
      setScriptSaveError(null);
    },
    onSuccess: (nextScript) => {
      queryClient.setQueryData(["script", storyId], nextScript);
      queryClient.invalidateQueries({ queryKey: ["story", storyId] });
      queryClient.invalidateQueries({ queryKey: ["stories"] });
      setScriptSaveError(null);
    },
    onError: (saveError) => {
      setScriptSaveError(saveError instanceof Error ? saveError.message : "Could not save script changes.");
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
  const scriptGenerationOperation = operation?.type === "script_generation";
  const scriptGenerationRunning = operationRunning && scriptGenerationOperation;
  const angleDirty = angleDraft.trim() !== (persistedSelectedAngle ?? "").trim();
  const hookDirty = hookDraft.trim() !== (persistedStoryHook ?? "").trim();
  const chaptersDirty = !chapterDraftsEqual(chaptersDraft, persistedChapters);
  const chaptersValid = chaptersDraft.length > 0 && normalizeChapterDrafts(chaptersDraft).every((chapter) => chapter.title && chapter.purpose);
  const planDirty = chaptersEditMode || chaptersDirty;
  const handleSaveAngle = () => {
    if (persistedSelectedAngle && !angleDirty) {
      setAngleEditMode(false);
      return;
    }
    approveAngleMutation.mutate();
  };
  const handleSaveHook = () => {
    if (persistedStoryHook && !hookDirty) {
      setHookEditMode(false);
      return;
    }
    approveHookMutation.mutate();
  };
  const handleSaveChapters = () => {
    if (readyForScript && !chaptersDirty) {
      setChaptersEditMode(false);
      return;
    }
    approveChaptersMutation.mutate();
  };

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
          {operation && (!scriptGenerationOperation || stage === "script") && (
            <div style={{ marginBottom: 12 }}>
              <OperationNotice operation={operation} />
            </div>
          )}
          {stage === "angles" && (
            <ArtifactShell title="Choose the story angle" kicker="Stage 1">
              <p style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 14, lineHeight: 1.5 }}>
                Select the framing you want to carry forward. You can return here later, generate more options, edit the selected angle, and restart hook generation.
              </p>
              <div
                className="stat-callout"
                style={{ marginBottom: 12, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}
              >
                <span>{angleDraft ? "Selected angle is ready to edit, download, or save." : "Choose an angle to unlock edit, download, and save."}</span>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => setAngleEditMode(true)}
                    disabled={angleEditMode || !angleDraft.trim() || operationRunning || approveAngleMutation.isPending}
                    style={{ ...EDIT_BUTTON_STYLE, flexShrink: 0 }}
                  >
                    <Edit3 size={13} />
                    Edit
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => downloadTextFile(
                      safeDownloadName(story.title, "angle"),
                      `${story.title}\n\nANGLE\n${angleDraft.trim()}`
                    )}
                    disabled={angleEditMode || !angleDraft.trim()}
                    style={{ flexShrink: 0 }}
                  >
                    <Download size={13} />
                    Download
                  </button>
                  <button
                    type="button"
                    className="btn-primary"
                    disabled={!angleDraft.trim() || approveAngleMutation.isPending || operationRunning}
                    onClick={handleSaveAngle}
                    style={{ flexShrink: 0 }}
                  >
                    {approveAngleMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                    Save
                  </button>
                </div>
              </div>
              <button
                type="button"
                className="btn-secondary"
                disabled={angleEditMode || generateAnglesMutation.isPending || operationRunning || approveAngleMutation.isPending}
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
                ) : (story.angles_data ?? []).length === 0 ? (
                  <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
                    No angle options are ready yet.
                  </p>
                ) : (story.angles_data ?? []).map((angle) => (
                  <AngleCard
                    key={angle.angle}
                    angle={angle}
                    selected={selectedAngle === angle.angle || angleDraft === angle.angle}
                    disabled={angleEditMode}
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
                  <Link
                    href={stagePath(storyId, "angles")}
                    className="btn-secondary"
                    style={{
                      textDecoration: "none",
                      padding: "5px 9px",
                      fontSize: 11,
                      pointerEvents: hookEditMode ? "none" : "auto",
                      opacity: hookEditMode ? 0.55 : 1,
                    }}
                    aria-disabled={hookEditMode}
                  >
                    Reselect
                  </Link>
                </div>
              )}
              <div
                className="stat-callout"
                style={{ marginBottom: 12, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}
              >
                <span>{hookDraft ? `${hookWords}/100 words` : "Choose a hook to unlock edit, download, and save."}</span>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => setHookEditMode(true)}
                    disabled={hookEditMode || !hookDraft.trim() || operationRunning || approveHookMutation.isPending}
                    style={{ ...EDIT_BUTTON_STYLE, flexShrink: 0 }}
                  >
                    <Edit3 size={13} />
                    Edit
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => downloadTextFile(
                      safeDownloadName(story.title, "hook"),
                      `${story.title}\n\nHOOK\n${hookDraft.trim()}`
                    )}
                    disabled={hookEditMode || !hookDraft.trim()}
                    style={{ flexShrink: 0 }}
                  >
                    <Download size={13} />
                    Download
                  </button>
                  <button
                    type="button"
                    className="btn-primary"
                    disabled={!hookDraft.trim() || hookWords > 100 || approveHookMutation.isPending || operationRunning}
                    onClick={handleSaveHook}
                    style={{ flexShrink: 0 }}
                  >
                    {approveHookMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                    Save
                  </button>
                </div>
              </div>
              <button
                type="button"
                className="btn-secondary"
                disabled={hookEditMode || !story.selected_angle || generateHooksMutation.isPending || operationRunning || approveHookMutation.isPending}
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
                    disabled={hookEditMode}
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
                  <Link
                    href={stagePath(storyId, "hook")}
                    className="btn-secondary"
                    style={{
                      textDecoration: "none",
                      padding: "5px 9px",
                      fontSize: 11,
                      pointerEvents: chaptersEditMode ? "none" : "auto",
                      opacity: chaptersEditMode ? 0.55 : 1,
                    }}
                    aria-disabled={chaptersEditMode}
                  >
                    Reselect
                  </Link>
                </div>
              )}
              <div
                className="stat-callout"
                style={{ marginBottom: 12, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}
              >
                <span>{chaptersDraft.length ? `${chaptersDraft.length} chapter${chaptersDraft.length === 1 ? "" : "s"} in the outline` : "Add chapters to unlock download and save."}</span>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <button
                    type="button"
                    className="btn-secondary"
                    disabled={chaptersEditMode || operationRunning || approveChaptersMutation.isPending}
                    onClick={() => setChaptersEditMode(true)}
                    style={{ ...EDIT_BUTTON_STYLE, flexShrink: 0 }}
                  >
                    <Edit3 size={13} />
                    Edit
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => downloadTextFile(
                      safeDownloadName(story.title, "chapters"),
                      `${story.title}\n\nCHAPTER OUTLINE\n\n${formatChapterText(chaptersDraft)}`
                    )}
                    disabled={chaptersEditMode || !chaptersDraft.length}
                    style={{ flexShrink: 0 }}
                  >
                    <Download size={13} />
                    Download
                  </button>
                  <button
                    type="button"
                    className="btn-primary"
                    disabled={!chaptersValid || approveChaptersMutation.isPending || operationRunning}
                    onClick={handleSaveChapters}
                    style={{ flexShrink: 0 }}
                  >
                    {approveChaptersMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                    Save
                  </button>
                </div>
              </div>
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

          {stage === "script" && (
            <ArtifactShell title="Edit the final script" kicker="Stage 4">
              {story.status !== "completed" ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {scriptGenerationRunning ? (
                    <div className="stat-callout" style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                      <Loader2 size={14} className="animate-spin" style={{ color: "var(--color-action)", marginTop: 2, flexShrink: 0 }} />
                      <span>
                        The script is being generated from your approved angle, hook, and chapters. You can visit the earlier tabs while this continues.
                      </span>
                    </div>
                  ) : story.status !== "ideating" ? (
                    <div className="stat-callout" style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                      <Loader2 size={14} className="animate-spin" style={{ color: "var(--color-action)", marginTop: 2, flexShrink: 0 }} />
                      <span>
                        The script is being generated. This page will refresh when the draft is ready for editing.
                      </span>
                    </div>
                  ) : readyForScript ? (
                    <>
                      <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                        Your angle, hook, and chapters are approved. Generate the script, then edit and save the final text here.
                      </p>
                      <button
                        type="button"
                        className="btn-primary"
                        disabled={!canGenerate || planDirty || generateMutation.isPending || operationRunning}
                        onClick={() => generateMutation.mutate()}
                        style={{ alignSelf: "flex-start" }}
                      >
                        {generateMutation.isPending && <Loader2 size={13} className="animate-spin" />}
                        Generate script
                        <Sparkles size={13} />
                      </button>
                    </>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                        Approve the angle, hook, and chapters before generating the script.
                      </p>
                      <Link href={stagePath(storyId, "chapters")} className="btn-secondary" style={{ textDecoration: "none", alignSelf: "flex-start" }}>
                        Back to chapters
                      </Link>
                    </div>
                  )}
                </div>
              ) : scriptLoading ? (
                <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--color-text-secondary)", fontSize: 13 }}>
                  <Loader2 size={14} className="animate-spin" />
                  Loading script editor...
                </div>
              ) : scriptError || !script ? (
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
                  Could not load the script editor.
                </div>
              ) : (
                <EditableScriptStep
                  script={script}
                  onSave={(nextScript) => saveScriptMutation.mutate(nextScript)}
                  isSaving={saveScriptMutation.isPending}
                  saveError={scriptSaveError}
                />
              )}
            </ArtifactShell>
          )}
        </div>

        <aside style={{ flex: "0 1 360px", minWidth: 320, display: "flex", flexDirection: "column", gap: 12 }}>
          {stage === "script" ? (
            <section className="card" style={{ padding: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <FileText size={15} style={{ color: "var(--color-action)" }} />
                <p style={{ fontSize: 14, fontWeight: 500 }}>Script editing</p>
              </div>
              <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                Changes in the script editor stay local until you click Save script.
              </p>
            </section>
          ) : (
            <section className="card" style={{ padding: 16 }}>
              <div style={{ maxHeight: 390, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8, paddingRight: 4 }}>
                {messages.length === 0 ? (
                  <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                    use this chat so I can help you improve the story
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
                  disabled={chatMutation.isPending || operationRunning}
                  style={{ resize: "vertical", fontFamily: "var(--font-sans)" }}
                />
                <button type="submit" className="btn-primary" disabled={!message.trim() || chatMutation.isPending || operationRunning} title="Send">
                  {chatMutation.isPending || operationRunning ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                </button>
              </form>
            </section>
          )}

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

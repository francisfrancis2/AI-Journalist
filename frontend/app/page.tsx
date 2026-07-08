"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, MessageSquareText, ChevronRight, AlertTriangle, FileText, Paperclip, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import { apiClient, type Story } from "@/lib/api";
import { getUserInfo } from "@/lib/auth";
import { storyStatusBadgeClass, storyStatusLabel } from "@/lib/story-status";

const PROMPT_MAX_WORDS = 200;
const MAX_ATTACHMENTS = 5;
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;
const ATTACHMENT_ACCEPT = ".pdf,.docx,.jpg,.jpeg,.xls,.xlsx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,image/jpeg";
const ATTACHMENT_EXTENSIONS = new Set(["pdf", "docx", "jpg", "jpeg", "xls", "xlsx"]);

function countWords(value: string): number {
  const trimmed = value.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function isAllowedAttachment(file: File): boolean {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return ATTACHMENT_EXTENSIONS.has(extension);
}

function storyWorkspaceHref(story: Story): string {
  const scriptGenerationRunning = story.ideation_operation_data?.type === "script_generation"
    && story.ideation_operation_data.status === "running";
  if (story.status === "completed") return `/ideation/${story.id}/script`;
  if (scriptGenerationRunning) return `/ideation/${story.id}/script`;
  if (story.status !== "ideating") return `/results/${story.id}`;
  if (story.ideation_stage === "hook") return `/ideation/${story.id}/hook`;
  if (story.ideation_stage === "chapters" || story.ideation_stage === "ready_for_script") {
    return `/ideation/${story.id}/chapters`;
  }
  return `/ideation/${story.id}/angles`;
}

export default function NewStoryPage() {
  const router = useRouter();
  const currentUser = getUserInfo();
  const isAdmin = currentUser?.is_admin ?? false;
  const [prompt, setPrompt] = useState("");
  const [attachments, setAttachments] = useState<File[]>([]);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const { data: stories } = useQuery<Story[]>({
    queryKey: ["stories", "list"],
    queryFn: () => apiClient.listStories(20),
    refetchInterval: 12_000,
  });

  const createMutation = useMutation({
    mutationFn: () => apiClient.createIdeationStory(prompt.trim(), attachments),
    onSuccess: ({ story }) => {
      setPrompt("");
      setAttachments([]);
      setAttachmentError(null);
      router.push(`/ideation/${story.id}/angles`);
    },
  });

  const wordCount = countWords(prompt);
  const recent = (stories ?? []).slice(0, 6);

  function handleAttachmentChange(files: FileList | null) {
    if (!files?.length) return;
    const selected = Array.from(files);
    const valid: File[] = [];
    const rejected: string[] = [];

    selected.forEach((file) => {
      if (!isAllowedAttachment(file)) {
        rejected.push(`${file.name} is not a supported type`);
      } else if (file.size > MAX_ATTACHMENT_BYTES) {
        rejected.push(`${file.name} is larger than 10 MB`);
      } else {
        valid.push(file);
      }
    });

    const byKey = new Map(attachments.map((file) => [fileKey(file), file]));
    valid.forEach((file) => byKey.set(fileKey(file), file));
    const next = Array.from(byKey.values()).slice(0, MAX_ATTACHMENTS);
    if (byKey.size > MAX_ATTACHMENTS) {
      rejected.push(`Only ${MAX_ATTACHMENTS} attachments can be added`);
    }
    setAttachments(next);
    setAttachmentError(rejected.length ? rejected.join(". ") : null);
  }

  return (
    <div style={{ minHeight: "100%", background: "var(--color-background-tertiary)" }}>
      <div
        style={{
          height: 52,
          display: "flex",
          alignItems: "center",
          padding: "0 28px",
          background: "var(--color-background-primary)",
          borderBottom: "0.5px solid var(--color-border-tertiary)",
        }}
      >
        <span style={{ fontSize: 18, fontWeight: 500 }}>New story</span>
      </div>

      <div style={{ padding: 28, maxWidth: 920 }}>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 280px", gap: 18, alignItems: "start" }}>
          <section className="card" style={{ padding: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
              <MessageSquareText size={17} style={{ color: "var(--color-action)" }} />
              <h1 style={{ fontSize: 16, margin: 0 }}>What story you want to work on today?</h1>
            </div>

            <textarea
              value={prompt}
              onChange={(event) => {
                const next = event.target.value;
                if (countWords(next) <= PROMPT_MAX_WORDS) setPrompt(next);
              }}
              className="input"
              rows={9}
              placeholder="Start with a rough idea, question, headline, tension, character, company, policy, trend, or data point. I’ll help shape it into angles, a story hook, and chapters before script generation."
              style={{ resize: "vertical", fontFamily: "var(--font-sans)", background: "#fff" }}
              disabled={createMutation.isPending}
            />
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginTop: 8 }}>
              <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{wordCount}/{PROMPT_MAX_WORDS} words</span>
              <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>Tone and duration are decided by the backend.</span>
            </div>

            <div style={{ marginTop: 14 }}>
              <input
                ref={fileInputRef}
                type="file"
                accept={ATTACHMENT_ACCEPT}
                multiple
                onChange={(event) => {
                  handleAttachmentChange(event.target.files);
                  event.target.value = "";
                }}
                style={{ display: "none" }}
                disabled={createMutation.isPending}
              />
              <button
                type="button"
                className="btn-secondary"
                onClick={() => fileInputRef.current?.click()}
                disabled={createMutation.isPending || attachments.length >= MAX_ATTACHMENTS}
              >
                <Paperclip size={13} />
                Attach sources
              </button>
              <span style={{ marginLeft: 10, fontSize: 11, color: "var(--color-text-tertiary)" }}>
                PDF, DOCX, JPEG, XLS/XLSX
              </span>

              {attachments.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 10 }}>
                  {attachments.map((file) => (
                    <div
                      key={fileKey(file)}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "16px minmax(0, 1fr) auto 28px",
                        alignItems: "center",
                        gap: 8,
                        padding: "7px 0",
                        borderTop: "0.5px solid var(--color-border-tertiary)",
                      }}
                    >
                      <FileText size={14} style={{ color: "var(--color-text-secondary)" }} />
                      <span style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {file.name}
                      </span>
                      <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
                        {formatFileSize(file.size)}
                      </span>
                      <button
                        type="button"
                        className="btn-ghost"
                        aria-label={`Remove ${file.name}`}
                        title={`Remove ${file.name}`}
                        onClick={() => setAttachments((current) => current.filter((item) => fileKey(item) !== fileKey(file)))}
                        disabled={createMutation.isPending}
                        style={{ width: 28, height: 28, padding: 0 }}
                      >
                        <X size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {attachmentError && (
                <p role="alert" style={{ marginTop: 8, fontSize: 12, color: "var(--color-danger)" }}>
                  {attachmentError}.
                </p>
              )}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 16 }}>
              <button
                type="button"
                onClick={() => createMutation.mutate()}
                disabled={!prompt.trim() || createMutation.isPending}
                className="btn-primary"
              >
                {createMutation.isPending && <Loader2 size={13} className="animate-spin" />}
                Start ideation
              </button>
              {createMutation.isPending && (
                <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                  {attachments.length ? "Uploading sources and researching angles..." : "Researching the first set of angles..."}
                </span>
              )}
            </div>

            {createMutation.isError && (
              <div
                role="alert"
                style={{
                  marginTop: 14,
                  padding: "10px 12px",
                  borderRadius: "var(--border-radius-md)",
                  background: "var(--color-danger-bg)",
                  color: "var(--color-danger)",
                  fontSize: 13,
                  display: "flex",
                  gap: 8,
                }}
              >
                <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 2 }} />
                <span>
                  Could not start ideation: {createMutation.error instanceof Error ? createMutation.error.message : "Unknown error"}.
                </span>
              </div>
            )}
          </section>

          <aside className="card" style={{ padding: 16 }}>
            <p className="section-label" style={{ marginBottom: 10 }}>Recent stories</p>
            {recent.length === 0 ? (
              <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                Your drafts and scripts will appear here.
              </p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {recent.map((story) => (
                  <Link
                    key={story.id}
                    href={storyWorkspaceHref(story)}
                    style={{ textDecoration: "none", color: "inherit", display: "block" }}
                  >
                    <div style={{ borderBottom: "0.5px solid var(--color-border-tertiary)", paddingBottom: 8 }}>
                      <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {story.title}
                      </p>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        <span className={`badge ${storyStatusBadgeClass(story.status)}`} style={{ fontSize: 10 }}>
                          {storyStatusLabel(story.status)}
                        </span>
                        {isAdmin && story.owner_email && (
                          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{story.owner_email}</span>
                        )}
                        <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
                          {formatDistanceToNow(new Date(story.created_at), { addSuffix: true })}
                        </span>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
            {recent.length > 0 && (
              <Link href="/history" className="btn-secondary" style={{ width: "100%", marginTop: 12, textDecoration: "none" }}>
                View all
                <ChevronRight size={13} />
              </Link>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}

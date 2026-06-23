import type { StoryStatus } from "@/lib/api";

export const ANGLE_SELECTION_STOPPED_MESSAGE =
  "Script writing was stopped, as no angle was approved to proceed.";

const TERMINAL_STATUSES = new Set<string>([
  "completed",
  "failed",
  "angle_selection_expired",
]);

export function isTerminalStoryStatus(status: string | undefined): boolean {
  return Boolean(status && TERMINAL_STATUSES.has(status));
}

export function isAngleSelectionExpired(status: string | undefined): boolean {
  return status === "angle_selection_expired";
}

export function storyStatusLabel(status: StoryStatus | string): string {
  if (status === "ideating") return "Ideating";
  if (status === "angle_selection_expired") return "Script writing stopped";
  return status.replace(/_/g, " ");
}

export function storyStatusTitle(status: StoryStatus | string): string {
  const label = storyStatusLabel(status);
  return label.replace(/\b\w/g, (char) => char.toUpperCase());
}

export function storyStatusBadgeClass(status: StoryStatus | string): string {
  if (status === "completed") return "badge-success";
  if (status === "failed") return "badge-danger";
  if (status === "angle_selection_expired") return "badge-warning";
  if (status === "ideating") return "badge-neutral";
  return "badge-active";
}

const MARKDOWN_LINK_RE = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/gi;
const RAW_URL_RE = /https?:\/\/[^\s)\]]+/gi;
const PROMPT_LABEL_RE = /^\s{0,3}(?:[-*]\s*)?(?:research request|user follow-up instruction|prompt|query)\s*:/i;
const PROMPT_HEADING_RE = /^\s{0,3}#{1,6}\s*(?:research request|user follow-up instruction|prompt|query)\s*$/i;
const EMPTY_LINK_LABEL_RE = /^\s{0,3}(?:[-*]\s*)?(?:url|link|source url|citation url)\s*:\s*$/i;

export function cleanResearchReportBody(markdown: string): string {
  let skippingPromptBlock = false;

  return markdown
    .replace(/\r\n/g, "\n")
    .replace(MARKDOWN_LINK_RE, "$1")
    .replace(RAW_URL_RE, "")
    .split("\n")
    .filter((rawLine) => {
      const line = rawLine.trim();

      if (PROMPT_HEADING_RE.test(line)) {
        skippingPromptBlock = true;
        return false;
      }

      if (PROMPT_LABEL_RE.test(line)) {
        return false;
      }

      if (skippingPromptBlock) {
        if (!line) {
          skippingPromptBlock = false;
        }
        return false;
      }

      if (EMPTY_LINK_LABEL_RE.test(line)) {
        return false;
      }

      return true;
    })
    .join("\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

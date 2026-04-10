"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Download } from "lucide-react";
import type { FinalScript, ScriptSection } from "@/lib/api";

interface ScriptViewerProps {
  script: FinalScript;
}

export function ScriptViewer({ script }: ScriptViewerProps) {
  const [expandedSections, setExpandedSections] = useState<Set<number>>(
    new Set([1])
  );

  const toggleSection = (sectionNumber: number) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(sectionNumber)) {
        next.delete(sectionNumber);
      } else {
        next.add(sectionNumber);
      }
      return next;
    });
  };

  const handleDownload = () => printScriptAsPDF(script);

  return (
    <div className="space-y-4">
      <div className="surface-card p-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <h2 className="text-xl font-bold text-[color:var(--palette-ink)]">{script.title}</h2>
          <button onClick={handleDownload} className="action-primary px-4 py-2 flex-shrink-0">
            <Download className="w-4 h-4" />
            Download PDF
          </button>
        </div>
        <p className="text-[color:var(--palette-muted)] italic text-sm mb-4">
          &ldquo;{script.logline}&rdquo;
        </p>
        <div className="flex flex-wrap gap-6 text-sm">
          <Stat label="Duration" value={`~${script.estimated_duration_minutes} min`} />
          <Stat label="Word Count" value={script.total_word_count.toLocaleString()} />
          <Stat label="Acts" value={String(script.sections.length)} />
          <Stat label="Sources" value={String(script.sources.length)} />
        </div>
        <div className="mt-5 rounded-2xl border border-[rgba(28,33,170,0.14)] bg-[rgba(124,237,253,0.12)] p-4">
          <p className="text-xs font-semibold text-[color:var(--palette-primary)] uppercase tracking-wider mb-2">
            Opening Hook (0:00 – 0:30)
          </p>
          <p className="text-[color:var(--palette-ink)] text-sm leading-relaxed">{script.opening_hook}</p>
        </div>
      </div>

      <div className="space-y-3">
        {script.sections.map((section) => (
          <ActCard
            key={section.section_number}
            section={section}
            isExpanded={expandedSections.has(section.section_number)}
            onToggle={() => toggleSection(section.section_number)}
          />
        ))}
      </div>

      <div className="surface-card p-6">
        <p className="text-xs font-semibold text-[color:var(--palette-primary)] uppercase tracking-wider mb-2">
          Closing Statement
        </p>
        <p className="text-[color:var(--palette-ink)] leading-relaxed">{script.closing_statement}</p>
      </div>

      <SourcesList sources={script.sources} />
    </div>
  );
}

function ActCard({ section, isExpanded, onToggle }: {
  section: ScriptSection;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const durationMin = Math.floor(section.estimated_seconds / 60);
  const durationSec = section.estimated_seconds % 60;

  return (
    <div className="surface-card overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full px-5 py-4 flex items-center justify-between gap-4 hover:bg-[rgba(124,237,253,0.08)] transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <span className="w-7 h-7 rounded-full bg-[color:var(--palette-primary)] text-white flex items-center justify-center text-xs font-bold flex-shrink-0">
            {section.section_number}
          </span>
          <span className="font-semibold text-[color:var(--palette-ink)]">{section.title}</span>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          <span className="text-xs text-[color:var(--palette-muted)]">
            {durationMin}:{String(durationSec).padStart(2, "0")}
          </span>
          {isExpanded
            ? <ChevronUp className="w-4 h-4 text-[color:var(--palette-muted)]" />
            : <ChevronDown className="w-4 h-4 text-[color:var(--palette-muted)]" />}
        </div>
      </button>

      {isExpanded && (
        <div className="px-5 pb-5 pt-4 border-t border-[rgba(28,33,170,0.1)]">
          <p className="text-[color:var(--palette-ink)] text-sm leading-relaxed whitespace-pre-wrap">
            {section.narration}
          </p>
        </div>
      )}
    </div>
  );
}

function SourcesList({ sources }: { sources: FinalScript["sources"] }) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? sources : sources.slice(0, 5);

  return (
    <div className="surface-card p-6">
      <h3 className="text-sm font-semibold text-[color:var(--palette-primary)] uppercase tracking-wider mb-4">
        Sources ({sources.length})
      </h3>
      <ul className="space-y-2">
        {visible.map((src, i) => (
          <li key={i} className="flex items-start gap-2 text-xs">
            <span className={`px-2 py-1 rounded-full font-semibold flex-shrink-0 ${
              src.credibility === "high" ? "bg-green-50 text-green-700"
              : src.credibility === "medium" ? "bg-amber-50 text-amber-700"
              : "bg-[rgba(124,237,253,0.12)] text-[color:var(--palette-muted)]"
            }`}>
              {src.credibility?.toUpperCase()}
            </span>
            <span className="text-[color:var(--palette-muted)]">
              {src.url
                ? <a href={src.url} target="_blank" rel="noopener noreferrer"
                    className="hover:text-[color:var(--palette-primary)] transition-colors">{src.title}</a>
                : src.title}
            </span>
          </li>
        ))}
      </ul>
      {sources.length > 5 && (
        <button onClick={() => setShowAll(!showAll)}
          className="mt-3 text-xs text-[color:var(--palette-primary)]">
          {showAll ? "Show less" : `Show all ${sources.length} sources`}
        </button>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[color:var(--palette-muted)] text-xs">{label}</p>
      <p className="text-[color:var(--palette-ink)] font-semibold text-sm">{value}</p>
    </div>
  );
}

function printScriptAsPDF(script: FinalScript) {
  const actsHtml = script.sections.map(s => `
    <div class="act">
      <h3>Act ${s.section_number}: ${s.title}</h3>
      <p class="duration">${Math.floor(s.estimated_seconds / 60)}:${String(s.estimated_seconds % 60).padStart(2, "0")} min</p>
      <p>${s.narration.replace(/\n/g, "<br>")}</p>
    </div>
  `).join("");

  const sourcesHtml = script.sources.map((s, i) =>
    `<li>${i + 1}. [${s.credibility?.toUpperCase()}] ${s.title}${s.url ? ` — ${s.url}` : ""}</li>`
  ).join("");

  const html = `<!DOCTYPE html><html><head><meta charset="utf-8">
<title>${script.title}</title>
<style>
  body { font-family: Georgia, serif; max-width: 680px; margin: 40px auto; color: #111; font-size: 13px; line-height: 1.7; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  .logline { font-style: italic; color: #555; margin-bottom: 24px; }
  .hook { background: #f4f4f8; border-left: 3px solid #1c26a8; padding: 12px 16px; margin-bottom: 28px; }
  .hook h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: #1c26a8; margin-bottom: 6px; }
  .act { margin-bottom: 28px; page-break-inside: avoid; }
  .act h3 { font-size: 14px; font-weight: bold; border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-bottom: 4px; }
  .duration { font-size: 11px; color: #888; margin-bottom: 8px; }
  .closing { border-top: 1px solid #ddd; padding-top: 20px; margin-top: 28px; }
  ul.sources { font-size: 11px; color: #555; padding-left: 16px; }
  @media print { body { margin: 20px; } }
</style>
</head><body>
<h1>${script.title}</h1>
<p class="logline">"${script.logline}"</p>
<div class="hook"><h2>Opening Hook</h2><p>${script.opening_hook}</p></div>
${actsHtml}
<div class="closing"><h3>Closing Statement</h3><p>${script.closing_statement}</p></div>
<br><h3>Sources</h3><ul class="sources">${sourcesHtml}</ul>
</body></html>`;

  const win = window.open("", "_blank");
  if (!win) return;
  win.document.write(html);
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 400);
}

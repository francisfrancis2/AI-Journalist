"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Download, Film, Mic, Monitor } from "lucide-react";
import type { FinalScript, ScriptSection } from "@/lib/api";

interface ScriptViewerProps {
  script: FinalScript;
}

export function ScriptViewer({ script }: ScriptViewerProps) {
  const [expandedSections, setExpandedSections] = useState<Set<number>>(
    new Set([1]) // Open the first act by default
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

  const handleDownload = () => {
    const content = generatePlainTextScript(script);
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${script.title.replace(/[^a-z0-9]/gi, "_")}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      {/* Script Header */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div className="flex items-center gap-3">
            <Film className="w-6 h-6 text-indigo-400 flex-shrink-0" />
            <h2 className="text-xl font-bold">{script.title}</h2>
          </div>
          <button
            onClick={handleDownload}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-sm transition-colors flex-shrink-0"
          >
            <Download className="w-4 h-4" />
            Download
          </button>
        </div>

        {/* Logline */}
        <p className="text-indigo-300 italic text-sm mb-4">"{script.logline}"</p>

        {/* Stats row */}
        <div className="flex flex-wrap gap-6 text-sm">
          <Stat label="Duration" value={`~${script.estimated_duration_minutes} min`} />
          <Stat label="Word Count" value={script.total_word_count.toLocaleString()} />
          <Stat label="Acts" value={String(script.sections.length)} />
          <Stat label="Sources" value={String(script.sources.length)} />
        </div>

        {/* Opening Hook */}
        <div className="mt-5 p-4 rounded-lg bg-indigo-950/50 border border-indigo-900/50">
          <p className="text-xs font-semibold text-indigo-400 uppercase tracking-wider mb-2">
            Opening Hook (0:00 – 0:30)
          </p>
          <p className="text-gray-200 text-sm leading-relaxed">{script.opening_hook}</p>
        </div>
      </div>

      {/* Acts */}
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

      {/* Closing Statement */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
          Closing Statement
        </p>
        <p className="text-gray-200 leading-relaxed">{script.closing_statement}</p>
      </div>

      {/* Sources */}
      <SourcesList sources={script.sources} />
    </div>
  );
}

// ── Act Card ──────────────────────────────────────────────────────────────────

function ActCard({
  section,
  isExpanded,
  onToggle,
}: {
  section: ScriptSection;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const durationMin = Math.floor(section.estimated_seconds / 60);
  const durationSec = section.estimated_seconds % 60;

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 overflow-hidden">
      {/* Act Header — always visible */}
      <button
        onClick={onToggle}
        className="w-full px-5 py-4 flex items-center justify-between gap-4 hover:bg-gray-800/50 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <span className="w-7 h-7 rounded-full bg-indigo-700/50 text-indigo-300 flex items-center justify-center text-xs font-bold flex-shrink-0">
            {section.section_number}
          </span>
          <span className="font-semibold">{section.title}</span>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          <span className="text-xs text-gray-500">
            {durationMin}:{String(durationSec).padStart(2, "0")}
          </span>
          {isExpanded ? (
            <ChevronUp className="w-4 h-4 text-gray-500" />
          ) : (
            <ChevronDown className="w-4 h-4 text-gray-500" />
          )}
        </div>
      </button>

      {/* Act Body — expandable */}
      {isExpanded && (
        <div className="px-5 pb-5 space-y-4 border-t border-gray-800">
          {/* Narration */}
          <div className="pt-4">
            <div className="flex items-center gap-2 mb-2">
              <Mic className="w-3.5 h-3.5 text-gray-400" />
              <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                Narration
              </span>
            </div>
            <p className="text-gray-200 text-sm leading-relaxed whitespace-pre-wrap">
              {section.narration}
            </p>
          </div>

          {/* On-Screen Text */}
          {section.on_screen_text && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Monitor className="w-3.5 h-3.5 text-amber-400" />
                <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">
                  On Screen
                </span>
              </div>
              <div className="bg-gray-800 rounded px-3 py-2 text-amber-200 text-sm font-mono">
                {section.on_screen_text}
              </div>
            </div>
          )}

          {/* B-Roll Suggestions */}
          {section.b_roll_suggestions.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-violet-400 uppercase tracking-wider mb-2">
                B-Roll
              </p>
              <ul className="space-y-1">
                {section.b_roll_suggestions.map((item, i) => (
                  <li key={i} className="text-xs text-gray-400 flex items-start gap-2">
                    <span className="text-violet-600 mt-0.5">▸</span>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Interview Cues */}
          {section.interview_cues.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-teal-400 uppercase tracking-wider mb-2">
                Interview Cues
              </p>
              <ul className="space-y-1">
                {section.interview_cues.map((item, i) => (
                  <li key={i} className="text-xs text-gray-400 flex items-start gap-2">
                    <span className="text-teal-600 mt-0.5">?</span>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Sources List ──────────────────────────────────────────────────────────────

function SourcesList({ sources }: { sources: FinalScript["sources"] }) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? sources : sources.slice(0, 5);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">
        Sources ({sources.length})
      </h3>
      <ul className="space-y-2">
        {visible.map((src, i) => (
          <li key={i} className="flex items-start gap-2 text-xs">
            <span
              className={`px-1.5 py-0.5 rounded font-semibold flex-shrink-0 ${
                src.credibility === "high"
                  ? "bg-green-900/50 text-green-400"
                  : src.credibility === "medium"
                  ? "bg-amber-900/50 text-amber-400"
                  : "bg-gray-800 text-gray-500"
              }`}
            >
              {src.credibility?.toUpperCase()}
            </span>
            <span className="text-gray-300">
              {src.url ? (
                <a
                  href={src.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-indigo-300 transition-colors"
                >
                  {src.title}
                </a>
              ) : (
                src.title
              )}
            </span>
          </li>
        ))}
      </ul>
      {sources.length > 5 && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="mt-3 text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
        >
          {showAll ? "Show less" : `Show all ${sources.length} sources`}
        </button>
      )}
    </div>
  );
}

// ── Helper ────────────────────────────────────────────────────────────────────

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-gray-500 text-xs">{label}</p>
      <p className="text-white font-semibold text-sm">{value}</p>
    </div>
  );
}

function generatePlainTextScript(script: FinalScript): string {
  const lines: string[] = [
    script.title.toUpperCase(),
    "=".repeat(script.title.length),
    "",
    `Logline: ${script.logline}`,
    "",
    "OPENING HOOK",
    script.opening_hook,
    "",
  ];

  for (const section of script.sections) {
    lines.push(
      `${"─".repeat(60)}`,
      `ACT ${section.section_number}: ${section.title.toUpperCase()}`,
      `(~${Math.floor(section.estimated_seconds / 60)}:${String(section.estimated_seconds % 60).padStart(2, "0")})`,
      "",
      "NARRATION:",
      section.narration,
      "",
    );
    if (section.on_screen_text) {
      lines.push(`[ON SCREEN]: ${section.on_screen_text}`, "");
    }
    if (section.b_roll_suggestions.length) {
      lines.push("B-ROLL:", ...section.b_roll_suggestions.map((b) => `  • ${b}`), "");
    }
    if (section.interview_cues.length) {
      lines.push("INTERVIEWS:", ...section.interview_cues.map((q) => `  ? ${q}`), "");
    }
  }

  lines.push(
    "─".repeat(60),
    "CLOSING STATEMENT",
    script.closing_statement,
    "",
    "─".repeat(60),
    "SOURCES",
    ...script.sources.map((s, i) => `${i + 1}. [${s.credibility?.toUpperCase()}] ${s.title} — ${s.url ?? "N/A"}`),
  );

  return lines.join("\n");
}

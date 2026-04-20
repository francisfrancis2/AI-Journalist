"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Download } from "lucide-react";
import type { FinalScript, ScriptSection } from "@/lib/api";
import { downloadScriptPdf } from "@/lib/script-export";

interface ScriptViewerProps {
  script: FinalScript;
}

const CREDIBILITY_COLORS: Record<string, string> = {
  high:   "var(--color-success, #16a34a)",
  medium: "var(--color-warning, #ca8a04)",
  low:    "var(--color-danger,  #dc2626)",
};

export function ScriptViewer({ script }: ScriptViewerProps) {
  const [open, setOpen] = useState<number[]>([0]);
  const toggle = (i: number) =>
    setOpen((p) => (p.includes(i) ? p.filter((x) => x !== i) : [...p, i]));

  const hasSources = script.sources.length > 0;

  return (
    <div>
      <div style={{ display: "flex", gap: 24 }}>
        {/* Left: TOC */}
        <div style={{ width: 180, flexShrink: 0 }}>
          <div className="card" style={{ padding: "14px 16px", position: "sticky", top: 24 }}>
            <p className="section-label">Contents</p>
            <ol style={{ listStyle: "none", padding: 0, margin: 0 }}>
              <li style={{ padding: "5px 0", fontSize: 12, color: "var(--color-text-secondary)", borderBottom: "0.5px solid var(--color-border-tertiary)", marginBottom: 4 }}>
                Opening
              </li>
              {script.sections.map((s, i) => (
                <li
                  key={i}
                  style={{ padding: "5px 0", fontSize: 12, color: "var(--color-text-secondary)", cursor: "pointer" }}
                  onClick={() => { if (!open.includes(i)) toggle(i); }}
                >
                  {s.section_number}. {s.title}
                </li>
              ))}
              <li style={{ padding: "5px 0", fontSize: 12, color: "var(--color-text-secondary)", borderTop: "0.5px solid var(--color-border-tertiary)", marginTop: 4 }}>
                Closing
              </li>
              {hasSources && (
                <li style={{ padding: "5px 0", fontSize: 12, borderTop: "0.5px solid var(--color-border-tertiary)", marginTop: 4 }}>
                  <a
                    href="#sources-appendix"
                    style={{ color: "var(--color-action)", textDecoration: "none" }}
                  >
                    Sources ({script.sources.length})
                  </a>
                </li>
              )}
            </ol>
          </div>
        </div>

        {/* Right: script body */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Metadata row */}
          <div className="card" style={{ padding: "14px 18px", marginBottom: 16, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <div style={{ display: "flex", gap: 16, fontSize: 12, color: "var(--color-text-secondary)" }}>
              <span>~{script.estimated_duration_minutes} min</span>
              <span>{script.total_word_count.toLocaleString()} words</span>
              <span>{script.sections.length} acts</span>
            </div>
            <button
              onClick={() => downloadScriptPdf(script)}
              className="btn-secondary"
              style={{ flexShrink: 0 }}
            >
              <Download size={13} />
              Download PDF
            </button>
          </div>

          {/* Logline */}
          <div className="card" style={{ padding: "18px 20px", marginBottom: 16 }}>
            <div className="section-rule"><span>Logline</span></div>
            <p style={{ fontSize: 13, lineHeight: 1.7 }}>{script.logline}</p>
          </div>

          {/* Opening hook */}
          <div className="card" style={{ padding: "18px 20px", marginBottom: 16 }}>
            <div className="section-rule"><span>Opening Hook</span></div>
            <p style={{ fontSize: 13, lineHeight: 1.7 }}>{script.opening_hook}</p>
          </div>

          {/* Acts */}
          {script.sections.map((section, i) => (
            <ActCard
              key={i}
              section={section}
              isOpen={open.includes(i)}
              onToggle={() => toggle(i)}
            />
          ))}

          {/* Closing */}
          <div className="card" style={{ padding: "18px 20px", marginBottom: 16 }}>
            <div className="section-rule"><span>Closing Statement</span></div>
            <p style={{ fontSize: 13, lineHeight: 1.7 }}>{script.closing_statement}</p>
          </div>

          {/* Sources Appendix */}
          {hasSources && <SourcesAppendix sources={script.sources} />}
        </div>
      </div>
    </div>
  );
}

function ActCard({
  section,
  isOpen,
  onToggle,
}: {
  section: ScriptSection;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="card" style={{ marginBottom: 10, overflow: "hidden" }}>
      <button
        onClick={onToggle}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 20px",
          background: "none",
          border: "none",
          cursor: "pointer",
          fontFamily: "var(--font-sans)",
          textAlign: "left",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span
            style={{
              width: 20,
              height: 20,
              background: "var(--color-action)",
              color: "#fff",
              borderRadius: 4,
              fontSize: 11,
              fontWeight: 500,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            {section.section_number}
          </span>
          <span style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text-primary)" }}>
            {section.title}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {Math.round(section.estimated_seconds / 60)} min
          </span>
          {isOpen
            ? <ChevronUp size={14} style={{ color: "var(--color-text-tertiary)" }} />
            : <ChevronDown size={14} style={{ color: "var(--color-text-tertiary)" }} />}
        </div>
      </button>

      {isOpen && (
        <div style={{ padding: "16px 20px 20px", borderTop: "0.5px solid var(--color-border-tertiary)" }}>
          <p style={{ fontSize: 13, lineHeight: 1.8 }}>{section.narration}</p>
        </div>
      )}
    </div>
  );
}

function SourcesAppendix({ sources }: { sources: FinalScript["sources"] }) {
  return (
    <div id="sources-appendix" className="card" style={{ padding: "18px 20px" }}>
      <div className="section-rule"><span>Appendix: Sources</span></div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 4 }}>
        {sources.map((src, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              gap: 12,
              padding: "10px 12px",
              background: "var(--color-background-secondary, #f8f8fa)",
              borderRadius: 6,
              border: "0.5px solid var(--color-border-tertiary)",
            }}
          >
            {/* Index */}
            <span
              style={{
                flexShrink: 0,
                width: 22,
                height: 22,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: "var(--color-border-tertiary)",
                borderRadius: 4,
                fontSize: 11,
                fontWeight: 600,
                color: "var(--color-text-secondary)",
                marginTop: 1,
              }}
            >
              {i + 1}
            </span>

            {/* Details */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 3 }}>
                {src.url ? (
                  <a
                    href={src.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      fontSize: 13,
                      fontWeight: 500,
                      color: "var(--color-action)",
                      textDecoration: "none",
                      wordBreak: "break-word",
                    }}
                  >
                    {src.title} ↗
                  </a>
                ) : (
                  <span style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text-primary)", wordBreak: "break-word" }}>
                    {src.title}
                  </span>
                )}

                {src.credibility && (
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 600,
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                      color: CREDIBILITY_COLORS[src.credibility] ?? "var(--color-text-tertiary)",
                      padding: "1px 5px",
                      border: `1px solid ${CREDIBILITY_COLORS[src.credibility] ?? "var(--color-border-tertiary)"}`,
                      borderRadius: 3,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {src.credibility}
                  </span>
                )}
              </div>

              <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                {src.type && (
                  <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", textTransform: "capitalize" }}>
                    {src.type.replace(/_/g, " ")}
                  </span>
                )}
                {src.url && (
                  <span
                    style={{
                      fontSize: 11,
                      color: "var(--color-text-tertiary)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      maxWidth: 360,
                    }}
                    title={src.url}
                  >
                    {src.url}
                  </span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
